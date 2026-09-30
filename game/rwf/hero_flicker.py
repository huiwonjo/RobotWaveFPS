"""FLICKER (HERO_B owns this file): Tracer-style flanker (spec 3.0, 3.2, 3.4).

Kit
- LMB  TWIN PISTOLS. Hitscan, 12 damage (crit x2 = 24), 20 shots/s through a time accumulator (several
  traces in one frame when dt > 0.05), the two guns alternating. Mag 40, reload 1.0 s. Falloff: full up to
  5 cells, linear to 50% at 10 cells, 50% beyond (Hero.fire_hitscan falloff, measured along the ray).
- SHIFT / SPACE / RMB / F  BLINK. 3 charges, one back every 3.0 s, one after another. 3.5 cells along the
  WASD direction relative to the view (forward with no input), stepped 0.1 with world.dash_target and
  stopping 0.3 short of any wall. Passes through enemies. Not usable while rewinding or rooted.
- E  REWIND. A ring buffer of 30 samples at 10 Hz of (x, y, angle, health, ammo), taken in after_move.
  Travel runs from think() (on_input is gated while lock_input is set): 0.5 s back along the recorded
  path, newest to oldest, at constant speed along the path, with `invuln` and no actions. At the end:
  position = oldest sample, health = max(current, oldest sample), ammo = 40 (a full mag is >= any
  recorded ammo), reload cancelled, buffer cleared. Cooldowns and ult are untouched. Cooldown 12 s.
- Q  PULSE BOMB. PulseBombShot (a Projectile subclass) flies at 12 cells/s, radius 0.25, up to 6 cells.
  It sticks to the first enemy it touches, to a wall or an enemy barrier on contact, or drops to the
  floor at max range, and becomes a PulseBomb effect: fuse 1.0 s from that moment, following its target
  (staying put if the target dies), then 350 to the stuck target and a 350 -> 105 splash over r 2.5
  (LOS from the bomb; barriers ignored; no self-damage).

Presentation (viewmodel ported from the original draw_gun, overlays, crosshair, icons) is at the bottom of
this file and never feeds back into gameplay.
"""
import math
from collections import deque

import pygame

from . import core
from .combat import Effect, Enemy, Projectile, apply_damage, splash
from .config import TEAM_PLAYER, W, H
from .hero_base import Ability, Hero
from .world import dash_target, is_wall

# Spec 3.2 numbers. The integrator may retune these after playtesting.
TUNING = {
    # primary: TWIN PISTOLS
    'pistol_damage': 12.0,
    'pistol_interval': 0.05,            # 20 shots/s
    'pistol_falloff': (5.0, 10.0, 0.5),  # (full damage until, min reached at, min multiplier)
    'pistol_spread': 0.014,             # rad of random yaw; pitch jitter = spread x 768 = +-11 px
    # SHIFT / RMB / F: BLINK
    'blink_charges': 3,
    'blink_cd': 3.0,                    # per charge, recharged one after another
    'blink_dist': 3.5,
    'blink_step': 0.1,
    'blink_margin': 0.3,
    'blink_fx': 0.12,                   # speed-line overlay length (s)
    # E: REWIND
    'rewind_cd': 12.0,
    'rewind_samples': 30,
    'rewind_hz': 10.0,
    'rewind_time': 0.5,
    # Q: PULSE BOMB
    'bomb_speed': 12.0,
    'bomb_radius': 0.25,
    'bomb_range': 6.0,
    'bomb_fuse': 1.0,
    'bomb_blast_r': 2.5,
    'bomb_stuck_damage': 350.0,
    'bomb_center': 350.0,
    'bomb_edge': 105.0,
    'bomb_beep': 0.2,
    'bomb_ring_hz': 8.0,
    'bomb_shake': (8.0, 0.3),
    'bomb_flash': 0.3,                  # ring flash after the blast (s)
    # viewmodel
    'kick_px': 30.0,
    'kick_time': 0.09,
}

BOMB_BLUE = (60, 140, 255)
BOMB_RING = (80, 170, 255)
WHITE = (255, 255, 255)
BOMB_FLOOR_Z = 0.06


def _blocked(x, y, r):
    """True when the square body footprint of half-size r at (x, y) overlaps a wall cell."""
    return is_wall(x - r, y - r) or is_wall(x + r, y - r) or is_wall(x - r, y + r) or is_wall(x + r, y + r)


@core.register_hero
class Flicker(Hero):
    KEY = 'flicker'
    NAME = 'FLICKER'
    ROLE = 'DAMAGE'
    DIFFICULTY = 3
    COLOR = (255, 150, 40)
    BLURB = 'Blink through fights, rewind mistakes.'
    KIT = (('LMB', 'TWIN PISTOLS', 'Rapid fire. Falls off past 10 m.'),
           ('RMB/F', 'BLINK (3 CHARGES)', 'Or SHIFT. Zip 7 m the way you move.'),
           ('E', 'REWIND', 'Jump back 3 s. Health and ammo return.'),
           ('V', 'QUICK MELEE', 'A quick punch.'),
           ('Q', 'PULSE BOMB', 'Sticky bomb. Huge blast after 1 s.'))
    LABELS = {'primary': 'PISTOLS', 'ult': 'PULSE BOMB', 'melee': 'MELEE'}
    HEALTH = 150
    ARMOR = 0
    SHIELDS = 0
    SPEED = 4.6
    ULT_COST = 1100
    ULT_NAME = 'PULSE BOMB'
    ULT_CALLOUT = 'BOMB AWAY!'
    ULT_DURATION = 0.0
    MAX_AMMO = 40
    RELOAD_TIME = 1.0
    HUD_ORDER = ('ab1', 'ab2')

    def __init__(self, world):
        super().__init__(world)
        T = TUNING
        # RMB/F and SHIFT/SPACE both use 'ab1' (spec 3.2): no separate 'secondary' entry, so 2 HUD tiles.
        self.abilities = {
            'ab1': Ability(self, 'ab1', 'BLINK', 'SHIFT', T['blink_cd'], charges=T['blink_charges']),
            'ab2': Ability(self, 'ab2', 'REWIND', 'E', T['rewind_cd'], duration=T['rewind_time']),
        }
        self.spread = T['pistol_spread']
        self._acc = T['pistol_interval']    # fire credit (s); a full interval = the next press fires at once
        self._was_firing = False
        self._gun = 0                       # next gun to fire: 0 right, 1 left
        self.gun_fired = [-9.0, -9.0]       # sim time of each gun's last shot (viewmodel kick, flash)
        self.last_blink = -9.0
        self.blink_from = None
        self.blink_to = None
        self.history = deque(maxlen=int(T['rewind_samples']))
        self._next_sample = 0.0
        self.rewind = None                  # dict while travelling back, else None
        self.rewind_started = -9.0
        self.bomb = None                    # the last PulseBombShot / PulseBomb thrown

    # --- input (only while the hero can act) -------------------------------------------
    def on_input(self, inp, world):
        if inp.hit('ab1') or inp.hit('alt'):
            self.blink(world)
        if inp.hit('ab2') and self.start_rewind(world):
            return
        self._fire(inp, world)

    def _fire(self, inp, world):
        iv = TUNING['pistol_interval']
        dt = world.dt
        if not inp.down('fire') or self.reloading or self.ammo <= 0:
            self._acc = min(self._acc + dt, iv)
            self._was_firing = False
            return
        if self._was_firing:
            self._acc += dt
        else:
            # the time before this frame's press was not firing time: at most one shot is banked
            self._acc = min(self._acc + dt, iv)
            self._was_firing = True
        n = 0
        while self._acc >= iv - 1e-9 and n < 32:
            self._acc -= iv
            n += 1
            if not self.use_ammo():
                break
            self._shoot(world)
            if self.ammo <= 0:
                self.start_reload(world)        # fire is held: the reload starts on its own
                break
        if self.reloading:
            self._acc = min(self._acc, iv)
            self._was_firing = False

    def _shoot(self, world):
        g = self._gun
        self._gun = g ^ 1
        self.gun_fired[g] = world.now
        self.fire_hitscan(world, TUNING['pistol_damage'], spread=self.spread, falloff=TUNING['pistol_falloff'])

    # --- BLINK ---------------------------------------------------------------------------
    def blink(self, world):
        ab = self.abilities['ab1']
        if self.rewind is not None or not self.status.can_move(world.now) or not ab.ready():
            return False
        if not ab.use(world):
            return False
        f, r = self.move_fwd, self.move_right
        if not f and not r:
            f = 1
        ang = self.angle + math.atan2(r, f)
        T = TUNING
        ox, oy = self.x, self.y
        self.x, self.y = dash_target(ox, oy, ang, T['blink_dist'], T['blink_step'], T['blink_margin'])
        self.blink_from = (ox, oy)
        self.blink_to = (self.x, self.y)
        self.last_blink = world.now
        world.bus.emit('sfx', name='blink', vol=1.0)
        return True

    # --- REWIND --------------------------------------------------------------------------
    def start_rewind(self, world):
        ab = self.abilities['ab2']
        if self.rewind is not None or not ab.use(world):
            return False
        now = world.now
        T = TUNING
        hist = self.history
        pts = [(self.x, self.y)]
        for s in reversed(hist):                    # newest -> oldest
            pts.append((s[0], s[1]))
        oldest = hist[0] if hist else (self.x, self.y, self.angle, self.pool.health, self.ammo)
        cum = [0.0]
        for i in range(1, len(pts)):
            cum.append(cum[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
        self.rewind = {'pts': pts, 'cum': cum, 't': 0.0, 'oldest': oldest}
        self.rewind_started = now
        self.lock_input = True
        self.status.add('invuln', T['rewind_time'], now)
        ab.start(T['rewind_time'])
        self.cancel_reload()
        self._acc = T['pistol_interval']
        self._was_firing = False
        # spec: SFX blink played pitched down; 'variant' lets sfx.py pick a pitched-down copy if it has one
        world.bus.emit('sfx', name='blink', vol=0.8, variant='rewind')
        return True

    def _path_point(self, k):
        rw = self.rewind
        pts = rw['pts']
        cum = rw['cum']
        total = cum[-1]
        if total < 1e-9:
            return pts[-1]
        target = k * total
        i = 1
        n = len(pts)
        while i < n - 1 and cum[i] < target:
            i += 1
        seg = cum[i] - cum[i - 1]
        u = (target - cum[i - 1]) / seg if seg > 1e-9 else 1.0
        u = 0.0 if u < 0.0 else (1.0 if u > 1.0 else u)
        (ax, ay), (bx, by) = pts[i - 1], pts[i]
        return ax + (bx - ax) * u, ay + (by - ay) * u

    def think(self, world, dt):
        rw = self.rewind
        if rw is None:
            return
        self.custom_motion = True
        rw['t'] += dt
        k = rw['t'] / TUNING['rewind_time']
        if k >= 1.0 - 1e-6:
            self._finish_rewind(world)
            return
        x, y = self._path_point(k)
        # samples are 0.1 s apart, so a straight line between two of them can clip a corner (blink,
        # knockback): keep the last good point there; the end snaps to the oldest sample anyway.
        if not _blocked(x, y, self.radius * 0.8):
            self.x, self.y = x, y

    def _finish_rewind(self, world):
        rw = self.rewind
        ox, oy, _oa, ohealth, _oammo = rw['oldest']
        if not is_wall(ox, oy):
            self.x, self.y = ox, oy
        p = self.pool
        p.health = min(p.max_health, max(p.health, ohealth))
        self.ammo = self.MAX_AMMO
        self.cancel_reload()
        self.history.clear()
        self._next_sample = world.now               # sample the landing spot this frame
        self.lock_input = False
        self.abilities['ab2'].stop()
        self.rewind = None

    def after_move(self, world, dt):
        if self.rewind is not None:
            return
        now = world.now
        if now >= self._next_sample - 1e-9:
            self.history.append((self.x, self.y, self.angle, self.pool.health, self.ammo))
            step = 1.0 / TUNING['rewind_hz']
            self._next_sample += step
            if self._next_sample <= now:
                self._next_sample = now + step

    # --- PULSE BOMB ----------------------------------------------------------------------
    def on_ult(self, world):
        shot = PulseBombShot(self)
        self.bomb = shot
        if not world.add_projectile(shot):
            shot.land(world, self.x, self.y, BOMB_FLOOR_Z, None)   # never lose the ult to the cap

    def on_removed(self, world):
        for pr in world.projectiles:
            if isinstance(pr, PulseBombShot) and pr.owner is self:
                pr.alive = False
        for ef in world.effects:
            if isinstance(ef, PulseBomb) and ef.owner is self:
                ef.alive = False
        if self.rewind is not None:
            self.rewind = None
            self.lock_input = False

    # --- presentation ----------------------------------------------------------------------
    def draw_viewmodel(self, surf, world):
        if self.rewind is not None or not self.alive:
            return                                  # hidden while rewinding
        vm = _assets()
        now = world.now
        if self.move_fwd or self.move_right:
            bob_x = math.sin(now * 4.5) * 5.0
            bob_y = abs(math.sin(now * 9.0)) * 7.0
        else:
            bob_x = math.sin(now * 0.9) * 2.0
            bob_y = math.sin(now * 1.8) * 4.0
        kt = TUNING['kick_time']
        for g in (0, 1):
            age = now - self.gun_fired[g]
            k = (1.0 - age / kt) if 0.0 <= age < kt else 0.0
            y = GUN_Y + bob_y + TUNING['kick_px'] * k
            if g == 0:
                x = GUN_RIGHT_X + bob_x + 8.0 * k
                surf.blit(vm['gun_r'], (int(x), int(y)))
                mx = x - 3
            else:
                x = W - GUN_RIGHT_X - GUN_W - bob_x - 8.0 * k
                surf.blit(vm['gun_l'], (int(x), int(y)))
                mx = x + GUN_W + 3
            if 0.0 <= age < 0.06:
                fs = vm['flash'][0 if age < 0.02 else (1 if age < 0.04 else 2)]
                surf.blit(fs, (int(mx) - fs.get_width() // 2, int(y) + MUZZLE_DY - fs.get_height() // 2))

    def draw_overlay(self, surf, world):
        now = world.now
        if self.rewind is not None:
            _draw_rewind_fx(surf, now - self.rewind_started)
        age = now - self.last_blink
        if 0.0 <= age < TUNING['blink_fx']:
            _draw_blink_fx(surf, age / TUNING['blink_fx'])

    def draw_crosshair(self, surf, world):
        cx, cy = W // 2, H // 2
        gap = 8 + (6 if world.now - self.last_fire < 0.1 else 0)
        ln = 7
        col = (255, 255, 255)
        fill = surf.fill
        fill(col, (cx - gap - ln, cy - 1, ln, 2))
        fill(col, (cx + gap + 1, cy - 1, ln, 2))
        fill(col, (cx - 1, cy - gap - ln, 2, ln))
        fill(col, (cx - 1, cy + gap + 1, 2, ln))

    @classmethod
    def draw_icon(cls, slot, surf, rect):
        rect = pygame.Rect(rect)
        fn = _ICONS.get(slot, _icon_blink)
        fn(surf, rect, cls.COLOR)


# ============================ Pulse Bomb =====================================
class PulseBombShot(Projectile):
    """The thrown bomb. Every impact makes it stick (the default projectile impact never runs)."""

    def __init__(self, hero):
        T = TUNING
        super().__init__(hero.x, hero.y, hero.angle, T['bomb_speed'], team=TEAM_PLAYER, damage=0.0,
                         radius=T['bomb_radius'], owner=hero, ability='ult',
                         ttl=T['bomb_range'] / T['bomb_speed'] - 1e-6,     # the epsilon: no extra frame
                         z=0.42, color=BOMB_BLUE, core=WHITE, size=0.075)
        self.on_hit = self._on_hit
        self.on_expire = self._on_expire
        self.stuck = None

    def _on_hit(self, world, proj, target, x, y):
        if isinstance(target, Enemy):
            self.land(world, target.x, target.y, self.z, target)
        else:                                   # a wall (None) or an enemy barrier: stick at the contact
            self.land(world, x, y, self.z, None)
        return True

    def _on_expire(self, world, proj):
        # max range: drops to the floor exactly 6 cells out (the last frame may have overshot a little;
        # pulling back along the flown path can't enter a wall)
        x, y = self.x, self.y
        dx, dy = x - self.ox, y - self.oy
        d = math.hypot(dx, dy)
        rng = TUNING['bomb_range']
        if d > rng > 0.0:
            x = self.ox + dx / d * rng
            y = self.oy + dy / d * rng
        self.land(world, x, y, BOMB_FLOOR_Z, None)

    def land(self, world, x, y, z, target):
        self.alive = False
        fx = PulseBomb(self.owner, world, x, y, z, target)
        self.stuck = fx
        if self.owner is not None:
            self.owner.bomb = fx
        if not world.add_effect(fx):
            fx.explode(world)                   # effect cap: blow up now rather than lose the ult


class PulseBomb(Effect):
    """A stuck or landed Pulse Bomb: beeps, follows its target, explodes 1.0 s after it stuck."""

    def __init__(self, owner, world, x, y, z, target=None):
        self.owner = owner
        self.alive = True
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.target = target
        self.face_off = 0.0
        self.stuck_at = world.now
        self.next_beep = world.now
        self.state = 'armed'                    # 'armed' -> 'flash' -> dead
        self.exploded_at = None
        self.hit = []
        if target is not None:
            self._follow()
        self.minimap_ring = (self.x, self.y, TUNING['bomb_blast_r'], BOMB_RING)

    def _follow(self):
        t = self.target
        self.x = t.x
        self.y = t.y
        self.z = t.z0 + t.height * t.height_mult * 0.5
        self.face_off = t.radius * 0.9

    def update(self, world, dt):
        now = world.now
        T = TUNING
        if self.state == 'armed':
            t = self.target
            if t is not None:
                if t.alive:
                    self._follow()
                else:
                    self.target = None          # the target died: the bomb stays where it was
            fuse_end = self.stuck_at + T['bomb_fuse']
            while self.next_beep <= now + 1e-9 and self.next_beep < fuse_end - 1e-6:
                world.bus.emit('sfx', name='beep', vol=0.9)
                self.next_beep += T['bomb_beep']
            self.minimap_ring = (self.x, self.y, T['bomb_blast_r'], BOMB_RING)
            if now - self.stuck_at >= T['bomb_fuse'] - 1e-6:
                self.explode(world)
        elif now - self.exploded_at >= T['bomb_flash']:
            self.alive = False

    def explode(self, world):
        if self.state != 'armed':
            return
        T = TUNING
        self.state = 'flash'
        self.exploded_at = world.now
        self.minimap_ring = None
        t = self.target if (self.target is not None and self.target.alive) else None
        src = self.owner
        x, y = self.x, self.y
        if t is not None:
            apply_damage(world, t, T['bomb_stuck_damage'], src, ability='ult', from_xy=(x, y))
        self.hit = splash(world, x, y, T['bomb_blast_r'], T['bomb_center'], T['bomb_edge'], src, TEAM_PLAYER,
                          'ult', exclude=(t,) if t is not None else (), ignore_barriers=True)
        if t is not None:
            self.hit.insert(0, t)
        world.burst(x, y, self.z, 12, BOMB_BLUE, 3.5, 0.6, 3)
        world.burst(x, y, self.z, 12, WHITE, 2.5, 0.45, 2)
        world.shake(*T['bomb_shake'])

    def emit_visuals(self, scene):
        T = TUNING
        now = scene.now
        x, y, z = self.x, self.y, self.z
        if self.face_off > 0.0 and self.state == 'armed':
            # sit on the side of the target that faces the camera (also right in POTG replays)
            dx = scene.cam[0] - x
            dy = scene.cam[1] - y
            d = math.hypot(dx, dy)
            if d > 1e-6:
                off = min(self.face_off, d * 0.5)
                x += dx / d * off
                y += dy / d * off
        r = T['bomb_blast_r']
        if self.state == 'armed':
            age = now - self.stuck_at
            on = int(age * 2.0 * T['bomb_ring_hz']) % 2 == 0
            scene.orb(x, y, z, 0.085 if on else 0.07, BOMB_BLUE, WHITE)
            if on:
                scene.ring(self.x, self.y, r, BOMB_RING, 2, 28)
        else:
            k = min(1.0, max(0.0, (now - self.exploded_at) / T['bomb_flash']))
            if k < 0.5:
                scene.orb(x, y, z, 0.45 * (1.0 - 2.0 * k) + 0.05, (170, 215, 255), WHITE)
            scene.ring(self.x, self.y, r * (0.3 + 0.7 * k), WHITE, 3, 28)
            scene.ring(self.x, self.y, r, BOMB_RING, 2, 28)


# ============================ presentation ===================================
# Layout numbers for the viewmodel (1024x768 space). The later UI pass may move these freely.
GUN_W, GUN_H = 185, 130
GUN_RIGHT_X = 668           # left edge (barrel tip) of the right gun; the left gun is its mirror image
GUN_Y = 590                 # top of both guns: bodies clear the HUD band (y >= 668), grips run into it
MUZZLE_DY = 22
FLASH_R = (22, 15, 9)       # muzzle-flash radii, big -> small (pre-rendered once)
_A = {}


def _paint_gun(s):
    """The original twin-pistol look (game/main.py draw_gun), as the RIGHT gun with its barrel tip at x 0."""
    rect = pygame.draw.rect
    rect(s, (45, 50, 62), (0, 12, 110, 20))                 # barrel
    rect(s, (0, 210, 110), (0, 12, 110, 5))                 # barrel stripe
    s.fill((78, 86, 104), (2, 17, 106, 1))                  # barrel highlight
    rect(s, (38, 42, 55), (90, 6, 95, 60))                  # body
    rect(s, (0, 180, 230), (90, 18, 80, 7))                 # body stripe
    rect(s, (70, 80, 100), (90, 6, 95, 60), 1)              # body outline
    rect(s, (30, 33, 42), (90, 60, 32, 70))                 # grip
    rect(s, (50, 55, 70), (90, 60, 32, 70), 1)
    rect(s, (55, 60, 75), (60, 0, 35, 14))                  # scope
    rect(s, (0, 200, 220), (65, 3, 25, 6))                  # scope glass
    s.fill((60, 66, 82), (0, 31, 110, 1))                   # barrel underside line


def _paint_flash(r):
    size = r * 5 + 2
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size // 2
    for a in range(0, 360, 40):
        ang = math.radians(a)
        pygame.draw.line(s, (255, 210, 50, 230), (c, c),
                         (c + int(math.cos(ang) * r * 2.2), c + int(math.sin(ang) * r * 2.2)), max(1, r // 6))
    pygame.draw.circle(s, (255, 255, 200, 220), (c, c), r)
    pygame.draw.circle(s, (255, 230, 80, 200), (c, c), max(1, r // 2))
    return s


def _blink_lines():
    cx, cy = W // 2, H // 2
    out = []
    for i in range(16):
        a = (i + 0.5) * math.tau / 16 + 0.07 * math.sin(i * 2.3)
        ca, sa = math.cos(a), math.sin(a)
        t = min((W / 2) / abs(ca) if abs(ca) > 1e-6 else 1e9, (H / 2) / abs(sa) if abs(sa) > 1e-6 else 1e9)
        out.append((cx + ca * t, cy + sa * t, ca * t, sa * t, 0.06 * math.sin(i * 1.7)))
    return out


def _assets():
    """Lazily built once (after set_mode): the two guns, 3 muzzle flashes and the blink line table."""
    if _A:
        return _A
    gun = pygame.Surface((GUN_W, GUN_H), pygame.SRCALPHA)
    _paint_gun(gun)
    flashes = [_paint_flash(r) for r in FLASH_R]
    try:
        gun = gun.convert_alpha()
        flashes = [f.convert_alpha() for f in flashes]
    except Exception:
        pass
    _A['gun_r'] = gun
    _A['gun_l'] = pygame.transform.flip(gun, True, False)
    _A['flash'] = flashes
    _A['lines'] = _blink_lines()
    return _A


def _scanlines():
    """Additive scanline layer for Rewind: a 1 px line every 6 px, built once, 6 px taller for scrolling."""
    s = _A.get('scan')
    if s is None:
        s = pygame.Surface((W, H + 6))
        try:
            s = s.convert()
        except Exception:
            pass
        s.fill((0, 0, 0))
        for y in range(0, H + 6, 6):
            s.fill((0, 45, 80), (0, y, W, 1))
        _A['scan'] = s
    return s


def _draw_rewind_fx(surf, age):
    surf.fill((0, 25, 60), None, pygame.BLEND_RGB_ADD)
    off = int(age * 60.0) % 6
    surf.blit(_scanlines(), (0, -off), None, pygame.BLEND_RGB_ADD)


def _draw_blink_fx(surf, k):
    surf.fill((0, 30, 60), None, pygame.BLEND_RGB_ADD)
    fade = 1.0 - 0.6 * k
    col = (int(150 * fade), int(215 * fade), int(255 * fade))
    cx, cy = W // 2, H // 2
    f_in = 0.72 - 0.30 * k                    # the lines race in toward the centre
    line = pygame.draw.line
    for ex, ey, vx, vy, jit in _assets()['lines']:
        f = f_in + jit
        line(surf, col, (int(ex), int(ey)), (int(cx + vx * f), int(cy + vy * f)), 3)


# ============================ icons (drawn once, cached by the HUD) ==========
def _icon_bg(surf, r, accent):
    surf.fill((22, 26, 40), r)
    pygame.draw.rect(surf, accent, r, max(1, r.w // 40))


def _icon_portrait(surf, r, accent):
    s = min(r.w, r.h) / 96.0
    x, y, w, h = r.x, r.y, r.w, r.h
    cx = r.centerx
    surf.fill((22, 26, 40), r)
    poly = pygame.draw.polygon
    poly(surf, (74, 44, 20), [(x, y + h * 0.66), (x + w, y + h * 0.40), (x + w, y + h), (x, y + h)])
    # jacket and the chronal accelerator
    poly(surf, (126, 76, 42), [(cx - 40 * s, y + h), (cx - 30 * s, y + h - 24 * s), (cx + 30 * s, y + h - 24 * s),
                               (cx + 40 * s, y + h)])
    pygame.draw.circle(surf, (80, 200, 255), (cx, int(y + h - 9 * s)), max(2, int(10 * s)))
    pygame.draw.circle(surf, (230, 250, 255), (cx, int(y + h - 9 * s)), max(1, int(4 * s)))
    # neck, face
    surf.fill((222, 180, 150), (int(cx - 8 * s), int(y + 60 * s), max(2, int(16 * s)), max(2, int(14 * s))))
    fy = y + 46 * s
    pygame.draw.circle(surf, (238, 198, 168), (cx, int(fy)), max(4, int(23 * s)))
    # spiky hair
    hair = [(-27, -2), (-31, -20), (-21, -18), (-19, -35), (-7, -26), (1, -41), (9, -27), (23, -35), (21, -17),
            (32, -15), (26, 0), (18, -12), (-2, -16), (-18, -11)]
    poly(surf, (110, 62, 34), [(cx + dx * s, fy + dy * s) for dx, dy in hair])
    # goggles
    surf.fill((40, 36, 40), (int(cx - 26 * s), int(fy - 7 * s), max(4, int(52 * s)), max(2, int(12 * s))))
    for lx in (-21, 4):
        lr = pygame.Rect(int(cx + lx * s), int(fy - 6 * s), max(3, int(17 * s)), max(2, int(10 * s)))
        pygame.draw.rect(surf, (255, 150, 40), lr, 0, max(1, int(3 * s)))
        surf.fill((255, 225, 160), (lr.x + max(1, int(2 * s)), lr.y + max(1, int(2 * s)), max(1, int(5 * s)),
                                    max(1, int(2 * s))))
    # grin
    pygame.draw.line(surf, (150, 80, 70), (int(cx - 7 * s), int(fy + 13 * s)), (int(cx + 7 * s), int(fy + 12 * s)),
                     max(1, int(2 * s)))
    pygame.draw.rect(surf, accent, r, max(1, r.w // 40))


def _icon_blink(surf, r, accent):
    _icon_bg(surf, r, accent)
    w, h = r.w, r.h
    cy = r.centery
    th = max(2, int(w * 0.08))
    for i, c in enumerate(((50, 90, 140), (90, 150, 210), (150, 215, 255))):
        px = r.x + w * (0.22 + 0.2 * i)
        pygame.draw.lines(surf, c, False, [(px, cy - h * 0.22), (px + w * 0.17, cy), (px, cy + h * 0.22)], th)
    for i, dy in enumerate((-0.3, 0.0, 0.3)):
        y = int(cy + h * dy)
        pygame.draw.line(surf, (60, 110, 160), (int(r.x + w * 0.08), y), (int(r.x + w * (0.18 - 0.03 * i)), y),
                         max(1, th // 2))


def _icon_rewind(surf, r, accent):
    _icon_bg(surf, r, accent)
    cx, cy = r.centerx, r.centery
    rad = min(r.w, r.h) * 0.3
    th = max(2, int(r.w * 0.07))
    col = (120, 200, 255)
    pts = []
    for i in range(25):                             # arc from 50 deg round to 340 deg (counter-clockwise)
        a = math.radians(50 + 290 * i / 24.0)
        pts.append((cx + math.cos(a) * rad, cy - math.sin(a) * rad))
    pygame.draw.lines(surf, col, False, pts, th)
    ax, ay = pts[0]                                 # arrow head at the start, pointing back in time
    a0 = math.radians(50)
    tx, ty = -math.sin(a0), -math.cos(a0)           # clockwise tangent in screen space
    nx, ny = math.cos(a0), -math.sin(a0)
    L = rad * 0.55
    pygame.draw.polygon(surf, col, [(ax + tx * L, ay + ty * L), (ax + nx * L * 0.6, ay + ny * L * 0.6),
                                    (ax - nx * L * 0.6, ay - ny * L * 0.6)])
    hand = max(1, th - 1)
    pygame.draw.line(surf, (235, 241, 237), (cx, cy), (cx, int(cy - rad * 0.6)), hand)
    pygame.draw.line(surf, (235, 241, 237), (cx, cy), (int(cx - rad * 0.45), int(cy - rad * 0.2)), hand)


def _icon_bomb(surf, r, accent):
    _icon_bg(surf, r, accent)
    cx, cy = r.centerx, r.centery
    m = min(r.w, r.h)
    th = max(1, int(m * 0.04))
    pygame.draw.circle(surf, BOMB_RING, (cx, cy), int(m * 0.40), th)
    for i in range(8):
        a = i * math.tau / 8
        pygame.draw.line(surf, BOMB_RING, (int(cx + math.cos(a) * m * 0.28), int(cy + math.sin(a) * m * 0.28)),
                         (int(cx + math.cos(a) * m * 0.36), int(cy + math.sin(a) * m * 0.36)), max(1, th))
    pygame.draw.circle(surf, BOMB_BLUE, (cx, cy), int(m * 0.22))
    pygame.draw.circle(surf, WHITE, (cx, cy), max(2, int(m * 0.10)))


_ICONS = {'portrait': _icon_portrait, 'ab1': _icon_blink, 'secondary': _icon_blink, 'ab2': _icon_rewind,
          'ult': _icon_bomb}
