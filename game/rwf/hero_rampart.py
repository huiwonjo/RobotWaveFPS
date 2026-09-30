"""RAMPART (HERO_C): Reinhardt-style tank (spec 3.0, 3.3, 3.4, 5.6).

Kit
- LMB  ROCKET HAMMER: instant cone swing (80 to every enemy within reach 2.5 and +-45 deg, LOS per target,
       knockback 0.6), also 80 to enemy barriers whose midpoint is in the arc. One swing per 0.9 s.
- RMB/F BARRIER (hold): a 600 HP player-team Barrier 1.0 in front (half-width 1.2) while held; x0.7 speed;
       150 HP/s regen after 2.0 s lowered; broken -> forced down, 5.0 s lockout, then regen from 0.
- SHIFT CHARGE: 9 cells/s for up to 1.5 s, steering 90 deg/s, WASD ignored, knockback-immune. Pins the first
       pinnable enemy ahead and carries it 0.7 in front; wall contact slams it (225). Others within 0.8 take
       50 + 1.5 sideways knockback once. The boss takes 100 and stops the charge. Shift again after 0.2 s
       cancels. Never ends inside a wall (the path is stepped 0.1 at a time and stops before any overlap).
- E    FLAME STRIKE: 90, piercing (each enemy once), passes enemy barriers, stops at walls. 2 charges.
- Q    QUAKE SLAM: a wave front travelling 20 cells/s along a +-30 deg / 8 cell cone; 120 + 2.5 s stun
       (x STUN_MULT) to every enemy it reaches with LOS from the origin and no enemy barrier in between.
       Rampart is rooted for 0.6 s.

Small OW-faithful rules the spec leaves open (see the integrator notes in the HERO_C report):
- Casting FLAME STRIKE or QUAKE drops a raised barrier for the cast (0.35 s flick / 0.6 s slam); it comes
  back by itself while RMB/F is still held. CHARGE drops it for the whole charge.
- E is ignored while charging; Q during a charge ends the charge and slams.
- A pinned enemy carried into the boss is slammed too (225) when the boss stops the charge.

Presentation (all drawn in code, nothing large allocated per frame): the hammer viewmodel
(_draw_hammer), the hex barrier overlay (two cached 880x480 RGB surfaces built once), charge speed lines,
the crosshair and the five icons (_ICONS). Visual numbers live in TUNING / the colour constants below.
"""
import math

import pygame

from . import config as C
from . import core
from .combat import Barrier, Effect, Projectile, apply_damage, cone_targets, knockback
from .config import TEAM_PLAYER
from .hero_base import Ability, Hero
from .world import is_wall, los

TUNING = {
    # ROCKET HAMMER (primary)
    'hammer_damage': 80.0, 'hammer_reach': 2.5, 'hammer_arc_deg': 45.0, 'hammer_interval': 0.9,
    'hammer_knockback': 0.6, 'hammer_sparks': 6, 'hammer_shake': (3.0, 0.12), 'hammer_sweep': 0.3,
    # BARRIER (secondary, hold)
    'barrier_hp': 600.0, 'barrier_regen': 150.0, 'barrier_regen_delay': 2.0, 'barrier_lockout': 5.0,
    'barrier_dist': 1.0, 'barrier_half_width': 1.2, 'barrier_speed_mult': 0.7, 'barrier_min_hp': 1.0,
    'barrier_low_frac': 0.30, 'barrier_flash': 0.08,
    # CHARGE (ab1)
    'charge_cd': 7.0, 'charge_speed': 9.0, 'charge_time': 1.5, 'charge_turn_deg': 90.0,
    'charge_cancel_after': 0.2, 'charge_step': 0.1, 'charge_pin_reach': 0.45, 'charge_carry': 0.7,
    'charge_pin_damage': 225.0, 'charge_brush_damage': 50.0, 'charge_brush_knockback': 1.5,
    'charge_brush_radius': 0.8, 'charge_boss_damage': 100.0, 'charge_shake': 2.0,
    'charge_impact_shake': (10.0, 0.3), 'charge_impact_particles': 12,
    # FLAME STRIKE (ab2)
    'flame_damage': 90.0, 'flame_speed': 14.0, 'flame_radius': 0.35, 'flame_range': 12.0, 'flame_cd': 6.0,
    'flame_charges': 2, 'flame_orb': 0.18, 'flame_embers_per_frame': 4, 'flame_flick': 0.35,
    # QUAKE SLAM (ult)
    'quake_damage': 120.0, 'quake_len': 8.0, 'quake_half_deg': 30.0, 'quake_speed': 20.0, 'quake_stun': 2.5,
    'quake_root': 0.6, 'quake_shake': (12.0, 0.4), 'quake_rocks': 24, 'quake_rock_ttl': 0.6,
    # presentation
    'overlay_size': (880, 480), 'overlay_tint': (0, 15, 35), 'overlay_tint_low': (35, 16, 0),
    'hp_bar': (200, 6, 300),
}
T = TUNING

# --- palette (presentation only) ---------------------------------------------------------------
GOLD = (230, 180, 60)
GOLD_D = (150, 110, 36)
STEEL = (150, 156, 168)
STEEL_L = (196, 202, 212)
STEEL_D = (92, 98, 112)
DARK = (44, 48, 58)
HANDLE = (84, 66, 48)
GRIP = (40, 34, 30)
SHIELD_BLUE = (120, 200, 255)
SHIELD_ORANGE = (255, 150, 40)
FLAME = (255, 120, 30)
FLAME_CORE = (255, 230, 120)
ROCK = (128, 92, 58)


def _blocked(x, y, r):
    """Square footprint test, the same one world.move_slide uses: True if any corner is in a wall."""
    return (is_wall(x - r, y - r) or is_wall(x + r, y - r)
            or is_wall(x - r, y + r) or is_wall(x + r, y + r))


class _HoldAbility(Ability):
    """CHARGE slot: its recharge is frozen while `holding` (the 7 s cooldown starts when the charge ends)
    and its HUD tile shows 'active' instead of a cooldown meanwhile."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.holding = False

    def update(self, world, dt):
        if self.holding:
            if self.active_left > 0.0:
                self.active_left = max(0.0, self.active_left - dt)
            return
        super().update(world, dt)

    def reset(self):
        self.holding = False
        super().reset()

    def hud(self):
        h = super().hud()
        if self.holding:                                  # active, not cooling down; Shift cancels it
            h = h._replace(cd_left=0.0, cd_frac=0.0, usable=True)
        return h


# ============================ FLAME STRIKE ===================================
_EMBER = {'key': None, 'n': 0}


def _embers(world, x, y, z):
    """Ember particles behind flame strikes: at most flame_embers_per_frame per frame in total."""
    key = (id(world), world.frame)
    if _EMBER['key'] != key:
        _EMBER['key'] = key
        _EMBER['n'] = 0
    n = min(2, T['flame_embers_per_frame'] - _EMBER['n'])
    if n <= 0:
        return
    _EMBER['n'] += n
    world.burst(x, y, z, n, (255, 150, 40), 0.8, 0.35, 2)


def _flame_on_hit(world, proj, target, x, y):
    if target is None:                                   # wall: a small fiery splash, then the default spark
        world.burst(x, y, proj.z, 6, (255, 140, 40), 1.8, 0.35, 2)
    return False


def _draw_flame(scene, p):
    """One big orange orb plus two trailing orbs (they appear once the strike has travelled that far)."""
    sp = math.hypot(p.vx, p.vy) or 1.0
    ux = p.vx / sp
    uy = p.vy / sp
    gone = math.hypot(p.x - p.ox, p.y - p.oy)
    scene.orb(p.x, p.y, p.z, T['flame_orb'], FLAME, FLAME_CORE)
    for off, r, col in ((0.35, 0.13, (240, 90, 20)), (0.7, 0.09, (200, 60, 12))):
        if gone > off:
            scene.orb(p.x - ux * off, p.y - uy * off, p.z - 0.03, r, col, None)


class FlameStrike(Projectile):
    """Piercing fire wave (pierce=True, through_barriers=True); drops embers while it flies."""

    def update(self, world, dt):
        super().update(world, dt)
        if self.alive:
            _embers(world, self.x, self.y, self.z)


# ============================ QUAKE SLAM =====================================
class QuakeWave(Effect):
    """The ult's wave front. Each frame the front advances quake_speed * dt (up to quake_len); every alive
    enemy inside the +-quake_half_deg cone whose distance (centre minus radius) the front has passed is
    resolved once: hit (120 + stun) if the origin sees it (walls) and no active enemy barrier crosses the
    origin-to-enemy segment, otherwise skipped (the barrier takes no damage). Rock orbs (at most 24) spawn
    along the cone as the front advances and shrink away over quake_rock_ttl."""

    def __init__(self, hero, world):
        self.alive = True
        self.owner = hero
        self.team = hero.team
        self.x = hero.x
        self.y = hero.y
        self.angle = hero.angle
        self.front = 0.0
        self.done = set()
        self.rocks = []                  # (x, y, born, size)
        self.spawned = 0
        self.next_rock = 0.4
        self.t0 = world.now
        self.now = world.now
        self.hit_ids = []

    def update(self, world, dt):
        self.now = world.now
        length = T['quake_len']
        if self.front < length:
            # time-based, so the front is exactly quake_speed x (time since the cast), slow-mo included
            self.front = min(length, T['quake_speed'] * (world.now - self.t0))
            self._resolve(world)
            self._spawn_rocks(world)
        ttl = T['quake_rock_ttl']
        if self.rocks and self.now - self.rocks[0][2] >= ttl:
            self.rocks = [r for r in self.rocks if self.now - r[2] < ttl]
        if self.front >= length and not self.rocks:
            self.alive = False

    def resolve_all(self, world):
        """Resolve the whole cone at once (used only when the effect cap refuses the wave)."""
        self.front = T['quake_len']
        self._resolve(world)

    def _blocked_by_barrier(self, world, e):
        for b in world.barriers:
            if b.active and b.team != self.team and b.intersects(self.x, self.y, e.x, e.y) is not None:
                return True
        return False

    def _resolve(self, world):
        half = math.radians(T['quake_half_deg'])
        ox, oy = self.x, self.y
        for e in world.enemies:
            if not e.alive or e.id in self.done:
                continue
            dx = e.x - ox
            dy = e.y - oy
            d = math.hypot(dx, dy)
            if d - e.radius > self.front:
                continue
            if d > 1e-6 and abs(core.wrap_angle(math.atan2(dy, dx) - self.angle)) > half:
                continue
            self.done.add(e.id)
            if not los(ox, oy, e.x, e.y) or self._blocked_by_barrier(world, e):
                continue
            apply_damage(world, e, T['quake_damage'], self.owner, ability='ult', from_xy=(ox, oy))
            if e.alive:
                e.status.add('stun', T['quake_stun'] * e.STUN_MULT, world.now)
            world.burst(e.x, e.y, 0.1, 4, (170, 130, 80), 2.0, 0.4, 2)
            self.hit_ids.append(e.id)

    def _spawn_rocks(self, world):
        rng = world.fx_rng
        half = math.radians(T['quake_half_deg'])
        cap = T['quake_rocks']
        step = T['quake_len'] / (cap / 2.0)
        while self.next_rock <= self.front and self.spawned < cap:
            d = self.next_rock
            for _ in range(2):
                self.spawned += 1
                a = self.angle + rng.uniform(-half, half) * min(1.0, 0.35 + d / T['quake_len'])
                rx = self.x + math.cos(a) * d
                ry = self.y + math.sin(a) * d
                if not is_wall(rx, ry) and los(self.x, self.y, rx, ry):
                    self.rocks.append((rx, ry, self.now, rng.uniform(0.045, 0.085)))
            self.next_rock += step

    def emit_visuals(self, scene):
        ttl = T['quake_rock_ttl']
        now = scene.now
        for rx, ry, born, size in self.rocks:
            k = 1.0 - (now - born) / ttl
            if k <= 0.0:
                continue
            s = 0.55 + 0.45 * k
            col = (int(ROCK[0] * s), int(ROCK[1] * s), int(ROCK[2] * s))
            scene.orb(rx, ry, 0.05 + size * 0.6 * k, size * (0.35 + 0.65 * k), col,
                      (min(255, col[0] + 40), min(255, col[1] + 32), min(255, col[2] + 24)))


# ============================ the hero =======================================
@core.register_hero
class Rampart(Hero):
    KEY = 'rampart'
    NAME = 'RAMPART'
    ROLE = 'TANK'
    DIFFICULTY = 2
    COLOR = (230, 180, 60)
    BLURB = 'Hold the line. Hammer, shield, charge.'
    KIT = (('LMB', 'ROCKET HAMMER', 'Wide swing that hits everything in front.'),
           ('RMB/F', 'BARRIER (HOLD)', '600 HP shield that blocks enemy shots.'),
           ('SHIFT', 'CHARGE', 'Rush forward, pin an enemy, slam it into a wall.'),
           ('E', 'FLAME STRIKE', 'Piercing fire wave. 2 charges.'),
           ('Q', 'QUAKE SLAM', 'Stun every enemy in front of you.'))
    LABELS = {'primary': 'HAMMER', 'ab1': 'CHARGE', 'ab2': 'FLAME STRIKE', 'ult': 'QUAKE', 'melee': 'MELEE'}
    HEALTH = 300
    ARMOR = 200
    SHIELDS = 0
    SPEED = 3.9
    ULT_COST = 1400
    ULT_NAME = 'QUAKE SLAM'
    ULT_CALLOUT = 'QUAKE!'
    ULT_DURATION = 0.0
    MAX_AMMO = 0
    RELOAD_TIME = 0.0
    HUD_ORDER = ('ab1', 'ab2', 'secondary')

    def __init__(self, world):
        super().__init__(world)
        self.abilities = {
            'secondary': Ability(self, 'secondary', 'BARRIER', 'RMB', T['barrier_lockout']),
            'ab1': _HoldAbility(self, 'ab1', 'CHARGE', 'SHIFT', T['charge_cd'], duration=T['charge_time']),
            'ab2': Ability(self, 'ab2', 'FLAME STRIKE', 'E', T['flame_cd'], charges=T['flame_charges']),
        }
        self.barrier = Barrier(TEAM_PLAYER, T['barrier_hp'], T['barrier_half_width'], owner=self)
        self.barrier.owner_view_only = True            # drawn as the screen overlay, not in the world
        self.barrier_up = False
        self.abilities['secondary'].meter = 1.0
        self._lowered_at = -99.0
        self._busy_until = -1.0                        # barrier blocked until (flame flick / quake slam)
        self._next_swing = 0.0
        self._swing_t = -9.0
        self._flick_t = -9.0
        self._quake_t = -9.0
        # charge
        self.charging = False
        self._charge_t0 = -9.0
        self._charge_left = 0.0
        self._charge_end_t = -9.0
        self.charge_end_reason = ''
        self._pinned = None
        self._brushed = set()
        self._effects = []
        # viewmodel smoothing (presentation only)
        self._vm_low = 0.0
        self._vm_tuck = 0.0
        self._vm_frame = -1
        try:
            _overlays()                                # once per session: no hitch at the first raise
        except Exception:
            pass

    # --- input ----------------------------------------------------------------------------
    def on_input(self, inp, world):
        now = world.now
        self._check_broken(world)
        if inp.hit('ab1'):
            if self.charging:
                if now - self._charge_t0 >= T['charge_cancel_after'] - 1e-9:
                    self._end_charge(world, 'cancel')
            else:
                self._start_charge(world)
        if inp.hit('ab2') and not self.charging and self.abilities['ab2'].use(world):
            self._flame(world)
        want = inp.down('alt') and self._barrier_allowed(world)
        if want and not self.barrier_up:
            self._raise(world)
        elif not want and self.barrier_up:
            self._lower(world)
        if self.barrier_up:
            self.speed_mult *= T['barrier_speed_mult']
        if inp.down('fire') and not self.barrier_up and not self.charging and now >= self._next_swing:
            self._swing(world)

    # --- per frame ----------------------------------------------------------------------------
    def think(self, world, dt):
        now = world.now
        b = self.barrier
        sec = self.abilities['secondary']
        self._check_broken(world)
        if self.barrier_up and (self.charging or now < self._busy_until or not self.can_act(world)):
            self._lower(world)
        if (not self.barrier_up and sec.charges > 0 and b.hp < b.max_hp
                and now - self._lowered_at >= T['barrier_regen_delay']):
            b.hp = min(b.max_hp, b.hp + T['barrier_regen'] * dt)
        sec.meter = b.hp / b.max_hp
        if self.charging:
            self._charge_update(world, dt)

    def after_move(self, world, dt):
        if self.barrier_up:
            self._pose_barrier()
        self.abilities['secondary'].active_left = 1.0 if self.barrier_up else 0.0

    # --- barrier ------------------------------------------------------------------------------
    def _check_broken(self, world):
        """Barrier.take() deactivated it (hp 0) during the last projectile / enemy pass: force it down and
        start the 5 s lockout. Runs first in on_input and in think, before anything can lower it normally."""
        if self.barrier_up and not self.barrier.active:
            self._lower(world)
            self.barrier.hp = 0.0
            self.abilities['secondary'].start_cooldown(T['barrier_lockout'])

    def _barrier_allowed(self, world):
        return (not self.charging and world.now >= self._busy_until
                and self.abilities['secondary'].charges > 0 and self.barrier.hp >= T['barrier_min_hp'])

    def _pose_barrier(self):
        d = T['barrier_dist']
        a = self.angle
        self.barrier.set_pose(self.x + math.cos(a) * d, self.y + math.sin(a) * d, a)

    def _raise(self, world):
        b = self.barrier
        b.active = True
        self._pose_barrier()
        if world.add_barrier(b):
            self.barrier_up = True
            world.bus.emit('ability_used', hero=self.KEY, slot='secondary', name='BARRIER')

    def _lower(self, world):
        if self.barrier_up:
            self.barrier_up = False
            self._lowered_at = world.now
        world.remove_barrier(self.barrier)

    # --- hammer -------------------------------------------------------------------------------
    def _swing(self, world):
        now = world.now
        self._next_swing = now + T['hammer_interval']
        self._swing_t = now
        self.last_fire = now
        world.bus.emit('ability_used', hero=self.KEY, slot='primary', name=self.label_for('primary'))
        half = math.radians(T['hammer_arc_deg'])
        reach = T['hammer_reach']
        x, y, a = self.x, self.y, self.angle
        hit = False
        for e in cone_targets(world, x, y, a, half, reach):
            apply_damage(world, e, T['hammer_damage'], self, ability='primary', from_xy=(x, y))
            world.burst(e.x, e.y, e.height * e.height_mult * 0.6, T['hammer_sparks'], (255, 220, 140),
                        2.5, 0.3, 2)
            if e.alive and not e.BOSS:
                knockback(world, e, x, y, T['hammer_knockback'])
            hit = True
        for b in tuple(world.barriers):                         # enemy barriers never block the hammer
            if not b.active or b.team == self.team:
                continue
            mx = (b.x1 + b.x2) * 0.5
            my = (b.y1 + b.y2) * 0.5
            dx = mx - x
            dy = my - y
            d = math.hypot(dx, dy)
            if d > reach or (d > 1e-6 and abs(core.wrap_angle(math.atan2(dy, dx) - a)) > half):
                continue
            if not los(x, y, mx, my):
                continue
            b.take(world, T['hammer_damage'], self)
            world.burst(mx, my, 0.5, T['hammer_sparks'], (120, 200, 255), 2.0, 0.3, 2)
            hit = True
        if hit:
            world.shake(*T['hammer_shake'])

    # --- flame strike ---------------------------------------------------------------------------
    def _flame(self, world):
        a = self.angle
        c = math.cos(a)
        s = math.sin(a)
        off = 0.3
        x = self.x + c * off
        y = self.y + s * off
        if is_wall(x, y):
            x, y, off = self.x, self.y, 0.0
        sp = T['flame_speed']
        p = FlameStrike(x, y, a, sp, team=TEAM_PLAYER, damage=T['flame_damage'], radius=T['flame_radius'],
                        owner=self, ability='ab2', ttl=(T['flame_range'] - off) / sp, z=0.4, color=FLAME,
                        core=FLAME_CORE, size=T['flame_orb'], pierce=True, through_barriers=True,
                        on_hit=_flame_on_hit, draw=_draw_flame)
        world.add_projectile(p)
        self._flick_t = world.now
        self._busy_until = max(self._busy_until, world.now + T['flame_flick'])

    # --- charge -----------------------------------------------------------------------------------
    def _start_charge(self, world):
        ab = self.abilities['ab1']
        if self.charging or not ab.ready() or not self.status.can_move(world.now):
            return False
        if self.barrier_up:
            self._lower(world)
        self.charging = True
        self._charge_t0 = world.now
        self._charge_left = T['charge_time']
        self._pinned = None
        self._brushed = set()
        self.charge_end_reason = ''
        self.knockback_immune = True
        self.turn_limit = math.radians(T['charge_turn_deg'])
        ab.charges = 0
        ab.recharge_left = ab.cooldown
        ab.holding = True
        ab.start(T['charge_time'])
        world.bus.emit('ability_used', hero=self.KEY, slot='ab1', name=ab.name)
        return True

    def _end_charge(self, world, reason, cooldown=True):
        if not self.charging:
            return
        self.charging = False
        self.charge_end_reason = reason
        self._charge_end_t = world.now
        self.knockback_immune = False
        self.turn_limit = None
        self._release()
        ab = self.abilities['ab1']
        ab.holding = False
        ab.stop()
        if cooldown:                                  # the cooldown starts when the charge ends
            ab.charges = 0
            ab.recharge_left = ab.cooldown

    def _release(self):
        e = self._pinned
        self._pinned = None
        if e is not None:
            e.status.remove('pinned')

    def _charge_update(self, world, dt):
        self.custom_motion = True
        world.shake(T['charge_shake'], 0.06)
        dist = T['charge_speed'] * min(dt, self._charge_left)
        n = max(1, int(math.ceil(dist / T['charge_step'] - 1e-9)))
        step = dist / n
        for _ in range(n):
            if not self._charge_step(world, step):
                return
        self._charge_left -= dt
        self.abilities['ab1'].active_left = max(0.0, self._charge_left)
        if self._charge_left <= 1e-9:
            self._end_charge(world, 'time')

    def _charge_step(self, world, step):
        """Advance one sub-step; returns False once the charge has ended (Rampart never enters a wall)."""
        a = self.angle
        c = math.cos(a)
        s = math.sin(a)
        nx = self.x + c * step
        ny = self.y + s * step
        pe = self._pinned
        if pe is not None and not pe.alive:
            self._release()
            pe = None
        if pe is not None:
            carry = T['charge_carry']
            ex = nx + c * carry
            ey = ny + s * carry
            if _blocked(nx, ny, self.radius) or _blocked(ex, ey, pe.radius):
                self._slam(world, pe, c, s)
                return False
            self.x, self.y = nx, ny
            pe.x, pe.y = ex, ey
            pe.angle = a + math.pi
            pe.status.add('pinned', self._charge_left + 0.2, world.now)
        else:
            if _blocked(nx, ny, self.radius):
                self._impact(world, self.x + c * (self.radius + 0.05), self.y + s * (self.radius + 0.05))
                self._end_charge(world, 'wall')
                return False
            self.x, self.y = nx, ny
        return self._charge_contacts(world, c, s)

    def _charge_contacts(self, world, c, s):
        reach = T['charge_pin_reach']
        brush_r = T['charge_brush_radius']
        for e in tuple(world.enemies):
            pe = self._pinned
            if not e.alive or e is pe:
                continue
            dx = e.x - self.x
            dy = e.y - self.y
            d = math.hypot(dx, dy)
            proj = dx * c + dy * s
            lat = -dx * s + dy * c
            lane = proj > 0.0 and abs(lat) <= e.radius + self.radius
            if pe is not None:
                dfront = math.hypot(e.x - pe.x, e.y - pe.y)
                front_touch = dfront <= e.radius + pe.radius + 0.1
            else:
                dfront = 99.0
                front_touch = False
            if getattr(e, 'BOSS', False):
                if (lane and d <= e.radius + reach) or front_touch:
                    self._hit_boss(world, e, c, s)
                    return False
            elif pe is None and lane and e.PINNABLE:
                if d <= e.radius + reach:
                    if not self._pin(world, e, c, s):
                        return False
                continue                                     # still ahead in the lane: pin it, don't brush it
            if e.id in self._brushed or min(d, dfront) > brush_r:
                continue
            self._brushed.add(e.id)
            apply_damage(world, e, T['charge_brush_damage'], self, ability='ab1', from_xy=(self.x, self.y))
            if e.alive:
                side = 1.0 if lat >= 0.0 else -1.0
                px = -s * side                               # sideways, away from the path
                py = c * side
                knockback(world, e, e.x - px, e.y - py, T['charge_brush_knockback'])
        return True

    def _pin(self, world, e, c, s):
        self._pinned = e
        self._brushed.add(e.id)
        e.status.add('pinned', self._charge_left + 0.2, world.now)
        carry = T['charge_carry']
        ex = self.x + c * carry
        ey = self.y + s * carry
        if _blocked(ex, ey, e.radius):                     # pinned right against a wall: slam at once
            self._slam(world, e, c, s)
            return False
        e.x, e.y = ex, ey
        return True

    def _slam(self, world, e, c, s):
        apply_damage(world, e, T['charge_pin_damage'], self, ability='ab1', from_xy=(self.x, self.y))
        self._impact(world, e.x + c * e.radius, e.y + s * e.radius)
        self._end_charge(world, 'slam')

    def _hit_boss(self, world, boss, c, s):
        apply_damage(world, boss, T['charge_boss_damage'], self, ability='ab1', from_xy=(self.x, self.y))
        pe = self._pinned
        if pe is not None and pe.alive:                    # crushed between Rampart and the boss
            apply_damage(world, pe, T['charge_pin_damage'], self, ability='ab1', from_xy=(self.x, self.y))
        self._impact(world, boss.x - c * boss.radius, boss.y - s * boss.radius)
        self._end_charge(world, 'boss')

    def _impact(self, world, x, y):
        world.shake(*T['charge_impact_shake'])
        world.burst(x, y, 0.45, T['charge_impact_particles'], (255, 200, 120), 3.0, 0.5, 2)
        world.bus.emit('sfx', name='hammer', vol=1.0)

    # --- ult ------------------------------------------------------------------------------------
    def on_ult(self, world):
        now = world.now
        if self.charging:
            self._end_charge(world, 'ult')
        if self.barrier_up:
            self._lower(world)
        self._busy_until = max(self._busy_until, now + T['quake_root'])
        self._quake_t = now
        self.status.add('root', T['quake_root'], now)
        world.shake(*T['quake_shake'])
        a = self.angle
        world.burst(self.x + math.cos(a) * 0.7, self.y + math.sin(a) * 0.7, 0.05, 10, (150, 115, 75), 3.0,
                    0.5, 2)
        q = QuakeWave(self, world)
        self._effects = [e for e in self._effects if e.alive]
        if world.add_effect(q):
            self._effects.append(q)
        else:                                              # effect cap reached: resolve the whole cone now
            q.resolve_all(world)
            q.alive = False

    # --- lifecycle ----------------------------------------------------------------------------
    def on_removed(self, world):
        self._end_charge(world, 'removed', cooldown=False)
        self._lower(world)
        for e in self._effects:
            e.alive = False
        self._effects = []

    def restore(self, world):
        self._end_charge(world, 'restore', cooldown=False)
        super().restore(world)
        self.barrier.hp = self.barrier.max_hp
        self.barrier.active = True
        self.abilities['secondary'].meter = 1.0

    # ============================ presentation ===================================
    def _vm_smooth(self, world):
        """Ease the 'lowered behind the barrier' and 'tucked for the charge' amounts (once per frame)."""
        if self._vm_frame == world.frame:
            return
        self._vm_frame = world.frame
        k = min(1.0, max(world.dt, 1.0 / 60.0) * 14.0)
        self._vm_low += ((1.0 if self.barrier_up else 0.0) - self._vm_low) * k
        self._vm_tuck += ((1.0 if self.charging else 0.0) - self._vm_tuck) * k

    def _hammer_pose(self, now):
        """(pivot x, pivot y, angle deg, sweep 0..1 or None, rocket glow 0..1) for the viewmodel."""
        px, py, th = 860.0, 900.0, -8.0
        if self.move_fwd or self.move_right:
            px += 5.0 * math.sin(now * 4.2)
            py += 7.0 * abs(math.sin(now * 4.2))
        sweep = None
        glow = 0.0
        age = now - self._quake_t
        sw = now - self._swing_t
        fl = now - self._flick_t
        if 0.0 <= age < 0.75:                              # raise, slam, settle
            if age < 0.25:
                u = age / 0.25
                th, py = -8.0 + 26.0 * u, 900.0 - 80.0 * u
            elif age < 0.4:
                u = (age - 0.25) / 0.15
                th, py = 18.0 - 70.0 * u, 820.0 + 150.0 * u
                sweep = u
            else:
                u = (age - 0.4) / 0.35
                th, py = -52.0 + 44.0 * u, 970.0 - 70.0 * u
        elif 0.0 <= sw < T['hammer_sweep']:                # right-to-left sweep: rotate about the grip while
            u = sw / T['hammer_sweep']                     # the arm carries the grip leftwards
            e = 1.0 - (1.0 - u) ** 2
            th = 40.0 - 95.0 * e
            px = 900.0 - 300.0 * e
            py = 900.0 + 30.0 * e
            sweep = u
            glow = 1.0 - u
        elif 0.0 <= sw < T['hammer_sweep'] + 0.4:          # recover: dip below the screen, back to the right
            u = (sw - T['hammer_sweep']) / 0.4
            e = u * u * (3.0 - 2.0 * u)
            th = -55.0 + 47.0 * e
            px = 600.0 + 260.0 * e
            py = 930.0 - 30.0 * e + 160.0 * math.sin(math.pi * e)
        elif 0.0 <= fl < T['flame_flick']:                 # flame strike flick
            k = math.sin(math.pi * fl / T['flame_flick'])
            th += 26.0 * k
            px -= 40.0 * k
            py -= 40.0 * k
            glow = k
        low = self._vm_low
        tuck = self._vm_tuck
        if low > 0.001:
            px, py, th = px + (905.0 - px) * low, py + (1030.0 - py) * low, th + (6.0 - th) * low
        if tuck > 0.001:
            px, py, th = px + (800.0 - px) * tuck, py + (975.0 - py) * tuck, th + (-58.0 - th) * tuck
            sweep = None
        return px, py, th, sweep, glow

    def draw_viewmodel(self, surf, world):
        self._vm_smooth(world)
        px, py, th, sweep, glow = self._hammer_pose(world.now)
        if sweep is not None and sweep < 1.0:
            _draw_streak(surf, px, py, th)
        _draw_hammer(surf, px, py, th, glow)
        if self._vm_low > 0.02:
            _draw_projector(surf, self._vm_low, world.now - self.barrier.last_hit < T['barrier_flash'],
                            self.barrier.hp / self.barrier.max_hp < T['barrier_low_frac'])

    def draw_overlay(self, surf, world):
        if self.barrier_up:
            b = self.barrier
            frac = b.hp / b.max_hp
            low = frac < T['barrier_low_frac']
            flash = world.now - b.last_hit < T['barrier_flash']              # hex lines brighten on hits
            ov = _overlays()[('orange' if low else 'blue', flash)]
            x, y, strips = _OV_POS
            tint = T['overlay_tint_low'] if low else T['overlay_tint']
            add = pygame.BLEND_RGB_ADD
            for r in strips:                                                 # the faint tint outside the
                surf.fill(tint, r, add)                                      # overlay (baked in inside)
            surf.blit(ov, (x, y), special_flags=add)
            bw, bh, by = T['hp_bar']
            bx = C.W // 2 - bw // 2
            surf.fill((16, 20, 30), (bx - 2, by - 2, bw + 4, bh + 4))
            surf.fill(SHIELD_ORANGE if low else SHIELD_BLUE, (bx, by, int(bw * frac + 0.5), bh))
        if self.charging:
            _draw_speed_lines(surf, world.now)

    def draw_crosshair(self, surf, world):
        cx, cy = C.W // 2, C.H // 2
        ready = world.now >= self._next_swing and not self.barrier_up and not self.charging
        col = (255, 255, 255) if ready else (150, 150, 160)
        surf.fill(col, (cx - 1, cy - 1, 3, 3))
        pygame.draw.arc(surf, col, (cx - 60, cy - 60, 120, 120), math.radians(205), math.radians(335), 2)

    @classmethod
    def draw_icon(cls, slot, surf, rect):
        fn = _ICONS.get(slot)
        if fn is None:
            return super().draw_icon(slot, surf, rect)
        rect = pygame.Rect(rect)
        clip = surf.get_clip()
        surf.set_clip(rect)
        try:
            fn(surf, rect)
        finally:
            surf.set_clip(clip)
        return None


# ============================ viewmodel painters (screen space) ==============
_HAMMER_L = 300.0          # grip to head, px


def _draw_hammer(surf, px, py, th_deg, glow=0.0):
    """Rocket hammer rotated by th_deg about the grip (px, py): positive tilts the head to the right.
    Head 150x90 px; a rocket nozzle on the trailing (right) end, the striking face on the left."""
    th = math.radians(th_deg)
    cs = math.cos(th)
    sn = math.sin(th)

    def P(lx, ly):
        return (px + lx * cs - ly * sn, py + lx * sn + ly * cs)
    poly = pygame.draw.polygon
    L = _HAMMER_L
    poly(surf, HANDLE, [P(-9, 20), P(9, 20), P(8, -L), P(-8, -L)])
    for gy in (-30, -62, -94):
        poly(surf, GRIP, [P(-11, gy), P(11, gy), P(11, gy - 14), P(-11, gy - 14)])
    poly(surf, GOLD_D, [P(-12, -L + 60), P(12, -L + 60), P(12, -L + 48), P(-12, -L + 48)])
    top = -L - 90
    head = [P(-70, -L), P(70, -L), P(75, -L - 8), P(75, top + 8), P(70, top), P(-70, top), P(-75, top + 8),
            P(-75, -L - 8)]
    poly(surf, STEEL, head)
    poly(surf, STEEL_L, [P(-70, top), P(70, top), P(66, top + 12), P(-66, top + 12)])
    poly(surf, STEEL_D, [P(-70, -L), P(70, -L), P(66, -L - 12), P(-66, -L - 12)])
    poly(surf, DARK, [P(-75, -L - 8), P(-60, -L - 14), P(-60, top + 14), P(-75, top + 8)])        # face
    poly(surf, DARK, [P(75, -L - 20), P(97, -L - 12), P(97, top + 12), P(75, top + 20)])        # nozzle
    poly(surf, GOLD, [P(-13, -L - 2), P(13, -L - 2), P(13, top + 2), P(-13, top + 2)])          # band
    poly(surf, GOLD, [P(-22, -L + 14), P(22, -L + 14), P(22, -L - 4), P(-22, -L - 4)])          # collar
    cx, cy = P(0, -L - 45)
    pygame.draw.circle(surf, GOLD_D, (int(cx), int(cy)), 14)
    pygame.draw.circle(surf, (255, 214, 120) if glow > 0.2 else (120, 90, 40), (int(cx), int(cy)), 6)
    pygame.draw.polygon(surf, DARK, head, 2)
    if glow > 0.05:                                         # rocket burst from the nozzle
        g = min(1.0, glow)
        fl = [P(97, -L - 16), P(97 + 60 * g, -L - 45), P(97, top + 16)]
        poly(surf, (255, 140, 40), fl)
        poly(surf, (255, 230, 140), [P(97, -L - 30), P(97 + 30 * g, -L - 45), P(97, top + 30)])


def _draw_streak(surf, px, py, th_deg):
    """Three motion lines trailing the head arc during the sweep."""
    for r, w, col in ((_HAMMER_L + 5, 3, (255, 240, 200)), (_HAMMER_L + 45, 2, (255, 210, 150)),
                      (_HAMMER_L + 85, 2, (230, 170, 100))):
        pts = []
        for k in range(5):
            a = math.radians(th_deg + 6.0 + k * 7.0)
            pts.append((px + r * math.sin(a), py - r * math.cos(a)))
        pygame.draw.lines(surf, col, False, pts, w)


def _draw_projector(surf, low, flash, orange):
    """The barrier projector gauntlet sliding in from the bottom-left while the barrier is up."""
    off = int((1.0 - low) * 200)
    pts = [(0, 768 + off), (0, 700 + off), (150, 626 + off), (212, 650 + off), (170, 768 + off)]
    pygame.draw.polygon(surf, (40, 43, 52), pts)
    pygame.draw.polygon(surf, GOLD_D, pts, 2)
    pygame.draw.polygon(surf, (28, 30, 37), [(30, 712 + off), (135, 660 + off), (160, 690 + off), (55, 750 + off)])
    col = SHIELD_ORANGE if orange else SHIELD_BLUE
    ex, ey = 176, 648 + off
    pygame.draw.circle(surf, GOLD_D, (ex, ey), 17)
    pygame.draw.circle(surf, col, (ex, ey), 12)
    pygame.draw.circle(surf, (255, 255, 255) if flash else (210, 240, 255), (ex, ey), 5)


def _draw_speed_lines(surf, now):
    """16 radial speed lines from the screen edge toward the centre (outside the 200x200 crosshair box)."""
    cx, cy = C.W // 2, C.H // 2
    col = (255, 236, 196)
    for k in range(16):
        a = k * (math.pi / 8.0) + 0.12 * math.sin(now * 9.0 + k * 1.7)
        ph = (now * 4.5 + k * 0.618) % 1.0
        r0 = 700.0 - 140.0 * ph
        r1 = r0 - 150.0 - 50.0 * ((k * 7) % 3)
        ca = math.cos(a)
        sa = math.sin(a)
        pygame.draw.line(surf, col, (cx + ca * r0, cy + sa * r0 * 0.78), (cx + ca * r1, cy + sa * r1 * 0.78), 2)


_OV = {}


def _overlays():
    """{(colour, bright): 880x480 RGB surface} for one BLEND_RGB_ADD blit per frame: the hex grid with the
    faint tint baked in; 'bright' has the lines doubled (the 0.08 s hit flash). All four are built together
    once per session (Rampart.__init__ calls this at match start / swap, after set_mode), so neither the
    first raise nor the low-HP colour ever allocates mid-fight."""
    if not _OV:
        built = {}
        for kind, tint in (('blue', T['overlay_tint']), ('orange', T['overlay_tint_low'])):
            lines = _build_hex_overlay(kind)
            for bright in (False, True):
                s = lines.copy()
                if bright:
                    s.blit(lines, (0, 0), special_flags=pygame.BLEND_RGB_ADD)
                s.fill(tint, None, pygame.BLEND_RGB_ADD)
                built[(kind, bright)] = s
        _OV.update(built)
    return _OV


def _overlay_frame():
    """Top-left of the centred overlay and the 4 screen strips around it (they get the tint by fill)."""
    ow, oh = T['overlay_size']
    x = (C.W - ow) // 2
    y = (C.H - oh) // 2
    return x, y, ((0, 0, C.W, y), (0, y + oh, C.W, C.H - y - oh), (0, y, x, oh), (x + ow, y, C.W - x - ow, oh))


_OV_POS = _overlay_frame()


def _build_hex_overlay(kind):
    """Lines are dimmer toward the centre so the crosshair area stays readable."""
    w, h = T['overlay_size']
    s = pygame.Surface((w, h))
    s.fill((0, 0, 0))
    base = (40, 120, 215) if kind == 'blue' else (225, 110, 25)
    R = 30.0
    dx = math.sqrt(3.0) * R
    dy = 1.5 * R
    cx = w * 0.5
    cy = h * 0.5
    nx = int(w / dx / 2) + 2
    ny = int(h / dy / 2) + 2
    corners = [(math.cos(math.radians(60 * k - 30)), math.sin(math.radians(60 * k - 30))) for k in range(6)]
    for row in range(-ny, ny + 1):
        for col in range(-nx, nx + 1):
            hx = cx + col * dx + (dx * 0.5 if row & 1 else 0.0)
            hy = cy + row * dy
            e = min(1.0, max(abs(hx - cx) / (w * 0.5), abs(hy - cy) / (h * 0.5)))
            k = 0.28 + 0.72 * e ** 1.6
            c = (int(base[0] * k), int(base[1] * k), int(base[2] * k))
            pygame.draw.polygon(s, c, [(hx + R * ux, hy + R * uy) for ux, uy in corners], 1)
    rim = (min(255, int(base[0] * 1.3)), min(255, int(base[1] * 1.3)), min(255, int(base[2] * 1.3)))
    pygame.draw.rect(s, rim, (0, 0, w, h), 3, border_radius=22)
    pygame.draw.rect(s, (base[0] // 2, base[1] // 2, base[2] // 2), (7, 7, w - 14, h - 14), 1, border_radius=16)
    try:
        s = s.convert()
    except Exception:
        pass
    return s


# ============================ icons (drawn once; the HUD caches them) ========
def _icon_frame(r):
    m = min(r.w, r.h)
    cx, cy = r.center

    def P(u, v):
        return (cx + u * m, cy + v * m)
    return m, P, max(1, int(round(m / 40.0)))


def _icon_portrait(surf, r):
    m, P, lw = _icon_frame(r)
    cx, cy = r.center
    pygame.draw.circle(surf, (56, 44, 22), (cx, cy), int(m * 0.48))
    for sgn in (-1, 1):                                                  # pauldrons
        pygame.draw.polygon(surf, GOLD_D, [P(0.52 * sgn, 0.55), P(0.46 * sgn, 0.30), P(0.30 * sgn, 0.22),
                                           P(0.12 * sgn, 0.30), P(0.10 * sgn, 0.55)])
        pygame.draw.polygon(surf, GOLD, [P(0.46 * sgn, 0.30), P(0.30 * sgn, 0.22), P(0.12 * sgn, 0.30),
                                         P(0.14 * sgn, 0.35), P(0.30 * sgn, 0.28), P(0.44 * sgn, 0.35)])
    helm = [P(-0.25, 0.30), P(-0.29, 0.0), P(-0.25, -0.22), P(-0.13, -0.34), P(0.13, -0.34), P(0.25, -0.22),
            P(0.29, 0.0), P(0.25, 0.30), P(0.10, 0.37), P(-0.10, 0.37)]
    pygame.draw.polygon(surf, STEEL, helm)
    pygame.draw.polygon(surf, STEEL_L, [P(-0.13, -0.34), P(0.13, -0.34), P(0.20, -0.25), P(-0.20, -0.25)])
    pygame.draw.polygon(surf, DARK, [P(-0.26, -0.09), P(0.26, -0.09), P(0.23, 0.02), P(-0.23, 0.02)])   # visor
    pygame.draw.line(surf, (255, 205, 90), P(-0.20, -0.035), P(0.20, -0.035), lw + 1)
    pygame.draw.polygon(surf, GOLD, [P(-0.05, -0.38), P(0.05, -0.38), P(0.035, -0.10), P(-0.035, -0.10)])  # crest
    for i in range(-2, 3):                                               # breathing grille
        pygame.draw.line(surf, DARK, P(i * 0.05, 0.10), P(i * 0.05, 0.24), lw)
    pygame.draw.line(surf, GOLD, P(-0.25, 0.30), P(0.0, 0.40), lw + 1)
    pygame.draw.line(surf, GOLD, P(0.0, 0.40), P(0.25, 0.30), lw + 1)
    pygame.draw.polygon(surf, DARK, helm, lw)
    pygame.draw.circle(surf, GOLD, (cx, cy), int(m * 0.48), max(2, lw + 1))


def _hexagon(P, u, v, rad):
    return [P(u + rad * math.cos(math.radians(60 * k - 30)), v + rad * math.sin(math.radians(60 * k - 30)))
            for k in range(6)]


def _icon_barrier(surf, r):
    m, P, lw = _icon_frame(r)
    pygame.draw.polygon(surf, (22, 52, 90), _hexagon(P, 0.0, 0.0, 0.42))
    cells = [(0.0, 0.0)] + [(0.2 * math.cos(math.radians(60 * k)), 0.2 * math.sin(math.radians(60 * k)))
                            for k in range(6)]
    for u, v in cells:
        pygame.draw.polygon(surf, (80, 160, 235), _hexagon(P, u, v, 0.105), lw)
    pygame.draw.polygon(surf, SHIELD_BLUE, _hexagon(P, 0.0, 0.0, 0.42), lw + 1)


def _icon_charge(surf, r):
    m, P, lw = _icon_frame(r)
    for i, (x, col) in enumerate(((-0.24, (140, 102, 38)), (-0.04, (190, 145, 50)), (0.16, GOLD))):
        pygame.draw.polygon(surf, col, [P(x, -0.28), P(x + 0.18, 0.0), P(x, 0.28), P(x - 0.1, 0.28),
                                        P(x + 0.08, 0.0), P(x - 0.1, -0.28)])
    for v in (-0.16, 0.0, 0.16):
        pygame.draw.line(surf, (220, 225, 235), P(-0.46, v), P(-0.34, v), lw)


def _icon_flame(surf, r):
    m, P, lw = _icon_frame(r)
    outer = [P(0.02, -0.42), P(0.13, -0.22), P(0.27, -0.08), P(0.29, 0.13), P(0.19, 0.31), P(0.0, 0.39),
             P(-0.19, 0.31), P(-0.29, 0.13), P(-0.21, -0.05), P(-0.11, 0.02), P(-0.08, -0.20)]
    inner = [P(0.03, -0.12), P(0.15, 0.06), P(0.13, 0.24), P(0.0, 0.31), P(-0.13, 0.24), P(-0.15, 0.10),
             P(-0.05, 0.13)]
    pygame.draw.polygon(surf, FLAME, outer)
    pygame.draw.polygon(surf, (255, 212, 90), inner)
    pygame.draw.circle(surf, (255, 250, 220), P(0.0, 0.2), max(2, int(m * 0.06)))


def _icon_quake(surf, r):
    m, P, lw = _icon_frame(r)
    pygame.draw.line(surf, (140, 110, 70), P(-0.46, 0.30), P(0.46, 0.30), lw * 2)
    for pts in (((-0.04, 0.30), (-0.14, 0.38), (-0.22, 0.34), (-0.34, 0.45)),
                ((-0.04, 0.30), (0.08, 0.40), (0.20, 0.35), (0.34, 0.46)),
                ((-0.04, 0.30), (-0.02, 0.47))):
        pygame.draw.lines(surf, (255, 200, 60), False, [P(u, v) for u, v in pts], lw + 1)
    pygame.draw.line(surf, HANDLE, P(-0.02, 0.04), P(0.30, -0.42), max(2, lw * 3))
    head = [P(-0.30, -0.02), P(0.18, -0.06), P(0.20, 0.24), P(-0.28, 0.28)]
    pygame.draw.polygon(surf, STEEL, head)
    pygame.draw.polygon(surf, GOLD, [P(-0.08, -0.04), P(0.01, -0.05), P(0.03, 0.25), P(-0.06, 0.26)])
    pygame.draw.polygon(surf, DARK, head, lw)
    for u, v in ((-0.38, 0.18), (0.38, 0.20), (-0.26, 0.08), (0.30, 0.08)):
        pygame.draw.circle(surf, ROCK, P(u, v), max(2, int(m * 0.035)))


_ICONS = {'portrait': _icon_portrait, 'secondary': _icon_barrier, 'ab1': _icon_charge, 'ab2': _icon_flame,
          'ult': _icon_quake}
