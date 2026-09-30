"""Enemy kinds, their AI state machines and code-drawn painters (spec 4.1-4.5, 7.7). ENEMIES owns this file.

Kinds: trooper, slicer, detonator, eradicator (with its enemy-team barrier) and the warden boss.
The base Enemy (combat.py) applies stage scaling and the elite modifier in __init__; this file only
reads self.speed / self.dmg_mult / self.elite.

Rules shared by every kind (4.4):
- update() runs only while the enemy can act; World calls update_disabled() while stunned or pinned,
  which shows the 'stun' painter state and cancels any windup (a Detonator fuse included).
- State decisions tick every 0.2 s (Enemy.decision_due, staggered by id); LOS to the player comes from
  Enemy.has_los (world.los_budgeted, at most 5 checks a second per enemy). Movement runs every frame.
  Range-triggered attacks (lunge, arm, stomp) test their range every frame against the cached LOS so the
  trigger distance is exact.
- No attack starts while the player is invulnerable (Enemy.can_attack).
- All enemy damage is stage-scaled: fire_bolt/melee scale inside, and every direct call here passes
  base * self.dmg_mult. Enemy damage to the player always goes through enemy_hits_player (or projectiles),
  so the player's barrier can block it.
- vstate drives the painter. Painters never read the clock; blinking alternates states.

Presentation: each painter is registered with an aspect-correct base size (the renderer stretches a
sprite to width/height x 1.27 on screen, so e.g. a trooper is 76x96, not 48x96), draws at most ~12
primitives, keeps the head/core inside the kind's crit band, and adds cyan trim for elites.
When theme.enemy_image() returns a Surface (a PNG theme), it is fitted to the base rect and given state
overlays instead. Floor telegraphs (detonator blast radius, warden stomp ring) and the Eradicator's
barrier are emitted from emit_visuals.
"""
import math

import pygame

from . import config as C
from . import core
from . import theme
from .combat import Barrier, Effect, Enemy, Projectile, enemy_hits_player, knockback, splash
from .config import TEAM_ENEMY, TEAM_PLAYER
from .render import register_painter
from .world import OPEN_CELLS, is_wall

# Spec 4.2-4.5 numbers (stage 1, before scaling). Bolt specs: (speed, radius, damage, ttl, color, core, size).
TUNING = {
    'direct_range': 3.0,                    # flow + direct steering blend (4.4)
    'elite_per_stage': 0.15, 'elite_max': 0.45,
    # TROOPER
    'trooper_engage': 7.0, 'trooper_hold': (4.0, 7.0), 'trooper_backoff': 3.5, 'trooper_strafe': 0.6,
    'trooper_flip': (1.0, 2.0), 'trooper_los_lost': 1.0, 'trooper_fire_every': 2.0, 'trooper_windup': 0.4,
    'trooper_jitter_deg': 2.0, 'trooper_first_shot': 1.0,
    'trooper_bolt': (8.0, 0.12, 10.0, 1.25, (255, 70, 50), (255, 255, 255), 0.08),
    'trooper_melee': (10.0, 1.0, 1.0),     # damage, every s, reach (centre distance)
    # SLICER
    'slicer_zig': 0.4, 'slicer_zig_hz': 2.0, 'slicer_flank_range': 5.0, 'slicer_flank_behind': 1.5,
    'slicer_lunge_range': 3.0, 'slicer_lunge_cd': 3.0, 'slicer_windup': 0.35, 'slicer_lunge_speed': 9.0,
    'slicer_lunge_dist': 2.5, 'slicer_lunge_hit_r': 0.7, 'slicer_lunge_damage': 20.0, 'slicer_recover': 0.4,
    'slicer_melee': (12.0, 0.8, 0.9),
    # DETONATOR
    'det_rush_range': 4.0, 'det_rush_speed': 2.6, 'det_arm_range': 1.5, 'det_fuse': 0.8, 'det_blink_hz': 8.0,
    'det_beep_every': 0.2, 'det_blast_r': 2.0, 'det_player_dmg': (60.0, 30.0), 'det_enemy_dmg': 120.0,
    'det_chain_delay': 0.25, 'det_chain_enemy_dmg': 120.0, 'det_chain_player_dmg': 30.0,
    # ERADICATOR
    'erad_engage': 6.0, 'erad_hold': (5.0, 7.0), 'erad_strafe': 0.5, 'erad_turn_deg': 90.0,
    'erad_barrier_hp': 400.0, 'erad_barrier_half': 1.0, 'erad_barrier_dist': 0.9, 'erad_barrier_range': 10.0,
    'erad_barrier_up': 8.0, 'erad_barrier_cd': 8.0,
    'erad_burst_every': 3.0, 'erad_burst_n': 3, 'erad_burst_gap': 0.15, 'erad_fire_arc_deg': 45.0,
    'erad_jitter_deg': 2.0, 'erad_flip': (1.5, 2.5),
    'erad_bolt': (9.0, 0.12, 10.0, 1.3, (255, 120, 40), (255, 230, 170), 0.08),
    'erad_melee': (15.0, 1.0, 1.0),
    # WARDEN
    'ward_hold': 8.0, 'ward_recon_every': (0.6, 0.45), 'ward_recon_jitter_deg': 1.5,
    'ward_recon_bolt': (10.0, 0.15, 15.0, 1.4, (220, 80, 255), (255, 220, 255), 0.10),
    'ward_sentry_first': 6.0, 'ward_sentry_every': 12.0, 'ward_sentry_range': 12.0, 'ward_sentry_windup': 0.8,
    'ward_sentry_time': 4.0, 'ward_sentry_rate': 10.0, 'ward_sentry_jitter_deg': 6.0, 'ward_sentry_recover': 1.0,
    'ward_sentry_bolt': (12.0, 0.10, 6.0, 1.2, (255, 220, 60), (255, 255, 255), 0.06),
    'ward_stomp_range': 2.5, 'ward_stomp_cd': 6.0, 'ward_stomp_windup': 0.6, 'ward_stomp_r': 3.0,
    'ward_stomp_damage': 40.0, 'ward_stomp_knock': 1.5, 'ward_stomp_slow': (0.6, 1.5),
    'ward_phase_at': 0.5, 'ward_phase_shields': 300.0, 'ward_summons': 2, 'ward_summon_r': (1.0, 3.0),
}
T = TUNING

_D2R = math.pi / 180.0
_TAU = 2.0 * math.pi
_EPS = 1e-6         # timers: 0.4 s at 30 fps is 12 frames, not 13 after float round-off


def _hypot(ax, ay, bx, by):
    return math.hypot(bx - ax, by - ay)


def _crosses_player_barrier(world, ax, ay, bx, by):
    """t along a->b where an active player-team barrier crosses it, or None."""
    best = None
    for b in world.barriers:
        if b.active and b.team == TEAM_PLAYER:
            t = b.intersects(ax, ay, bx, by)
            if t is not None and (best is None or t < best):
                best = t
    return best


# ============================ small world effects ============================
class _RingFlash(Effect):
    """An expanding floor ring (explosions, stomps): presentation only."""

    def __init__(self, x, y, r, color, dur=0.25, width=3):
        self.x = x
        self.y = y
        self.r = r
        self.color = color
        self.dur = dur
        self.width = width
        self.t = 0.0
        self.alive = True

    def update(self, world, dt):
        self.t += dt
        if self.t >= self.dur:
            self.alive = False

    def emit_visuals(self, scene):
        k = min(1.0, self.t / self.dur)
        scene.ring(self.x, self.y, self.r * (0.35 + 0.65 * k), self.color, self.width, 24)


def _blast_fx(world, x, y, r, color, n=14):
    world.burst(x, y, 0.3, n, color, 3.0, 0.5, 3)
    world.add_effect(_RingFlash(x, y, r, color))
    p = world.player
    d = _hypot(x, y, p.x, p.y)
    if d < r + 3.0:
        world.shake(6 if d < r else 3, 0.2)


class _ChainBlast(Effect):
    """Detonator killed by the player: 0.25 s later it goes off, credited to the player (ability 'chain')."""

    def __init__(self, det, killer):
        self.det = det
        self.killer = killer
        self.x = det.x
        self.y = det.y
        self.dm = det.dmg_mult
        self.left = T['det_chain_delay']
        self.alive = True

    def update(self, world, dt):
        self.left -= dt
        if self.left <= _EPS and self.alive:
            self.fire(world)

    def fire(self, world):
        self.alive = False
        x, y, r = self.x, self.y, T['det_blast_r']
        dmg = T['det_chain_enemy_dmg'] * self.dm
        splash(world, x, y, r, dmg, dmg, self.killer, TEAM_PLAYER, 'chain', exclude=(self.det,))
        p = world.player
        if p.alive and _hypot(x, y, p.x, p.y) <= r and world.los(x, y, p.x, p.y):
            enemy_hits_player(world, self.det, T['det_chain_player_dmg'] * self.dm, (x, y), 'chain')
        _blast_fx(world, x, y, r, (255, 150, 40), 16)

    def emit_visuals(self, scene):
        hot = int(scene.now * 16.0) % 2 == 0
        scene.ring(self.x, self.y, T['det_blast_r'], (255, 240, 200) if hot else (255, 60, 40), 2, 20)
        scene.orb(self.x, self.y, 0.25, 0.14, (255, 120, 40), (255, 255, 220) if hot else (255, 60, 40))


# ============================ shared base ====================================
class _Robot(Enemy):
    """Shared helpers for the 5 kinds. Subclasses implement update() (and on_disabled() to cancel windups
    while stunned/pinned) and drive their painter through vstate."""
    MELEE = None                # (damage, every s, reach)
    DEBRIS = (200, 200, 200)

    def __init__(self, world, x, y, elite=False):
        super().__init__(world, x, y, elite)
        self._melee_next = world.now + 0.5
        self._attack_until = -9.0

    # --- scaling ---------------------------------------------------------------------
    @property
    def pool_mult(self):
        """Stage x elite pool multiplier (4.3), for pools this file adds (barrier, phase-2 shields)."""
        return (1.0 + 0.15 * (self.stage - 1)) * (1.6 if self.elite else 1.0)

    def strafe(self, world, dt, speed_mult, flip_range):
        """Sidestep across the line to the player; flips on a timer or when a wall stops it. Returns the
        distance moved (0 in a 1-cell corridor, where both sides are walls)."""
        now = world.now
        a = self.angle_to_player(world)
        sx = -math.sin(a) * self._side
        sy = math.cos(a) * self._side
        want = self.speed * speed_mult * self.status.speed_mult(now) * dt
        moved = self.move_dir(world, sx, sy, dt, speed_mult, face=False)
        if now >= self._flip_at:
            self._side = -self._side
            self._flip_at = now + world.rng.uniform(*flip_range)
        elif moved < want * 0.5:
            self._side = -self._side
        return moved

    # --- movement -------------------------------------------------------------------
    def steer_dir(self, world, tx, ty):
        """Unit direction along world.flow toward the player, blended with direct steering toward (tx, ty)
        while LOS holds and (tx, ty) is within 3 cells (full direct within 1.5): Enemy.move_toward's rule."""
        dx = tx - self.x
        dy = ty - self.y
        d = math.hypot(dx, dy)
        fx, fy = world.flow.toward(self.x, self.y)
        if d < 1e-6:
            return fx, fy
        ux = dx / d
        uy = dy / d
        if fx == 0.0 and fy == 0.0:
            return ux, uy
        rng = T['direct_range']
        if d < rng and self.has_los(world):
            w = core.clamp((rng - d) / 1.5, 0.0, 1.0)
        else:
            return fx, fy
        vx = fx * (1.0 - w) + ux * w
        vy = fy * (1.0 - w) + uy * w
        m = math.hypot(vx, vy)
        if m < 1e-9:
            return ux, uy
        return vx / m, vy / m

    def away_dir(self, world):
        """Back away: world.flow.away, or straight away from the player in a dead end."""
        ax, ay = world.flow.away(self.x, self.y)
        if ax == 0.0 and ay == 0.0:
            p = world.player
            ax = self.x - p.x
            ay = self.y - p.y
        return ax, ay

    def turn_to(self, target, dt, rate_deg):
        diff = core.wrap_angle(target - self.angle)
        lim = rate_deg * _D2R * dt
        self.angle = core.wrap_angle(self.angle + core.clamp(diff, -lim, lim))

    def angle_to_player(self, world):
        p = world.player
        return math.atan2(p.y - self.y, p.x - self.x)

    # --- attacks ----------------------------------------------------------------------
    def try_melee(self, world, d):
        if self.MELEE is None:
            return False
        dmg, every, reach = self.MELEE
        if d <= reach and world.now >= self._melee_next and self.can_attack(world):
            self._melee_next = world.now + every
            self.face_player(world)
            self.melee(world, dmg)
            self._attack_until = world.now + 0.15
            return True
        return False

    def shoot(self, world, angle, spec, ability='bolt'):
        """One enemy bolt (4.5): like Enemy.fire_bolt, with its own colour/core/size and ability tag."""
        speed, radius, dmg, ttl, color, core_col, size = spec
        off = self.radius + 0.05
        sx = self.x + math.cos(angle) * off
        sy = self.y + math.sin(angle) * off
        if is_wall(sx, sy):
            sx, sy = self.x, self.y
        pr = Projectile(sx, sy, angle, speed, team=TEAM_ENEMY, damage=dmg * self.dmg_mult, radius=radius,
                        owner=self, ability=ability, ttl=ttl, z=0.45, color=color, core=core_col, size=size)
        ok = world.add_projectile(pr)
        if ok:
            world.bus.emit('sfx', name='enemy_shot', vol=0.6)
        return ok

    def aim(self, world, jitter_deg):
        return self.face_player(world) + world.rng.uniform(-jitter_deg, jitter_deg) * _D2R

    # --- engine hooks ----------------------------------------------------------------
    def update_disabled(self, world, dt):
        self.vstate = 'stun'
        self.on_disabled(world, dt)

    def on_disabled(self, world, dt):
        pass

    def on_death(self, world, source, ability):
        world.burst(self.x, self.y, self.height * 0.5, 10, self.DEBRIS, 2.5, 0.5, 2)


# ============================ TROOPER ========================================
@core.register_enemy
class Trooper(_Robot):
    """Ranged line unit: advance, then hold 4-7 cells and strafe; 0.4 s visor windup, one bolt per 2 s."""
    KIND = 'trooper'
    SCORE = 10
    BASE_HEALTH = 75
    BASE_SPEED = 1.8
    radius = 0.25
    height = 0.70
    width = 0.44
    head_band = (0.00, 0.20)
    MELEE = T['trooper_melee']
    DEBRIS = (110, 190, 110)

    def __init__(self, world, x, y, elite=False):
        super().__init__(world, x, y, elite)
        rng = world.rng
        self.mode = 'advance'
        self._lost_since = None
        self._side = 1 if rng.random() < 0.5 else -1
        self._flip_at = world.now + rng.uniform(*T['trooper_flip'])
        self._fire_next = world.now + T['trooper_first_shot'] + (self.id % 5) * 0.15
        self._windup_left = 0.0

    def update(self, world, dt):
        now = world.now
        p = world.player
        d = self.dist_to_player(world)
        los = self.has_los(world)
        if self.decision_due(world):
            if los:
                self._lost_since = None
                if self.mode == 'advance' and d <= T['trooper_engage']:
                    self.mode = 'hold'
            elif self._lost_since is None:
                self._lost_since = now
            elif now - self._lost_since > T['trooper_los_lost']:
                self.mode = 'advance'
        self.try_melee(world, d)
        # fire cycle: WINDUP 0.4 s (stands still, bright visor), then one bolt
        if self._windup_left > 0.0:
            self._windup_left -= dt
            self.face_player(world)
            self.vstate = 'windup'
            if self._windup_left <= _EPS:
                self._windup_left = 0.0
                if los and self.can_attack(world):
                    self.shoot(world, self.aim(world, T['trooper_jitter_deg']), T['trooper_bolt'])
                    self._attack_until = now + 0.15
            return
        spd, _r, _dm, ttl = T['trooper_bolt'][:4]
        if now >= self._fire_next and los and d <= spd * ttl and self.can_attack(world):
            self._fire_next = now + T['trooper_fire_every']
            self._windup_left = T['trooper_windup']
            self.face_player(world)
            self.vstate = 'windup'
            return
        # movement
        lo, hi = T['trooper_hold']
        if self.mode == 'advance' or d > hi:
            self.move_toward(world, p.x, p.y, dt)
            moving = True
        elif d < T['trooper_backoff']:
            ax, ay = self.away_dir(world)
            moving = self.move_dir(world, ax, ay, dt, face=False) > 1e-4
            self.face_player(world)
        else:
            moving = self.strafe(world, dt, T['trooper_strafe'], T['trooper_flip']) > 1e-4
            self.face_player(world)
        if now < self._attack_until:
            self.vstate = 'attack'
        else:
            self.vstate = 'move' if moving else 'idle'

    def on_disabled(self, world, dt):
        self._windup_left = 0.0


# ============================ SLICER =========================================
@core.register_enemy
class Slicer(_Robot):
    """Fast flanker: zig-zag chase, odd ids flank behind the player, 0.35 s windup then a 9 cells/s lunge."""
    KIND = 'slicer'
    SCORE = 15
    BASE_HEALTH = 40
    BASE_SHIELDS = 40
    BASE_SPEED = 3.4
    radius = 0.22
    height = 0.46
    width = 0.36
    head_band = (0.00, 0.30)
    MELEE = T['slicer_melee']
    DEBRIS = (230, 90, 80)

    def __init__(self, world, x, y, elite=False):
        super().__init__(world, x, y, elite)
        self.mode = 'chase'
        self._t = 0.0
        self._lunge_ready = world.now
        self._dir = (1.0, 0.0)
        self._travel = 0.0
        self._hit_done = False
        self._flank = None
        self._phase = (self.id * 1.7) % _TAU

    def update(self, world, dt):
        now = world.now
        p = world.player
        d = self.dist_to_player(world)
        if self.mode == 'windup':
            self._t -= dt
            self.vstate = 'windup'
            self.angle = math.atan2(self._dir[1], self._dir[0])
            if self._t <= _EPS:
                self.mode = 'lunge'
                self._travel = 0.0
            return
        if self.mode == 'lunge':
            self._lunge(world, dt)
            return
        if self.mode == 'recover':
            self._t -= dt
            self.vstate = 'idle'
            if self._t <= _EPS:
                self.mode = 'chase'
            return
        los = self.has_los(world)
        if self.decision_due(world):
            self._flank = None
            if self.id % 2 == 1 and los and d <= T['slicer_flank_range']:
                fx = p.x - math.cos(p.angle) * T['slicer_flank_behind']
                fy = p.y - math.sin(p.angle) * T['slicer_flank_behind']
                if not is_wall(fx, fy) and world.los_budgeted(p.x, p.y, fx, fy, default=False):
                    self._flank = (fx, fy)
        self.try_melee(world, d)
        if (d <= T['slicer_lunge_range'] and los and now >= self._lunge_ready and self.can_attack(world)):
            self.mode = 'windup'
            self._t = T['slicer_windup']
            self._lunge_ready = now + T['slicer_lunge_cd']
            dx = p.x - self.x
            dy = p.y - self.y
            m = math.hypot(dx, dy) or 1.0
            self._dir = (dx / m, dy / m)
            self._hit_done = False
            self.vstate = 'windup'
            self.angle = math.atan2(dy, dx)
            return
        # chase: flow (+ direct near the player) with a zig-zag weave
        tx, ty = p.x, p.y
        if self._flank is not None and _hypot(self.x, self.y, self._flank[0], self._flank[1]) > 0.4:
            fx, fy = self._flank
            ux = fx - self.x
            uy = fy - self.y
        else:
            ux, uy = self.steer_dir(world, tx, ty)
        m = math.hypot(ux, uy)
        if m < 1e-9:
            self.vstate = 'idle'
            return
        ux /= m
        uy /= m
        z = T['slicer_zig'] * math.sin(_TAU * T['slicer_zig_hz'] * now + self._phase)
        self.move_dir(world, ux - uy * z, uy + ux * z, dt)
        self.vstate = 'lunge' if now < self._attack_until else 'move'

    def _lunge(self, world, dt):
        p = world.player
        self.vstate = 'lunge'
        ux, uy = self._dir
        left = T['slicer_lunge_dist'] - self._travel
        step = min(T['slicer_lunge_speed'] * dt, left)
        done = step <= 1e-6
        if not done:
            nx = self.x + ux * step
            ny = self.y + uy * step
            t = _crosses_player_barrier(world, self.x, self.y, nx, ny)
            if t is not None:                   # 5.6: the lunge stops at the barrier line
                step *= max(0.0, t - 0.05)
                done = True
            moved = self.move_dir(world, ux, uy, 1.0, speed=step) if step > 1e-6 else 0.0
            self._travel += moved
            if moved < step * 0.5:
                done = True                     # a wall
        dp = self.dist_to_player(world)
        if not self._hit_done and dp <= T['slicer_lunge_hit_r'] and self.can_attack(world):
            self._hit_done = True
            enemy_hits_player(world, self, T['slicer_lunge_damage'] * self.dmg_mult, (self.x, self.y), 'lunge')
        if dp <= self.radius + C.PLAYER_RADIUS + 0.06 or self._travel >= T['slicer_lunge_dist'] - 1e-6:
            done = True
        if done:
            self.mode = 'recover'
            self._t = T['slicer_recover']

    def on_disabled(self, world, dt):
        if self.mode != 'chase':
            self.mode = 'chase'


# ============================ DETONATOR ======================================
@core.register_enemy
class Detonator(_Robot):
    """Armored walker: rushes within 4, arms at 1.5 (0.8 s blinking fuse), explodes. Killed by the player it
    chain-detonates 0.25 s later for the player (ability 'chain')."""
    KIND = 'detonator'
    SCORE = 15
    BASE_HEALTH = 100
    BASE_ARMOR = 100
    BASE_SPEED = 1.6
    radius = 0.30
    height = 0.58
    width = 0.56
    head_band = (0.30, 0.55)
    DEBRIS = (255, 160, 60)

    def __init__(self, world, x, y, elite=False):
        super().__init__(world, x, y, elite)
        self.mode = 'walk'
        self._fuse = 0.0
        self._beep = 0.0

    def update(self, world, dt):
        p = world.player
        if self.mode == 'armed':
            self._fuse -= dt
            el = T['det_fuse'] - self._fuse
            self.vstate = 'armed_a' if int(el * T['det_blink_hz'] * 2.0) % 2 == 0 else 'armed_b'
            self.face_player(world)
            self._beep -= dt
            if self._beep <= _EPS:
                self._beep += T['det_beep_every']
                world.bus.emit('sfx', name='beep', vol=0.8)
            if self._fuse <= _EPS:
                self.explode(world)
            return
        d = self.dist_to_player(world)
        if d <= T['det_arm_range'] and self.can_attack(world):
            self.mode = 'armed'
            self._fuse = T['det_fuse']
            self._beep = 0.0
            self.vstate = 'armed_a'
            self.face_player(world)
            return
        los = self.has_los(world)
        if los and d <= T['det_rush_range']:
            self.move_toward(world, p.x, p.y, dt, T['det_rush_speed'] / self.BASE_SPEED)
        else:
            self.move_toward(world, p.x, p.y, dt)
        self.vstate = 'move'

    def explode(self, world):
        """Self-destruct (4.4): dies with no score; 60->30 to the player (LOS, barrier-aware), 120 to enemies."""
        if not self.alive:
            return
        x, y = self.x, self.y
        r = T['det_blast_r']
        dm = self.dmg_mult
        self.remove_silently(world, 0)
        splash(world, x, y, r, T['det_enemy_dmg'] * dm, T['det_enemy_dmg'] * dm, self, TEAM_ENEMY, 'blast',
               exclude=(self,))
        p = world.player
        pd = _hypot(x, y, p.x, p.y)
        if p.alive and pd <= r and world.los(x, y, p.x, p.y):
            hi, lo = T['det_player_dmg']
            enemy_hits_player(world, self, (hi + (lo - hi) * pd / r) * dm, (x, y), 'blast')
        _blast_fx(world, x, y, r, (255, 130, 40), 18)

    def on_death(self, world, source, ability):
        super().on_death(world, source, ability)
        if source is not None and source is world.player:
            fx = _ChainBlast(self, source)
            if not world.add_effect(fx):
                fx.fire(world)

    def on_disabled(self, world, dt):
        if self.mode == 'armed':            # 4.4: a stun during the fuse cancels it
            self.mode = 'walk'
            self._fuse = 0.0

    def emit_visuals(self, scene):
        super().emit_visuals(scene)
        if self.alive and self.mode == 'armed':
            col = (255, 60, 40) if self.vstate == 'armed_a' else (255, 210, 90)
            scene.ring(self.x, self.y, T['det_blast_r'], col, 2, 20)


# ============================ ERADICATOR =====================================
class _EnemyBarrier(Barrier):
    """The Eradicator's shield. owner_view_only makes the renderer skip its default blue segment: the
    Eradicator draws it itself (red-orange with a hit flash and a low-HP tint) in emit_visuals. Gameplay is
    the plain Barrier's."""
    owner_view_only = True


@core.register_enemy
class Eradicator(_Robot):
    """Barrier tank: holds 5-7 cells and strafes, turns at 90 deg/s, deploys a 400-HP barrier for 8 s
    (8 s cooldown), bursts 3 bolts every 3 s."""
    KIND = 'eradicator'
    SCORE = 30
    BASE_HEALTH = 150
    BASE_SHIELDS = 100
    BASE_SPEED = 1.3
    radius = 0.35
    height = 0.80
    width = 0.66
    head_band = (0.00, 0.18)
    MELEE = T['erad_melee']
    DEBRIS = (120, 150, 230)

    def __init__(self, world, x, y, elite=False):
        super().__init__(world, x, y, elite)
        rng = world.rng
        self.mode = 'move'
        self.barrier = _EnemyBarrier(TEAM_ENEMY, T['erad_barrier_hp'] * self.pool_mult, T['erad_barrier_half'],
                                     owner=self, color_add=(80, 30, 18))
        self.bar_state = 'ready'            # 'ready' | 'up' | 'cooldown'
        self._bar_until = 0.0
        self._side = 1 if rng.random() < 0.5 else -1
        self._flip_at = world.now + rng.uniform(*T['erad_flip'])
        self._burst_next = world.now + 1.5 + (self.id % 5) * 0.2
        self._burst_left = 0
        self._shot_next = 0.0

    # --- barrier ----------------------------------------------------------------------
    def _pose_barrier(self):
        a = self.angle
        dd = T['erad_barrier_dist']
        self.barrier.set_pose(self.x + math.cos(a) * dd, self.y + math.sin(a) * dd, a)

    def _deploy(self, world):
        b = self.barrier
        b.hp = b.max_hp
        b.active = True
        self._pose_barrier()
        if world.add_barrier(b):
            self.bar_state = 'up'
            self._bar_until = world.now + T['erad_barrier_up']
            return True
        b.active = False
        return False                        # 3 enemy barriers already: wait (5.6)

    def _lower(self, world):
        world.remove_barrier(self.barrier)
        self.barrier.active = False
        self.bar_state = 'cooldown'
        self._bar_until = world.now + T['erad_barrier_cd']

    def _tick_barrier(self, world):
        now = world.now
        b = self.barrier
        if self.bar_state == 'up':
            if not b.active or now >= self._bar_until:      # broken or timed out: 8 s cooldown
                self._lower(world)
            else:
                self._pose_barrier()
                if b not in world.barriers and not world.add_barrier(b):
                    self._lower(world)
        elif self.bar_state == 'cooldown' and now >= self._bar_until:
            self.bar_state = 'ready'

    # --- AI ---------------------------------------------------------------------------
    def update(self, world, dt):
        now = world.now
        p = world.player
        d = self.dist_to_player(world)
        los = self.has_los(world)
        if self.decision_due(world):
            if los and d <= T['erad_engage']:
                self.mode = 'hold'
            elif not los:
                self.mode = 'move'
            if self.bar_state == 'ready' and los and d <= T['erad_barrier_range']:
                self._deploy(world)
        self.try_melee(world, d)
        # movement (facing is turn-limited separately)
        lo, hi = T['erad_hold']
        mvx = mvy = 0.0
        if self.mode == 'move' or d > hi:
            mvx, mvy = self.steer_dir(world, p.x, p.y)
            moved = self.move_dir(world, mvx, mvy, dt, face=False)
        elif d < lo:
            ax, ay = self.away_dir(world)
            moved = self.move_dir(world, ax, ay, dt, face=False)
        else:
            moved = self.strafe(world, dt, T['erad_strafe'], T['erad_flip'])
        # facing: toward the player in a fight, else along the motion; at most 90 deg/s either way
        if los and d <= T['erad_barrier_range'] + 2.0:
            self.turn_to(self.angle_to_player(world), dt, T['erad_turn_deg'])
        elif mvx or mvy:
            self.turn_to(math.atan2(mvy, mvx), dt, T['erad_turn_deg'])
        self._tick_barrier(world)
        # burst: 3 bolts 0.15 s apart every 3 s, only toward what it faces
        if self._burst_left > 0:
            if now >= self._shot_next - _EPS:
                self._burst_left -= 1
                self._shot_next = now + T['erad_burst_gap']
                if los and self.can_attack(world):
                    a = self.angle_to_player(world) + world.rng.uniform(-1.0, 1.0) * T['erad_jitter_deg'] * _D2R
                    self.shoot(world, a, T['erad_bolt'])
                    self._attack_until = now + 0.12
        elif now >= self._burst_next and los and self.can_attack(world):
            spd, _r, _dm, ttl = T['erad_bolt'][:4]
            off = abs(core.wrap_angle(self.angle_to_player(world) - self.angle))
            if d <= spd * ttl and off <= T['erad_fire_arc_deg'] * _D2R:
                self._burst_next = now + T['erad_burst_every']
                self._burst_left = T['erad_burst_n']
                self._shot_next = now
        if now < self._attack_until or self._burst_left > 0:
            self.vstate = 'attack'
        else:
            self.vstate = 'move' if moved > 1e-4 else 'idle'

    def on_disabled(self, world, dt):
        self._burst_left = 0
        if self.bar_state == 'up':
            world.remove_barrier(self.barrier)          # lowered while stunned/pinned; its timer runs on
            if world.now >= self._bar_until or not self.barrier.active:
                self._lower(world)

    def on_death(self, world, source, ability):
        super().on_death(world, source, ability)
        world.remove_barrier(self.barrier)
        self.barrier.active = False

    def emit_visuals(self, scene):
        super().emit_visuals(scene)
        b = self.barrier
        if self.alive and self.bar_state == 'up' and b.active:
            frac = b.hp / b.max_hp if b.max_hp > 0 else 0.0
            if scene.now - b.last_hit < 0.08:
                col, edge = (150, 70, 40), (255, 240, 200)
            elif frac < 0.3:
                col, edge = (90, 14, 10), (255, 70, 50)
            else:
                col, edge = (80, 30, 18), (255, 140, 70)
            # a barrier brushing past the camera would tint the whole screen: fade it within 1.2 cells
            cx, cy = scene.cam[0], scene.cam[1]
            sx, sy = b.x2 - b.x1, b.y2 - b.y1
            ll = sx * sx + sy * sy
            t = core.clamp(((cx - b.x1) * sx + (cy - b.y1) * sy) / ll, 0.0, 1.0) if ll > 1e-9 else 0.0
            dist = math.hypot(b.x1 + sx * t - cx, b.y1 + sy * t - cy)
            if dist < 1.2:
                k = max(0.25, dist / 1.2)
                col = (int(col[0] * k), int(col[1] * k), int(col[2] * k))
            scene.segment(b.x1, b.y1, b.x2, b.y2, col, z0=0.0, z1=0.95, edge=edge)


# ============================ WARDEN =========================================
@core.register_enemy
class Warden(_Robot):
    """Boss (Bastion-style): RECON bolts, SENTRY mode (0.8 s red windup, 4 s at 10 bolts/s) every 12 s,
    STOMP (0.6 s red floor ring) up close, PHASE 2 at 50% health+armor (+300 shields, 2 slicer summons,
    faster recon fire)."""
    KIND = 'warden'
    SCORE = 150
    BOSS = True
    PINNABLE = False
    STUN_MULT = 0.4
    BASE_HEALTH = 800
    BASE_ARMOR = 600
    BASE_SPEED = 1.1
    radius = 0.45
    height = 1.00
    width = 0.90
    head_band = (0.35, 0.55)
    DEBRIS = (210, 110, 255)

    def __init__(self, world, x, y, elite=False):
        super().__init__(world, x, y, False)        # the boss is never elite (4.3)
        self.mode = 'recon'
        self.phase = 1
        self._t = 0.0
        self._fire_next = world.now + 1.0
        self._sentry_next = world.now + T['ward_sentry_first']
        self._stomp_ready = world.now
        self._acc = 0.0
        self.vstate = 'recon'

    def _check_phase(self, world):
        if self.phase != 1:
            return
        pl = self.pool
        mx = pl.max_health + pl.max_armor
        if pl.dead or mx <= 0 or pl.health + pl.armor > T['ward_phase_at'] * mx:
            return
        self.phase = 2
        pl.add_max_shields(T['ward_phase_shields'] * self.pool_mult)
        n = 0
        for x, y in self._summon_cells(world):
            elite = False
            ch = min(T['elite_per_stage'] * (self.stage - 1), T['elite_max'])
            if ch > 0 and world.rng.random() < ch:
                elite = True
            world.spawn_enemy('slicer', x, y, elite=elite, summon=True)
            n += 1
            if n >= T['ward_summons']:
                break
        world.burst(self.x, self.y, 0.7, 20, (220, 90, 255), 3.0, 0.6, 3)
        world.shake(5, 0.25)
        world.bus.emit('sfx', name='warn', vol=1.0)
        world.bus.emit('boss_phase', enemy=self, phase=2)

    def _summon_cells(self, world):
        lo, hi = T['ward_summon_r']
        taken = [(e.x, e.y) for e in world.enemies if e.alive]
        good = []
        ok = []
        for cx, cy in OPEN_CELLS:
            dd = _hypot(self.x, self.y, cx, cy)
            if not (lo <= dd <= hi):
                continue
            if any((cx - x) ** 2 + (cy - y) ** 2 < 0.36 for x, y in taken):
                continue
            (good if world.los(self.x, self.y, cx, cy) else ok).append((cx, cy))
        world.rng.shuffle(good)
        world.rng.shuffle(ok)
        out = good + ok
        while len(out) < T['ward_summons']:
            out.append((self.x, self.y))
        return out

    def update(self, world, dt):
        self._check_phase(world)
        now = world.now
        p = world.player
        d = self.dist_to_player(world)
        los = self.has_los(world)
        mode = self.mode
        if mode == 'sentry_windup':
            self._t -= dt
            self.face_player(world)
            self.vstate = 'sentry_windup'
            if self._t <= _EPS:
                self.mode = 'sentry'
                self._t = T['ward_sentry_time']
                self._acc = 1.0             # the first bolt leaves on the first sentry frame
            return
        if mode == 'sentry':
            self._t -= dt
            self.face_player(world)
            self.vstate = 'sentry'
            self._acc += T['ward_sentry_rate'] * dt
            while self._acc >= 1.0:
                self._acc -= 1.0
                if los and self.can_attack(world):
                    self.shoot(world, self.aim(world, T['ward_sentry_jitter_deg']), T['ward_sentry_bolt'], 'sentry')
            if self._t <= _EPS:
                self.mode = 'recover'
                self._t = T['ward_sentry_recover']
            return
        if mode == 'stomp_windup':
            self._t -= dt
            self.vstate = 'stomp_windup'
            self.face_player(world)
            if self._t <= _EPS:
                self._stomp(world)
                self.mode = 'recon'
            return
        if mode == 'recover':
            self._t -= dt
            if self._t <= _EPS:
                self.mode = 'recon'
        # triggers
        if d <= T['ward_stomp_range'] and now >= self._stomp_ready and self.can_attack(world):
            self.mode = 'stomp_windup'
            self._t = T['ward_stomp_windup']
            self._stomp_ready = now + T['ward_stomp_cd']
            self.vstate = 'stomp_windup'
            world.bus.emit('sfx', name='warn', vol=1.0)
            return
        if (self.mode == 'recon' and now >= self._sentry_next and los and d <= T['ward_sentry_range']
                and self.can_attack(world)):
            self.mode = 'sentry_windup'
            self._t = T['ward_sentry_windup']
            self._sentry_next = now + T['ward_sentry_every']
            self.vstate = 'sentry_windup'
            world.bus.emit('sfx', name='warn', vol=1.0)
            return
        # recon: walk the flow until within 8 with LOS, then hold
        if not (los and d <= T['ward_hold']):
            self.move_toward(world, p.x, p.y, dt)
        elif los:
            self.face_player(world)
        spd, _r, _dm, ttl = T['ward_recon_bolt'][:4]
        if (self.mode == 'recon' and now >= self._fire_next and los and d <= spd * ttl
                and self.can_attack(world)):
            self._fire_next = now + T['ward_recon_every'][0 if self.phase == 1 else 1]
            self.shoot(world, self.aim(world, T['ward_recon_jitter_deg']), T['ward_recon_bolt'], 'recon')
            self._attack_until = now + 0.2
        self.vstate = 'recon_attack' if now < self._attack_until else 'recon'

    def _stomp(self, world):
        """40 to the player within 3.0, knockback 1.5 and slow 0.6 for 1.5 s; the player's barrier blocks it."""
        now = world.now
        p = world.player
        x, y = self.x, self.y
        r = T['ward_stomp_r']
        world.burst(x, y, 0.1, 18, (200, 170, 140), 3.5, 0.5, 3)
        world.add_effect(_RingFlash(x, y, r, (255, 90, 60), 0.3, 4))
        world.bus.emit('sfx', name='hammer', vol=1.0)
        d = _hypot(x, y, p.x, p.y)
        if d < r + 3.0:
            world.shake(8 if d <= r else 4, 0.25)
        if not p.alive or d > r or p.status.taken_mult(now) <= 0.0:
            return
        dmg = T['ward_stomp_damage'] * self.dmg_mult
        if _crosses_player_barrier(world, x, y, p.x, p.y) is not None:
            enemy_hits_player(world, self, dmg, (x, y), 'stomp')     # the barrier takes it
            return
        if not world.los(x, y, p.x, p.y):
            return
        enemy_hits_player(world, self, dmg, (x, y), 'stomp')
        knockback(world, p, x, y, T['ward_stomp_knock'])
        mag, dur = T['ward_stomp_slow']
        p.status.add('slow', dur, now, mag=mag)

    def update_disabled(self, world, dt):
        self._check_phase(world)
        super().update_disabled(world, dt)

    def on_disabled(self, world, dt):
        if self.mode in ('sentry_windup', 'stomp_windup'):
            self.mode = 'recon'                 # a stun cancels the windup
        elif self.mode == 'sentry':
            self._t -= dt
            if self._t <= _EPS:
                self.mode = 'recover'
                self._t = T['ward_sentry_recover']

    def emit_visuals(self, scene):
        super().emit_visuals(scene)
        if not self.alive:
            return
        if self.mode == 'stomp_windup':
            r = T['ward_stomp_r']
            k = core.clamp(1.0 - self._t / T['ward_stomp_windup'], 0.0, 1.0)
            scene.ring(self.x, self.y, r, (255, 50, 40), 3, 28)
            scene.ring(self.x, self.y, max(0.2, r * k), (255, 150, 90), 2, 24)
        elif self.mode == 'sentry_windup':
            scene.ring(self.x, self.y, 0.9, (255, 60, 40), 2, 16)


# ============================ painters =======================================
def _shade(c, k):
    return (min(255, int(c[0] * k)), min(255, int(c[1] * k)), min(255, int(c[2] * k)))


_HOT = ('windup', 'sentry_windup', 'stomp_windup', 'armed_a')
_FIRE = ('attack', 'lunge', 'recon_attack', 'sentry', 'armed_b')


def _paint_image(surf, img, state, elite):
    """PNG theme: the image fitted to the base rect (bottom-centred) plus state overlays."""
    w, h = surf.get_size()
    iw, ih = img.get_size()
    k = min(w / max(1, iw), h / max(1, ih))
    fw = max(1, int(iw * k))
    fh = max(1, int(ih * k))
    fit = img if (fw, fh) == (iw, ih) else pygame.transform.smoothscale(img, (fw, fh))
    x0 = (w - fw) // 2
    y0 = h - fh
    surf.blit(fit, (x0, y0))
    if state == 'stun':
        surf.fill((110, 110, 110), special_flags=pygame.BLEND_RGB_MULT)
    elif state in _HOT:
        pygame.draw.circle(surf, (255, 60, 40), (w // 2, y0 + fh // 5), max(4, fw // 5), 3)
        surf.fill((60, 0, 0), special_flags=pygame.BLEND_RGB_ADD)
    elif state in _FIRE:
        pygame.draw.circle(surf, (255, 230, 150), (w // 2, y0 + fh // 5), max(3, fw // 8))
    if elite:
        pygame.draw.rect(surf, C.COL_ELITE, (x0, y0, fw, fh), 2, border_radius=4)


def _painter(kind, draw_fn):
    def fn(surf, state, elite):
        img = theme.enemy_image(kind, surf.get_height())
        if img is not None:
            _paint_image(surf, img, state, elite)
        else:
            draw_fn(surf, state, elite)
    return fn


def _paint_trooper(surf, state, elite):
    """Green humanoid (the original robot look): visor in the top 20% crit band, rifle at the chest."""
    stun = state == 'stun'
    k = 0.5 if stun else 1.0
    body = _shade((78, 150, 88), k)
    dark = _shade((40, 82, 46), k)
    trim = C.COL_ELITE if elite else _shade((110, 200, 110), k)
    visor = {'windup': (255, 255, 200), 'attack': (255, 110, 70), 'stun': (70, 70, 70)}.get(state, (180, 255, 80))
    rect, poly = pygame.draw.rect, pygame.draw.polygon
    if state == 'move':
        poly(surf, dark, ((22, 58), (34, 58), (26, 96), (12, 96)))
        poly(surf, dark, ((42, 58), (54, 58), (64, 96), (50, 96)))
    else:
        surf.fill(dark, (22, 58, 13, 38))
        surf.fill(dark, (41, 58, 13, 38))
    torso = ((12, 21), (64, 21), (56, 60), (20, 60))
    poly(surf, body, torso)
    rect(surf, trim, (6, 19, 15, 11), border_radius=3)
    rect(surf, trim, (55, 19, 15, 11), border_radius=3)
    rect(surf, _shade(body, 1.25), (27, 27, 22, 10), border_radius=2)
    head = (22, 0, 32, 19)
    rect(surf, body, head, border_radius=6)
    surf.fill(visor, (25, 7, 26, 5))
    rect(surf, (38, 42, 50), (34, 38, 38, 8), border_radius=2)
    if state == 'windup':
        pygame.draw.circle(surf, (255, 230, 120), (70, 42), 7, 2)
    elif state == 'attack':
        pygame.draw.circle(surf, (255, 235, 150), (71, 42), 5)
    if elite:
        poly(surf, C.COL_ELITE, torso, 2)
        rect(surf, C.COL_ELITE, head, 2, border_radius=6)


def _paint_slicer(surf, state, elite):
    """Low red mantis: wedge head with one slit eye in the top 30%, two blade arms, thin legs."""
    stun = state == 'stun'
    k = 0.5 if stun else 1.0
    body = _shade((205, 58, 58), k)
    dark = _shade((110, 30, 34), k)
    blade = C.COL_ELITE if elite else _shade((235, 225, 225), k)
    eye = {'windup': (255, 30, 20), 'lunge': (255, 120, 70), 'stun': (70, 70, 70)}.get(state, (255, 205, 110))
    c = 6 if state == 'windup' else 0
    poly, line = pygame.draw.polygon, pygame.draw.line
    kl = kr = 12 if state == 'windup' else 6
    fl, fr = 26, 54
    if state == 'move':
        kl, kr, fl, fr = 11, 2, 16, 58
    line(surf, dark, (32, 46 + c), (32 - kl, 64), 5)
    line(surf, dark, (32 - kl, 64), (fl, 79), 5)
    line(surf, dark, (48, 46 + c), (48 + kr, 64), 5)
    line(surf, dark, (48 + kr, 64), (fr, 79), 5)
    if state == 'windup':
        tips = ((6, 0), (74, 0))
    elif state == 'lunge':
        tips = ((0, 34), (80, 34))
    else:
        tips = ((4, 8), (76, 8))
    edge = _shade(blade, 0.6) if not elite else (0, 140, 170)
    for sx, tip in ((26, tips[0]), (54, tips[1])):
        line(surf, edge, (sx, 31 + c), tip, 7)
        line(surf, blade, (sx, 31 + c), tip, 3)
    body_r = (20, 20 + c, 40, 30)
    pygame.draw.ellipse(surf, body, body_r)
    head = ((28, 1 + c), (52, 1 + c), (57, 13 + c), (40, 23 + c), (23, 13 + c))
    poly(surf, body, head)
    surf.fill(eye, (30, 8 + c, 20, 4))
    if state == 'lunge':
        for yy in (22, 30, 38):
            line(surf, (255, 150, 140), (2, yy), (16, yy), 2)
            line(surf, (255, 150, 140), (64, yy), (78, yy), 2)
    if elite:
        pygame.draw.ellipse(surf, C.COL_ELITE, body_r, 2)
        poly(surf, C.COL_ELITE, head, 2)


def _paint_detonator(surf, state, elite):
    """Squat orange walker with armour plates and a glowing core in its 30-55% crit band."""
    stun = state == 'stun'
    k = 0.5 if stun else 1.0
    body = _shade((225, 128, 40), k)
    dark = _shade((120, 62, 26), k)
    plate = _shade(C.COL_ARMOR, 0.85 * k)
    if state == 'armed_a':
        core_c, ring_c = (255, 255, 225), (255, 50, 30)
    elif state == 'armed_b':
        core_c, ring_c = (255, 40, 20), (255, 230, 150)
    else:
        core_c, ring_c = _shade((255, 200, 80), k), dark
    rect = pygame.draw.rect
    for n, x0 in enumerate((12, 32, 56, 72)):
        lift = 4 if state == 'move' and n % 2 else 0
        surf.fill(dark, (x0, 62 - lift, 14, 18))
    shell = (6, 10, 86, 54)
    rect(surf, body, shell, border_radius=16)
    pygame.draw.ellipse(surf, dark, (24, 0, 50, 22))
    rect(surf, plate, (6, 48, 86, 9), border_radius=4)
    rect(surf, plate, (14, 14, 18, 30), border_radius=4)
    rect(surf, plate, (66, 14, 18, 30), border_radius=4)
    pygame.draw.circle(surf, (40, 22, 12), (49, 34), 13)
    pygame.draw.circle(surf, core_c, (49, 34), 9)
    pygame.draw.circle(surf, ring_c, (49, 34), 16, 3)
    if elite:
        rect(surf, C.COL_ELITE, shell, 2, border_radius=16)
        pygame.draw.ellipse(surf, C.COL_ELITE, (24, 0, 50, 22), 2)


def _paint_eradicator(surf, state, elite):
    """Tall steel-blue tank: small head in the top 18%, heavy shoulders, shield projector, arm cannon."""
    stun = state == 'stun'
    k = 0.5 if stun else 1.0
    body = _shade((88, 108, 196), k)
    dark = _shade((44, 54, 104), k)
    glow = _shade((140, 205, 255), k)
    visor = {'attack': (255, 160, 70), 'stun': (70, 70, 70)}.get(state, (150, 230, 255))
    rect, poly = pygame.draw.rect, pygame.draw.polygon
    if state == 'move':
        poly(surf, dark, ((34, 74), (53, 74), (44, 112), (22, 112)))
        poly(surf, dark, ((65, 74), (84, 74), (96, 112), (74, 112)))
    else:
        surf.fill(dark, (34, 74, 19, 38))
        surf.fill(dark, (65, 74, 19, 38))
    torso = ((22, 28), (96, 28), (86, 76), (32, 76))
    poly(surf, body, torso)
    shoulders = (4, 16, 110, 18)
    rect(surf, dark, shoulders, border_radius=7)
    rect(surf, dark, (0, 30, 20, 44), border_radius=5)
    surf.fill(glow, (6, 36, 8, 32))
    rect(surf, (36, 40, 52), (98, 32, 20, 36), border_radius=4)
    pygame.draw.circle(surf, glow, (59, 48), 8)
    rect(surf, body, (45, 0, 28, 19), border_radius=5)
    surf.fill(visor, (48, 7, 22, 4))
    if state == 'attack':
        pygame.draw.circle(surf, (255, 200, 110), (108, 72), 8)
    if elite:
        poly(surf, C.COL_ELITE, torso, 2)
        rect(surf, C.COL_ELITE, shoulders, 2, border_radius=7)


def _paint_warden(surf, state, elite):
    """Purple boss mech (the original boss colours): sensor bar on top, glowing core in its 35-55% crit band.
    recon = walker; sentry = hunkered turret with a gatling on top; windups glow red."""
    stun = state == 'stun'
    k = 0.5 if stun else 1.0
    body = _shade((150, 62, 196), k)
    dark = _shade((84, 26, 112), k)
    plate = _shade(C.COL_ARMOR, 0.8 * k)
    hot = state in ('sentry_windup', 'stomp_windup')
    red = (255, 50, 40)
    core_c = {'sentry': (255, 225, 70), 'sentry_windup': red, 'stomp_windup': red,
              'stun': (90, 60, 100)}.get(state, (255, 110, 255))
    eye = red if hot else ((70, 70, 70) if stun else (255, 150, 255))
    rect, poly = pygame.draw.rect, pygame.draw.polygon
    cx, cy = 73, 57
    if state in ('sentry', 'sentry_windup'):
        poly(surf, dark, ((20, 96), (46, 96), (30, 128), (0, 128)))
        poly(surf, dark, ((100, 96), (126, 96), (146, 128), (116, 128)))
        shell = (18, 30, 110, 70)
        rect(surf, red if hot else body, shell, border_radius=14)
        rect(surf, body, (24, 36, 98, 58), border_radius=12)
        rect(surf, (40, 34, 50), (48, 2, 50, 28), border_radius=5)
        for bx in (54, 67, 80):
            surf.fill((255, 235, 120) if state == 'sentry' else (90, 80, 100), (bx, 0, 8, 12))
    else:
        if state == 'stomp_windup':
            poly(surf, red, ((38, 80), (62, 80), (58, 104), (30, 108)))
        else:
            poly(surf, dark, ((38, 80), (62, 80), (52, 128), (24, 128)))
        poly(surf, dark, ((84, 80), (108, 80), (122, 128), (94, 128)))
        shell = (26, 16, 94, 66)
        rect(surf, red if hot else body, shell, border_radius=12)
        rect(surf, body, (30, 20, 86, 58), border_radius=10)
        rect(surf, dark, (116, 34, 28, 20), border_radius=4)
        surf.fill(_shade(dark, 0.8), (122, 54, 12, 28))
        rect(surf, dark, (2, 34, 26, 32), border_radius=5)
        rect(surf, dark, (48, 0, 50, 17), border_radius=5)
        surf.fill(eye, (54, 6, 38, 5))
        if state == 'recon_attack':
            pygame.draw.circle(surf, (255, 170, 255), (128, 86), 9)
    surf.fill(plate, (34, 24, 22, 8))
    surf.fill(plate, (90, 24, 22, 8))
    pygame.draw.circle(surf, (36, 14, 48), (cx, cy), 15)
    pygame.draw.circle(surf, core_c, (cx, cy), 10)
    if elite:
        rect(surf, C.COL_ELITE, shell, 2, border_radius=12)


# Base sizes keep the on-screen aspect (width/height x 1.27, see the module docstring).
register_painter('trooper', _painter('trooper', _paint_trooper), 76, 96)
register_painter('slicer', _painter('slicer', _paint_slicer), 80, 80)
register_painter('detonator', _painter('detonator', _paint_detonator), 98, 80)
register_painter('eradicator', _painter('eradicator', _paint_eradicator), 118, 112)
register_painter('warden', _painter('warden', _paint_warden), 146, 128)
