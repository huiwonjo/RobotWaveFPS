"""VECTOR (HERO_A owns this file): the Soldier-style all-rounder (spec 3.0, 3.1, 3.4).

Kit
  LMB    PULSE RIFLE    hitscan 19 (crit x2 = 38), 9 shots/s, mag 30, reload 1.5 s, no falloff.
                        Shots 1-3 of a burst are exact, then +0.3 deg per shot up to 1.5 deg;
                        the burst resets 0.3 s after the last shot.
  RMB/F  HELIX ROCKETS  HelixRocket projectile (speed 16, radius 0.2): 40 direct + splash 80 at the
                        centre falling to 40 at r 1.5 (LOS from the blast), knockback 0.4, cd 6 s.
                        An enemy barrier takes direct + splash (120) and stops the splash.
  SHIFT  SPRINT         latch: x1.5 speed while W is held; ends on W release, fire, RMB/F, E, Q, V
                        or Shift/Space again; starting to sprint cancels a reload.
  E      HEAL FIELD     HealField effect + 'heal_pylon' sprite at your feet: 40 HP/s for 5 s inside
                        r 2.5, healed HP gives ult 1:1, cd 15 s from the deploy.
  Q      LOCK-ON        6 s: the clip is refilled, no ammo is used, 19 per shot and never a crit;
                        each shot snaps to the visible (ScreenBox.visible), in-LOS enemy within
                        HALF_FOV that is nearest the crosshair, else it is a normal manual shot.

Layout: TUNING, gameplay (HelixRocket, helix_blast, HealField, Vector), then presentation
(viewmodel, crosshair, lock-on brackets, heal glow, icons, heal_pylon painter). Presentation code
reads gameplay state and never changes it; everything big is built once and cached.
"""
import math

import pygame

from . import config as C
from . import core
from . import render
from .combat import Barrier, Effect, Projectile, apply_damage, heal, knockback, splash
from .config import EYE_Z, FLAG_NOSHADE, HALF_FOV, TEAM_PLAYER
from .hero_base import Ability, Hero
from .world import is_wall

# =============================== tuning (spec 3.1; the integrator may retune) ===============
TUNING = {
    # PULSE RIFLE (primary). MAX_AMMO 30 / RELOAD_TIME 1.5 are class attributes (spec 3.4).
    'rifle_damage': 19.0,           # crit x CRIT_MULT = 38
    'rifle_interval': 0.111,        # 9 shots/s
    'rifle_exact_shots': 3,         # the first 3 shots of a burst have no spread
    'spread_step_deg': 0.3,         # then +0.3 deg per shot ...
    'spread_max_deg': 1.5,          # ... up to 1.5 deg (0.026 rad): yaw +-spread, pitch +-(spread x 768) px
    'burst_reset': 0.3,             # s after the last shot
    # HELIX ROCKETS (secondary)
    'helix_direct': 40.0, 'helix_center': 80.0, 'helix_edge': 40.0, 'helix_radius': 1.5,
    'helix_speed': 16.0, 'helix_proj_radius': 0.2, 'helix_cd': 6.0, 'helix_knockback': 0.4,
    'helix_ttl': 2.0,               # air-bursts after 32 cells (the map is 20 wide: never in practice)
    # SPRINT (ab1)
    'sprint_mult': 1.5,             # 4.2 -> 6.3 cells/s
    # HEAL FIELD (ab2)
    'heal_rate': 40.0, 'heal_time': 5.0, 'heal_radius': 2.5, 'heal_cd': 15.0,
    # LOCK-ON (ult)
    'lockon_time': 6.0, 'lockon_damage': 19.0,
}
T = TUNING

# presentation colours
BLUE = (80, 150, 255)
BLUE_CORE = (205, 230, 255)
LOCK_RED = (255, 60, 50)
LOCK_CORE = (255, 205, 195)
ROCKET = (255, 140, 40)
ROCKET_CORE = (255, 230, 160)
HEAL_COL = (190, 235, 70)
HEAL_CORE = (240, 255, 190)
TRACER = (170, 215, 255)


def spread_for(index):
    """Spread (rad) of the shot with 0-based `index` inside the current burst."""
    n = index - T['rifle_exact_shots'] + 1
    if n <= 0:
        return 0.0
    return math.radians(min(T['spread_max_deg'], T['spread_step_deg'] * n))


# =============================== HELIX ROCKETS ================================================
class HelixRocket(Projectile):
    """Player rocket. Drawn as 3 small orange orbs in a spinning triangle (spec 3.1)."""

    def __init__(self, x, y, angle, owner):
        super().__init__(x, y, angle, T['helix_speed'], team=TEAM_PLAYER, damage=T['helix_direct'],
                         radius=T['helix_proj_radius'], owner=owner, ability='secondary', ttl=T['helix_ttl'],
                         z=0.42, color=ROCKET, core=ROCKET_CORE, size=0.06, splash_r=T['helix_radius'],
                         splash_center=T['helix_center'], splash_edge=T['helix_edge'],
                         on_hit=_helix_on_hit, on_expire=_helix_on_expire, draw=_draw_helix)


def helix_blast(world, owner, x, y, exclude=()):
    """Splash (80 at the centre -> 40 at r 1.5, LOS from the blast, no self-damage, enemy barriers
    shield their own team), knockback 0.4 on the non-boss enemies hit, and the explosion visuals.
    Returns the enemies hit."""
    hit = splash(world, x, y, T['helix_radius'], T['helix_center'], T['helix_edge'], owner, TEAM_PLAYER,
                 'secondary', exclude=exclude)
    kb = T['helix_knockback']
    for t in hit:
        if t is not world.player and t.alive:
            knockback(world, t, x, y, kb)
    _blast_fx(world, x, y)
    return hit


def _blast_fx(world, x, y):
    """14 orange particles, a 0.25 s floor ring flash of r 1.5 and a 4 px shake for 0.15 s."""
    world.burst(x, y, 0.4, 14, (255, 150, 50), 3.0, 0.5, 3)
    world.add_effect(BlastRing(x, y))
    world.shake(4, 0.15)


def _helix_on_hit(world, pr, target, x, y):
    owner = pr.owner
    if isinstance(target, Barrier):
        # the barrier takes direct + splash; nothing behind it is splashed (handoff note)
        target.take(world, T['helix_direct'] + T['helix_center'], owner)
        world.bus.emit('explosion', x=x, y=y, radius=T['helix_radius'], team=TEAM_PLAYER)
        _blast_fx(world, x, y)
    elif target is None:                                        # wall
        helix_blast(world, owner, x, y)
    else:                                                       # direct hit: 40 + 80 = 120
        apply_damage(world, target, T['helix_direct'] + T['helix_center'], owner, ability='secondary',
                     from_xy=(x, y))
        helix_blast(world, owner, x, y, exclude=(target,))
        if target.alive:
            knockback(world, target, x, y, T['helix_knockback'])
    return True


def _helix_on_expire(world, pr):
    helix_blast(world, pr.owner, pr.x, pr.y)


def _draw_helix(scene, pr):
    trav = math.hypot(pr.x - pr.ox, pr.y - pr.oy)
    if trav < 0.6:                  # still inside the launcher flash: at d < 0.6 the orbs would fill the view
        return
    sp = math.hypot(pr.vx, pr.vy) or 1.0
    nx = -pr.vy / sp
    ny = pr.vx / sp
    spin = trav * 5.0
    for k in range(3):
        a = spin + k * 2.0944
        lat = math.cos(a) * 0.08
        scene.orb(pr.x + nx * lat, pr.y + ny * lat, pr.z + math.sin(a) * 0.08, 0.06, ROCKET, ROCKET_CORE)


class BlastRing(Effect):
    """The Helix floor ring flash: r 1.5 for 0.25 s, fading, with an inner shock ring."""
    LIFE = 0.25

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.left = self.LIFE
        self.alive = True

    def update(self, world, dt):
        self.left -= dt
        if self.left <= 0.0:
            self.alive = False

    def emit_visuals(self, scene):
        k = self.left / self.LIFE
        if k < 0.12:                # floor rings are opaque lines: a nearly black ring would read as a stain
            return
        scene.ring(self.x, self.y, T['helix_radius'], (int(255 * k), int(170 * k), int(60 * k)), 3, 28)
        scene.ring(self.x, self.y, T['helix_radius'] * (1.0 - 0.8 * k), (int(255 * k), int(230 * k),
                                                                         int(170 * k)), 2, 18)


# =============================== HEAL FIELD ===================================================
class HealField(Effect):
    """E: dropped at VECTOR's feet. 40 HP/s to the player while inside r 2.5, for 5 s.

    Healing goes through combat.heal(ability='ab2') and the owner gains ult 1:1 (spec 5.9). The HUD
    draws minimap_ring on the minimap. World sprite 'heal_pylon' (0.35 tall, 0.2 wide) plus a pulsing
    yellow-green floor ring; while the player is inside, a green additive edge glow (draw_screen)."""

    def __init__(self, owner, x, y):
        self.owner = owner
        self.x = x
        self.y = y
        self.left = T['heal_time']
        self.age = 0.0
        self.alive = True
        self.inside = False
        self.healed = 0.0
        self.minimap_ring = (x, y, T['heal_radius'], HEAL_COL)

    def kill(self):
        self.alive = False
        self.inside = False
        self.minimap_ring = None

    def update(self, world, dt):
        step = min(dt, self.left)
        self.age += dt
        self.left -= dt
        p = world.player
        r = T['heal_radius']
        self.inside = (p is self.owner and p.alive and (p.x - self.x) ** 2 + (p.y - self.y) ** 2 <= r * r)
        if self.inside and step > 0.0:
            amt = heal(world, p, T['heal_rate'] * step, source=p, ability='ab2')
            if amt > 0.0:
                p.add_ult(amt)
                self.healed += amt
        if self.left <= 0.0:
            self.kill()

    def emit_visuals(self, scene):
        a = self.age
        fade = min(1.0, max(0.0, self.left) / 0.5)
        k = (0.65 + 0.35 * math.sin(a * 9.42)) * (0.35 + 0.65 * fade)
        scene.ring(self.x, self.y, T['heal_radius'], (int(190 * k), int(235 * k), int(70 * k)), 3, 40)
        wave = (a * 0.8) % 1.0
        kw = (1.0 - wave) * 0.8 * fade
        if kw > 0.12 and wave > 0.08:
            scene.ring(self.x, self.y, T['heal_radius'] * wave, (int(150 * kw), int(220 * kw), int(90 * kw)), 2, 24)
        scene.sprite(self.x, self.y, 'heal_pylon', 'pulse' if int(a * 4.0) % 2 == 0 else 'idle', 0.35, 0.2,
                     flags=FLAG_NOSHADE)

    def draw_screen(self, surf, world):
        if self.inside and world.player is self.owner:
            _draw_heal_glow(surf, self.age)


# =============================== the hero =====================================================
@core.register_hero
class Vector(Hero):
    KEY = 'vector'
    NAME = 'VECTOR'
    ROLE = 'DAMAGE'
    DIFFICULTY = 1
    COLOR = BLUE
    BLURB = 'Versatile rifleman. Rockets, sprint, self-heal.'
    KIT = (('LMB', 'PULSE RIFLE', 'Full-auto hitscan rifle. Headshots crit.'),
           ('RMB/F', 'HELIX ROCKETS', 'Three rockets that burst on impact.'),
           ('SHIFT', 'SPRINT', 'Press to run faster while moving forward.'),
           ('E', 'HEAL FIELD', 'Drop a field that heals you 40 HP/s.'),
           ('Q', 'LOCK-ON', 'For 6 s every shot hits the target nearest your aim.'))
    LABELS = {'primary': 'PULSE RIFLE', 'secondary': 'HELIX', 'ult': 'LOCK-ON', 'melee': 'MELEE'}
    HEALTH = 200
    ARMOR = 0
    SHIELDS = 0
    SPEED = 4.2
    ULT_COST = 1650                 # spec 1500; integration +10% (spec 9.6: charge was ~2x faster than 60 s)
    ULT_NAME = 'LOCK-ON'
    ULT_CALLOUT = 'LOCKED ON!'
    ULT_DURATION = T['lockon_time']
    MAX_AMMO = 30
    RELOAD_TIME = 1.5
    HUD_ORDER = ('ab1', 'ab2', 'secondary')

    def __init__(self, world):
        super().__init__(world)
        self.abilities = {
            'secondary': Ability(self, 'secondary', 'HELIX ROCKETS', 'RMB', T['helix_cd']),
            'ab1': Ability(self, 'ab1', 'SPRINT', 'SHIFT', 0.0),
            'ab2': Ability(self, 'ab2', 'HEAL FIELD', 'E', T['heal_cd']),
        }
        # rifle
        self._next_shot = -9.0
        self._last_shot = -9.0
        self._burst = 0             # shots fired in the current burst
        self._spread = 0.0          # spread (rad) of the last shot
        self._shots = 0             # shots fired this life (flash size cycle)
        self._tracer = None         # world point (x, y, z) the last shot ended at
        # sprint latch
        self.sprinting = False      # latched AND moving forward: x1.5
        self._latched = False
        self._fwd_seen = False
        # helix / heal field
        self._last_rocket = -9.0
        self._last_heal = -9.0
        self.field = None
        # lock-on
        self._lt_frame = -1
        self._lt = []
        self._los = {}
        # viewmodel motion (presentation only)
        self._bob_phase = 0.0
        self._bob_amp = 0.0
        self._low = 0.0

    # --- input ---------------------------------------------------------------------------------
    def on_input(self, inp, world):
        ab = self.abilities
        fire = inp.down('fire')
        cancel = fire or inp.hit('alt') or inp.hit('ab2') or inp.hit('ult') or inp.hit('melee')
        if inp.hit('ab1'):
            if self._latched:
                self._stop_sprint()
            elif not cancel and ab['ab1'].use(world):
                self._latched = True
                self._fwd_seen = False
        if self._latched:
            if cancel:
                self._stop_sprint()
            elif inp.down('fwd'):
                if not self.sprinting:
                    self.sprinting = True
                    self.cancel_reload()
                self._fwd_seen = True
            elif self._fwd_seen:
                self._stop_sprint()             # W released
            else:
                self.sprinting = False          # latched before W: sprint starts when W goes down
        if inp.hit('alt') and ab['secondary'].use(world):
            self._fire_rocket(world)
        if inp.hit('ab2') and ab['ab2'].use(world):
            self._deploy_field(world)
        if fire:
            self._fire(world)

    def think(self, world, dt):
        if self._latched and not self.can_act(world):
            self._stop_sprint()
        if self.sprinting:
            self.speed_mult = T['sprint_mult']
        self.abilities['ab1'].active_left = 1.0 if self._latched else 0.0
        # viewmodel motion
        moving = (self.move_fwd or self.move_right) and self.status.can_move(world.now)
        self._bob_amp += ((1.0 if moving else 0.0) - self._bob_amp) * min(1.0, dt * 8.0)
        if moving:
            self._bob_phase = (self._bob_phase + dt * 11.0 * (2.0 if self.sprinting else 1.0)) % (2.0 * math.pi)
        goal = 60.0 if self.sprinting else 0.0
        step = 480.0 * dt
        self._low = min(goal, self._low + step) if self._low < goal else max(goal, self._low - step)

    def _stop_sprint(self):
        self._latched = False
        self.sprinting = False
        self._fwd_seen = False
        self.abilities['ab1'].active_left = 0.0

    # --- PULSE RIFLE / LOCK-ON -------------------------------------------------------------------
    def _fire(self, world):
        if self.reloading:
            return
        now = world.now
        iv = T['rifle_interval']
        if now < self._next_shot - 1e-9:
            return
        if now - self._next_shot > world.dt + 1e-9:     # the trigger was idle: restart the cadence
            self._next_shot = now
        n = 0
        while now >= self._next_shot - 1e-9 and n < 2:  # 2 = safety for frames longer than 0.111 s
            if not self._shoot_once(world):
                break
            self._next_shot += iv
            n += 1

    def _shoot_once(self, world):
        ult = self.ult_active_left > 0.0
        if not ult and not self.use_ammo():
            return False
        now = world.now
        if now - self._last_shot > T['burst_reset']:
            self._burst = 0
        target = None
        if ult:
            tg = self._lock_targets(world)
            if tg:
                target = tg[0][0]
        if target is not None:
            ang, pitch = self._aim_at(target)
            spread = 0.0
            hit = self.fire_hitscan(world, T['lockon_damage'], angle=ang, pitch=pitch, allow_crit=False,
                                    ability='ult')
        else:
            spread = spread_for(self._burst)
            hit = self.fire_hitscan(world, T['lockon_damage'] if ult else T['rifle_damage'], spread=spread,
                                    allow_crit=not ult, ability='ult' if ult else 'primary')
        self._burst += 1
        self._shots += 1
        self._last_shot = now
        self._spread = spread
        self._tracer = (hit.x, hit.y, hit.z)
        return True

    def _aim_at(self, e):
        """Yaw and pitch (px) that put the crosshair on the middle of e's body."""
        dx = e.x - self.x
        dy = e.y - self.y
        d = max(0.2, math.hypot(dx, dy))
        zt = e.z0 + e.height * e.height_mult * 0.5
        return math.atan2(dy, dx), (zt - EYE_Z) * C.H / d

    def _lock_targets(self, world):
        """[(enemy, ScreenBox)] valid for Lock-On, nearest the crosshair first. Valid: alive, drawn with
        ScreenBox.visible on the last rendered frame, within HALF_FOV of the view and in LOS (walls).
        Cached per world frame; LOS per enemy is cached for 0.1 s."""
        fr = world.frame
        if self._lt_frame == fr:
            return self._lt
        self._lt_frame = fr
        proj = world.projection
        cands = []
        cx, cy = C.W * 0.5, C.H * 0.5
        for e in world.enemies:
            if not e.alive:
                continue
            box = proj.get(e.id)
            if box is None or not box.visible:
                continue
            if abs(core.wrap_angle(math.atan2(e.y - self.y, e.x - self.x) - self.angle)) > HALF_FOV:
                continue
            bx = (box.x0 + box.x1) * 0.5 - cx
            by = (box.y0 + box.y1) * 0.5 - cy
            cands.append((bx * bx + by * by, e.id, e, box))
        cands.sort(key=lambda t: (t[0], t[1]))
        self._lt = [(e, box) for _, _, e, box in cands if self._los_to(world, e)]
        return self._lt

    def _los_to(self, world, e):
        now = world.now
        c = self._los.get(e.id)
        if c is not None and c[0] > now:
            return c[1]
        ok = world.los(self.x, self.y, e.x, e.y)
        if len(self._los) > 48:
            alive = {x.id for x in world.enemies if x.alive}
            self._los = {k: v for k, v in self._los.items() if k in alive}
        self._los[e.id] = (now + 0.1, ok)
        return ok

    def spread_now(self, now):
        """Current spread (rad) for the crosshair: the last shot's, until the burst resets."""
        return self._spread if now - self._last_shot <= T['burst_reset'] else 0.0

    # --- HELIX / HEAL FIELD / ult ----------------------------------------------------------------
    def _fire_rocket(self, world):
        a = self.angle
        x = self.x + math.cos(a) * 0.1
        y = self.y + math.sin(a) * 0.1
        if is_wall(x, y):
            x, y = self.x, self.y
        world.add_projectile(HelixRocket(x, y, a, self))
        self._last_rocket = world.now
        world.bus.emit('sfx', name='rocket', vol=0.9)

    def _deploy_field(self, world):
        if self.field is not None and self.field.alive:
            self.field.kill()               # one field at a time (only matters with no_cooldowns)
        f = HealField(self, self.x, self.y)
        self.field = f if world.add_effect(f) else None
        self._last_heal = world.now
        world.bus.emit('sfx', name='heal', vol=0.8)

    def on_ult(self, world):
        self._stop_sprint()
        self.cancel_reload()
        self.ammo = self.MAX_AMMO
        self._burst = 0
        self._lt_frame = -1

    def on_removed(self, world):
        self._stop_sprint()
        if self.field is not None:
            self.field.kill()
            self.field = None

    def restore(self, world):
        super().restore(world)
        self._stop_sprint()
        self._burst = 0

    # --- presentation ----------------------------------------------------------------------------
    def draw_viewmodel(self, surf, world):
        _draw_viewmodel(self, surf, world)

    def draw_overlay(self, surf, world):
        if self.ult_active_left > 0.0:
            for i, (e, box) in enumerate(self._lock_targets(world)):
                _brackets(surf, box, 3 if i == 0 else 2)

    def draw_crosshair(self, surf, world):
        cx, cy = C.W // 2, C.H // 2
        col = LOCK_RED if self.ult_active_left > 0.0 else (255, 255, 255)
        r = int(10 + self.spread_now(world.now) * 400 + 0.5)
        pygame.draw.circle(surf, col, (cx, cy), r, 1)
        surf.fill(col, (cx - 1, cy - 1, 2, 2))

    @classmethod
    def draw_icon(cls, slot, surf, rect):
        rect = pygame.Rect(rect)
        fn = _ICONS.get(slot)
        if fn is None:
            super().draw_icon(slot, surf, rect)
        else:
            fn(surf, rect)


# =============================== presentation: viewmodel ======================================
# The rifle is pre-rendered once (normal and Lock-On variants) into a surface that covers the
# bottom-right of the screen, then blitted with an offset (bob, kick, sprint, reload dip). It stays
# below y 480 and out of the central 200x200 box; only the flash and the tracer reach the centre.
VM_POS = (560, 470)                 # screen top-left of the cached rifle surface at rest
VM_SIZE = (464, 298)
_GM = (84.0, 84.0)                  # muzzle, rifle-surface coordinates
_GS = (430.0, 214.0)                # stock end
_vm = {}


def _gp(u, v):
    """Point on the rifle: u 0 (muzzle) .. 1 (stock) along the barrel, v px across (+ = down),
    shrunk toward the muzzle for perspective."""
    dx = _GS[0] - _GM[0]
    dy = _GS[1] - _GM[1]
    ln = math.hypot(dx, dy)
    k = 0.55 + 0.45 * u
    return (_GM[0] + dx * u - dy / ln * v * k, _GM[1] + dy * u + dx / ln * v * k)


def _quad(u0, u1, v0, v1):
    return [_gp(u0, v0), _gp(u1, v0), _gp(u1, v1), _gp(u0, v1)]


def _build_rifle(strip, strip_core):
    s = pygame.Surface(VM_SIZE, pygame.SRCALPHA)
    edge = (12, 14, 20)
    poly = pygame.draw.polygon
    line = pygame.draw.line

    def part(pts, col, outline=True):
        poly(s, col, pts)
        if outline:
            poly(s, edge, pts, 2)
    w, h = VM_SIZE
    # sleeve (VECTOR's jacket, white stripe) and the glove on the grip
    part([_gp(0.68, 60), _gp(0.88, 50), (w + 4, h - 70), (w + 4, h + 4), (w - 170, h + 4)], (34, 50, 92))
    line(s, (220, 226, 240), _gp(0.80, 84), (w - 46, h + 4), 6)
    # stock, grip, magazine
    part([_gp(0.82, -40), _gp(1.00, -44), _gp(1.05, 58), _gp(0.88, 52)], (34, 38, 48))
    part(_quad(0.86, 0.99, -26, 30), (44, 48, 60))
    part([_gp(0.71, 30), _gp(0.79, 30), _gp(0.83, 118), _gp(0.74, 122)], (26, 29, 36))
    part([_gp(0.54, 30), _gp(0.64, 30), _gp(0.68, 132), _gp(0.57, 136)], (46, 52, 64))
    line(s, strip, _gp(0.585, 50), _gp(0.62, 122), 3)
    part([_gp(0.66, 26), _gp(0.81, 24), _gp(0.86, 86), _gp(0.70, 94)], (40, 42, 50))
    # helix launcher under the barrel, with its 3 rocket mouths
    part(_quad(0.07, 0.46, 14, 56), (92, 74, 58))
    line(s, (128, 104, 82), _gp(0.09, 18), _gp(0.44, 18), 2)
    part(_quad(0.05, 0.10, 10, 60), (58, 46, 38))
    c = _gp(0.075, 35)
    for ox, oy in ((0.0, -8.0), (-7.0, 5.0), (7.0, 5.0)):
        pygame.draw.circle(s, (20, 14, 10), (int(c[0] + ox), int(c[1] + oy)), 5)
        pygame.draw.circle(s, ROCKET, (int(c[0] + ox), int(c[1] + oy)), 3)
    # barrel and muzzle brake
    part(_quad(0.0, 0.22, -12, 12), (62, 66, 78))
    part(_quad(0.0, 0.045, -17, 17), (30, 32, 40))
    line(s, (100, 106, 124), _gp(0.05, -10), _gp(0.21, -10), 2)
    # handguard with vents, receiver with a side panel
    part(_quad(0.17, 0.49, -34, 16), (48, 54, 68))
    for u in (0.22, 0.28, 0.34, 0.40):
        poly(s, edge, _quad(u, u + 0.028, -28, -16))
    part(_quad(0.47, 0.85, -44, 34), (58, 64, 80))
    part(_quad(0.53, 0.80, -30, 22), (68, 76, 94))
    for u in (0.58, 0.66, 0.74):
        pygame.draw.circle(s, edge, [int(v) for v in _gp(u, 12)], 3)
    # sight on the top rail
    part(_quad(0.50, 0.70, -48, -42), (30, 34, 42))
    part(_quad(0.53, 0.68, -68, -46), (36, 40, 50))
    poly(s, strip, _quad(0.535, 0.57, -64, -50))
    # pulse energy strip
    poly(s, strip, _quad(0.18, 0.85, -12, 1))
    poly(s, strip_core, _quad(0.18, 0.85, -7.5, -3.5))
    # top highlights
    light = (104, 112, 132)
    line(s, light, _gp(0.175, -33), _gp(0.485, -33), 2)
    line(s, light, _gp(0.475, -43), _gp(0.845, -43), 2)
    return s


def _build_flash(size, outer, core_col):
    """Additive muzzle flash (RGB on black, blitted with BLEND_RGB_ADD)."""
    s = pygame.Surface((size, size))
    s.fill((0, 0, 0))
    c = size * 0.5
    pts = []
    for k in range(8):
        a = k * math.pi / 4.0 + 0.3
        r = c - 1 if k % 2 == 0 else c * 0.32
        pts.append((c + math.cos(a) * r, c + math.sin(a) * r))
    pygame.draw.polygon(s, tuple(int(x * 0.55) for x in outer), pts)
    for i in range(5):
        t = i / 4.0
        col = tuple(int(o * (0.6 + 0.4 * t) * (1 - t) + cc * t) for o, cc in zip(outer, core_col))
        pygame.draw.circle(s, col, (int(c), int(c)), max(1, int(c * 0.5 * (1.0 - 0.8 * t))))
    return s


def _fast(s, alpha=False):
    """convert() / convert_alpha() for faster blits once a display mode exists (else unchanged)."""
    try:
        return s.convert_alpha() if alpha else s.convert()
    except Exception:
        return s


def _vm_cache():
    if not _vm:
        base = _build_rifle(BLUE, BLUE_CORE)
        crop = base.get_bounding_rect()         # blit only the drawn part (both variants share the shape)
        _vm['off'] = crop.topleft
        _vm['base'] = _fast(base.subsurface(crop).copy(), True)
        _vm['ult'] = _fast(_build_rifle(LOCK_RED, LOCK_CORE).subsurface(crop).copy(), True)
        _vm['flash'] = [_fast(_build_flash(n, (150, 200, 255), (255, 255, 255))) for n in (40, 52, 64)]
        _vm['rocket_flash'] = _fast(_build_flash(64, (255, 140, 40), (255, 240, 200)))
        m = _gp(0.0, 0.0)
        _vm['muzzle'] = (VM_POS[0] + m[0], VM_POS[1] + m[1])
        lm = _gp(0.075, 35)
        _vm['launcher'] = (VM_POS[0] + lm[0], VM_POS[1] + lm[1])
    return _vm


def _draw_viewmodel(hero, surf, world):
    vm = _vm_cache()
    now = world.now
    ox = hero._bob_amp * math.sin(hero._bob_phase) * 7.0
    oy = hero._low + hero._bob_amp * abs(math.cos(hero._bob_phase)) * 6.0
    ks = now - hero._last_shot
    kick = 10.0 * (1.0 - ks / 0.08) if 0.0 <= ks < 0.08 else 0.0
    kr = now - hero._last_rocket
    if 0.0 <= kr < 0.15:
        kick = max(kick, 16.0 * (1.0 - kr / 0.15))
    ox += kick * 0.6
    oy += kick
    if hero.reloading and hero.RELOAD_TIME > 0:
        f = 1.0 - hero.reload_left / hero.RELOAD_TIME
        oy += 70.0 * math.sin(math.pi * core.clamp(f, 0.0, 1.0))
        ox += 18.0 * math.sin(math.pi * core.clamp(f, 0.0, 1.0))
    kh = now - hero._last_heal
    if 0.0 <= kh < 0.3:
        oy += 30.0 * math.sin(math.pi * kh / 0.3)
    ix = int(ox)
    iy = int(oy)
    off = vm['off']
    surf.blit(vm['ult' if hero.ult_active_left > 0.0 else 'base'], (VM_POS[0] + off[0] + ix, VM_POS[1] + off[1] + iy))
    mx = vm['muzzle'][0] + ix
    my = vm['muzzle'][1] + iy
    if 0.0 <= ks < 0.04 and hero._tracer is not None:
        end = render.project_point(world.cam, *hero._tracer)
        ex, ey = (C.W // 2, C.H // 2) if end is None else (core.clamp(end[0], 0, C.W - 1),
                                                           core.clamp(end[1], 0, C.H - 1))
        pygame.draw.line(surf, TRACER, (mx, my), (ex, ey), 2)
    if 0.0 <= ks < 0.05:
        fl = vm['flash'][(hero._shots * 7) % 3]
        surf.blit(fl, (int(mx - fl.get_width() * 0.5), int(my - fl.get_height() * 0.5)),
                  special_flags=pygame.BLEND_RGB_ADD)
    if 0.0 <= kr < 0.08:
        fl = vm['rocket_flash']
        lx = vm['launcher'][0] + ix
        ly = vm['launcher'][1] + iy
        surf.blit(fl, (int(lx - 32), int(ly - 32)), special_flags=pygame.BLEND_RGB_ADD)


# =============================== presentation: overlays =======================================
def _brackets(surf, box, width):
    """Red corner brackets (4 L-shapes) around a Lock-On target's ScreenBox."""
    x0 = max(2, box.x0)
    y0 = max(2, box.y0)
    x1 = min(C.W - 3, box.x1)
    y1 = min(C.H - 3, box.y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    ln = int(max(6, min(18, (x1 - x0) * 0.3, (y1 - y0) * 0.3)))
    line = pygame.draw.line
    for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        line(surf, LOCK_RED, (cx, cy), (cx + sx * ln, cy), width)
        line(surf, LOCK_RED, (cx, cy), (cx, cy + sy * ln), width)


_glow = []
GLOW_T = 44                         # strip thickness (px)


def _glow_levels():
    """3 intensity levels x 4 additive edge strips (top, bottom, left, right), built once."""
    if not _glow:
        for k in (0.45, 0.7, 1.0):
            top = pygame.Surface((C.W, GLOW_T))
            bot = pygame.Surface((C.W, GLOW_T))
            left = pygame.Surface((GLOW_T, C.H))
            right = pygame.Surface((GLOW_T, C.H))
            for i in range(GLOW_T):
                f = (1.0 - i / GLOW_T) ** 1.8 * k
                col = (int(40 * f), int(170 * f), int(70 * f))
                top.fill(col, (0, i, C.W, 1))
                bot.fill(col, (0, GLOW_T - 1 - i, C.W, 1))
                left.fill(col, (i, 0, 1, C.H))
                right.fill(col, (GLOW_T - 1 - i, 0, 1, C.H))
            _glow.append(tuple(_fast(x) for x in (top, bot, left, right)))
    return _glow


def _draw_heal_glow(surf, age):
    lv = _glow_levels()[min(2, int((0.5 + 0.5 * math.sin(age * 9.42)) * 3.0))]
    add = pygame.BLEND_RGB_ADD
    surf.blit(lv[0], (0, 0), special_flags=add)
    surf.blit(lv[1], (0, C.H - GLOW_T), special_flags=add)
    surf.blit(lv[2], (0, 0), special_flags=add)
    surf.blit(lv[3], (C.W - GLOW_T, 0), special_flags=add)


# =============================== presentation: icons ==========================================
def _P(r, fx, fy):
    return (r.x + fx * r.w, r.y + fy * r.h)


def _S(r, f):
    return max(1, int(round(f * r.w)))


def _icon_portrait(surf, r):
    poly = pygame.draw.polygon
    rad = max(2, r.w // 10)
    pygame.draw.rect(surf, (18, 26, 44), r, border_radius=rad)
    pygame.draw.rect(surf, (26, 40, 72), (r.x, int(r.y + r.h * 0.62), r.w, int(r.h * 0.38)),
                     border_bottom_left_radius=rad, border_bottom_right_radius=rad)
    # jacket and shoulders, with the white shoulder stripes
    poly(surf, (38, 60, 118), [_P(r, .04, 1), _P(r, .12, .80), _P(r, .34, .72), _P(r, .5, .80),
                               _P(r, .66, .72), _P(r, .88, .80), _P(r, .96, 1)])
    pygame.draw.line(surf, (225, 230, 240), _P(r, .16, .80), _P(r, .10, .98), _S(r, .045))
    pygame.draw.line(surf, (225, 230, 240), _P(r, .84, .80), _P(r, .90, .98), _S(r, .045))
    poly(surf, (60, 66, 80), [_P(r, .40, .70), _P(r, .60, .70), _P(r, .56, .80), _P(r, .44, .80)])
    # helmet
    head = [_P(r, .30, .30), _P(r, .36, .15), _P(r, .50, .09), _P(r, .64, .15), _P(r, .70, .30),
            _P(r, .70, .54), _P(r, .62, .70), _P(r, .50, .75), _P(r, .38, .70), _P(r, .30, .54)]
    poly(surf, (86, 92, 108), head)
    poly(surf, (118, 126, 144), [_P(r, .36, .15), _P(r, .50, .09), _P(r, .64, .15), _P(r, .50, .20)])
    # visor
    poly(surf, BLUE, [_P(r, .30, .33), _P(r, .70, .33), _P(r, .67, .45), _P(r, .33, .45)])
    pygame.draw.line(surf, BLUE_CORE, _P(r, .34, .38), _P(r, .66, .38), _S(r, .03))
    # mask with vents
    poly(surf, (52, 56, 68), [_P(r, .36, .52), _P(r, .64, .52), _P(r, .60, .67), _P(r, .50, .71),
                              _P(r, .40, .67)])
    for fy in (.57, .62):
        pygame.draw.line(surf, (24, 26, 32), _P(r, .42, fy), _P(r, .58, fy), _S(r, .025))
    poly(surf, (12, 14, 20), head, _S(r, .025))
    pygame.draw.rect(surf, BLUE, r, _S(r, .035), border_radius=rad)


def _icon_helix(surf, r):
    c = r.center
    rr = r.w * 0.22
    for k in range(3):
        a0 = k * 2.0944 - 1.5708
        box = pygame.Rect(0, 0, int(r.w * 0.76), int(r.h * 0.76))
        box.center = c
        pygame.draw.arc(surf, (150, 80, 30), box, -a0 - 0.2, -a0 + 1.4, _S(r, .05))
    for k in range(3):
        a = k * 2.0944 - 1.5708
        p = (int(c[0] + math.cos(a) * rr), int(c[1] + math.sin(a) * rr))
        pygame.draw.circle(surf, ROCKET, p, _S(r, .12))
        pygame.draw.circle(surf, ROCKET_CORE, p, _S(r, .055))


def _icon_sprint(surf, r):
    for x0, col in ((.14, (50, 80, 140)), (.34, (80, 130, 220)), (.54, (200, 225, 255))):
        pygame.draw.polygon(surf, col, [_P(r, x0, .22), _P(r, x0 + .14, .22), _P(r, x0 + .30, .50),
                                        _P(r, x0 + .14, .78), _P(r, x0, .78), _P(r, x0 + .16, .50)])


def _icon_heal(surf, r):
    ring = pygame.Rect(0, 0, int(r.w * 0.80), int(r.h * 0.26))
    ring.center = (int(r.centerx), int(r.y + r.h * 0.78))
    pygame.draw.ellipse(surf, HEAL_COL, ring, _S(r, .045))
    col_r = pygame.Rect(0, 0, _S(r, .14), int(r.h * 0.34))
    col_r.midbottom = (int(r.centerx), int(r.y + r.h * 0.80))
    pygame.draw.rect(surf, (170, 178, 194), col_r)
    pygame.draw.circle(surf, HEAL_CORE, (int(r.centerx), int(r.y + r.h * 0.44)), _S(r, .08))
    cx, cy = int(r.centerx), int(r.y + r.h * 0.22)
    a = _S(r, .16)
    t = _S(r, .07)
    surf.fill(HEAL_COL, (cx - t // 2, cy - a, t, 2 * a))
    surf.fill(HEAL_COL, (cx - a, cy - t // 2, 2 * a, t))


def _icon_lockon(surf, r):
    c = (int(r.centerx), int(r.centery))
    wdt = _S(r, .05)
    pygame.draw.circle(surf, LOCK_RED, c, int(r.w * 0.22), wdt)
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        pygame.draw.line(surf, LOCK_RED, (c[0] + dx * r.w * 0.14, c[1] + dy * r.h * 0.14),
                         (c[0] + dx * r.w * 0.30, c[1] + dy * r.h * 0.30), wdt)
    pygame.draw.circle(surf, (255, 255, 255), c, _S(r, .045))
    x0, y0, x1, y1 = r.x + r.w * .12, r.y + r.h * .12, r.x + r.w * .88, r.y + r.h * .88
    ln = r.w * 0.18
    lw = _S(r, .06)
    for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        pygame.draw.line(surf, LOCK_CORE, (cx, cy), (cx + sx * ln, cy), lw)
        pygame.draw.line(surf, LOCK_CORE, (cx, cy), (cx, cy + sy * ln), lw)


_ICONS = {'portrait': _icon_portrait, 'secondary': _icon_helix, 'ab1': _icon_sprint, 'ab2': _icon_heal,
          'ult': _icon_lockon}


# =============================== painter: heal_pylon ==========================================
def _paint_pylon(surf, state, elite):
    """States 'idle' and 'pulse' (the emitter light alternates at 4 Hz); unknown states draw as idle."""
    w, h = surf.get_size()
    hot = state == 'pulse'
    cx = w // 2
    pygame.draw.ellipse(surf, (46, 52, 62), (1, h - 11, w - 2, 10))
    pygame.draw.rect(surf, (74, 82, 98), (5, h - 16, w - 10, 9), border_radius=2)
    surf.fill((150, 160, 176), (cx - 5, 20, 10, h - 36))
    surf.fill((104, 112, 128), (cx + 2, 20, 3, h - 36))
    surf.fill(HEAL_COL, (cx - 1, 25, 3, 13))
    surf.fill(HEAL_COL, (cx - 5, 30, 11, 3))
    if hot:
        pygame.draw.circle(surf, (190, 235, 70, 110), (cx, 12), 12)
    pygame.draw.circle(surf, HEAL_CORE if hot else HEAL_COL, (cx, 12), 8)
    pygame.draw.circle(surf, (255, 255, 255), (cx, 12), 5 if hot else 3)


render.register_painter('heal_pylon', _paint_pylon, 32, 56)
