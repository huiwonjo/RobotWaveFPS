"""Damage pipeline, pools, statuses, hitscan, projectiles, barriers, effects (spec 5, 7.4)."""
import itertools
import math

from . import config as C
from . import core
from . import theme
from .config import (EYE_Z, HIT_PAD, MAX_DEPTH, TEAM_ENEMY, TEAM_PLAYER, ARMOR_REDUCTION,
                     FLAG_FLASH, FLAG_STUN, FLAG_DYING)
from .world import cast_ray, is_wall, los, move_slide


# ============================ pools ==========================================
class HealthPool:
    """health / armor / shields. absorb() order: shields -> armor (flat 30% off) -> health."""

    def __init__(self, health, armor=0.0, shields=0.0):
        self.max_health = float(health)
        self.health = float(health)
        self.max_armor = float(armor)
        self.armor = float(armor)
        self.max_shields = float(shields)
        self.shields = float(shields)
        self.last_damage = -99.0

    @property
    def total(self):
        return self.health + self.armor + self.shields

    @property
    def max_total(self):
        return self.max_health + self.max_armor + self.max_shields

    @property
    def dead(self):
        return self.health <= 1e-6

    def absorb(self, amount, now):
        self.last_damage = now
        dealt = 0.0
        r = float(amount)
        if self.shields > 0:
            a = min(self.shields, r)
            self.shields -= a
            r -= a
            dealt += a
        if r > 0 and self.armor > 0:
            eff = r * (1 - ARMOR_REDUCTION)
            a = min(self.armor, eff)
            self.armor -= a
            dealt += a
            r -= a / (1 - ARMOR_REDUCTION)
        if r > 1e-9 and self.health > 0:
            a = min(self.health, r)
            self.health -= a
            dealt += a
        return dealt

    def heal(self, amount):
        if amount <= 0:
            return 0.0
        r = float(amount)
        a = min(r, self.max_health - self.health)
        a = max(0.0, a)
        self.health += a
        r -= a
        b = max(0.0, min(r, self.max_armor - self.armor))
        self.armor += b
        return a + b

    def update(self, dt, now):
        if self.shields < self.max_shields and now - self.last_damage >= C.SHIELD_REGEN_DELAY:
            self.shields = min(self.max_shields, self.shields + C.SHIELD_REGEN_RATE * dt)

    def add_max_shields(self, n):
        self.max_shields += n
        self.shields += n

    def scale(self, mult):
        self.max_health *= mult
        self.health *= mult
        self.max_armor *= mult
        self.armor *= mult
        self.max_shields *= mult
        self.shields *= mult

    def refill(self):
        self.health = self.max_health
        self.armor = self.max_armor
        self.shields = self.max_shields

    def segments(self):
        return [('health', self.health, self.max_health), ('armor', self.armor, self.max_armor),
                ('shields', self.shields, self.max_shields)]


# ============================ statuses =======================================
class StatusSet:
    """stun / pinned / slow / root / invuln with sim-clock expiry (spec 5.7)."""

    def __init__(self):
        self._until = {}        # kind -> expiry (sim time)
        self._mag = {}          # kind -> magnitude (non-slow kinds)
        self._slows = []        # [(until, mag)]

    def add(self, kind, duration, now, mag=1.0):
        until = now + duration
        if kind == 'slow':
            self._slows = [s for s in self._slows if s[0] > now]
            self._slows.append((until, mag))
        self._until[kind] = max(self._until.get(kind, -1.0), until)
        self._mag[kind] = mag

    def has(self, kind, now):
        u = self._until.get(kind)
        return u is not None and u > now

    def left(self, kind, now):
        u = self._until.get(kind)
        return max(0.0, u - now) if u is not None else 0.0

    def speed_mult(self, now):
        if not self._slows:
            return 1.0
        m = 1.0
        for until, mag in self._slows:
            if until > now and mag < m:
                m = mag
        return m

    def can_act(self, now):
        if not self._until:
            return True
        return not (self.has('stun', now) or self.has('pinned', now))

    def can_move(self, now):
        if not self._until:
            return True
        return not (self.has('stun', now) or self.has('pinned', now) or self.has('root', now))

    def taken_mult(self, now):
        return 0.0 if self.has('invuln', now) else 1.0

    def active(self, now):
        return [k for k, u in self._until.items() if u > now]

    def remove(self, kind):
        self._until.pop(kind, None)
        self._mag.pop(kind, None)
        if kind == 'slow':
            self._slows = []

    def clear(self):
        self._until.clear()
        self._mag.clear()
        self._slows = []


# ============================ entities =======================================
_ids = itertools.count(1)


class Entity:
    team = TEAM_ENEMY
    radius = 0.25
    height = 0.70
    width = 0.44
    z0 = 0.0
    head_band = (0.0, 0.2)
    height_mult = 1.0
    alive = True
    dying_until = 0.0
    last_hit = -9.0
    knockback_immune = False
    NAME = '?'

    def __init__(self):
        self.id = next(_ids)
        self.x = 0.0
        self.y = 0.0
        self.angle = 0.0
        self.pool = HealthPool(100)
        self.status = StatusSet()

    def on_damaged(self, world, amount, source, crit, ability):
        pass

    def on_death(self, world, source, ability):
        pass


class Enemy(Entity):
    """Base for every enemy kind. Subclasses set KIND, SCORE, BASE_*, radius/height/width/head_band.

    Helpers for AI code: decision_due(world) (0.2 s staggered tick), has_los(world)
    (LOS to the PLAYER, budgeted, re-checked at most 5x/s), can_attack(world), face_player(world),
    move_toward, move_dir, fire_bolt, melee, dist_to_player, remove_silently.

    Damage scaling: fire_bolt() and melee() take the STAGE-1 damage and multiply by dmg_mult inside.
    enemy_hits_player(), splash() and apply_damage() do NOT scale: pass `base * self.dmg_mult` yourself
    (detonator blast, warden stomp, slicer lunge ...), and don't scale twice.
    Credit: pass the enemy itself as `source` for damage it does to other enemies (detonator blast):
    it gets no credit or score (only source is world.player does), and the kill event's killer is then
    theme.enemy_name(KIND) instead of ''.
    Barriers: a barrier whose owner is dead or dying is dropped by World.update (step 9), so an enemy
    removed with remove_silently() never leaves its barrier behind.
    """
    KIND = 'enemy'
    SCORE = 0
    BOSS = False
    PINNABLE = True
    STUN_MULT = 1.0
    BASE_HEALTH = 0
    BASE_ARMOR = 0
    BASE_SHIELDS = 0
    BASE_SPEED = 0.0
    vstate = 'idle'

    def __init__(self, world, x, y, elite=False):
        super().__init__()
        self.team = TEAM_ENEMY
        self.x = float(x)
        self.y = float(y)
        p = world.player
        self.angle = math.atan2(p.y - self.y, p.x - self.x) if p is not None else 0.0
        stage = max(1, int(world.stage))
        k = stage - 1
        self.stage = stage
        self.elite = bool(elite)
        pm = (1.0 + 0.15 * k) * (1.6 if self.elite else 1.0)
        self.pool = HealthPool(self.BASE_HEALTH * pm, self.BASE_ARMOR * pm, self.BASE_SHIELDS * pm)
        self.speed = self.BASE_SPEED * min(1.0 + 0.05 * k, 1.3) * (1.2 if self.elite else 1.0)
        self.dmg_mult = 1.0 + 0.15 * k
        self.summoned = False
        self.vstate = 'idle'
        self.NAME = theme.enemy_name(self.KIND)
        self.knockback_immune = bool(self.BOSS)
        phase = (self.id % 5) * 0.04
        self._next_decide = world.now + phase
        self._los = False
        self._los_next = world.now + phase

    # --- AI hooks (ENEMIES overrides) -------------------------------------------
    def update(self, world, dt):
        pass

    def update_disabled(self, world, dt):
        pass

    def emit_visuals(self, scene):
        now = scene.now
        flags = 0
        if now - self.last_hit < 0.06:
            flags |= FLAG_FLASH
        if self.status.has('stun', now):
            flags |= FLAG_STUN
        if not self.alive:
            flags |= FLAG_DYING
        scene.sprite(self.x, self.y, self.KIND, self.vstate, self.height * self.height_mult, self.width,
                     z0=self.z0, flags=flags, elite=self.elite, ref=self.id)

    # --- helpers ------------------------------------------------------------------
    def decision_due(self, world):
        now = world.now
        if now >= self._next_decide:
            self._next_decide = now + 0.2
            return True
        return False

    def has_los(self, world):
        now = world.now
        if now >= self._los_next and world.los_used < C.CAP_LOS_PER_FRAME:
            self._los_next = now + 0.2
            p = world.player
            self._los = world.los_budgeted(self.x, self.y, p.x, p.y, default=self._los)
        return self._los

    def can_attack(self, world):
        p = world.player
        return p.alive and not p.status.has('invuln', world.now)

    def face_player(self, world):
        p = world.player
        self.angle = math.atan2(p.y - self.y, p.x - self.x)
        return self.angle

    def dist_to_player(self, world):
        p = world.player
        return math.hypot(p.x - self.x, p.y - self.y)

    def move_toward(self, world, tx, ty, dt, speed_mult=1.0):
        """Spec 4.4 "normal movement" toward the PLAYER: world.flow.toward(), blended with direct
        steering toward (tx, ty) only while has_los() (LOS to the player) and (tx, ty) is within 3 cells
        (full direct steering within 1.5). Farther out, or without LOS, it follows the flow field, and
        the flow field always leads to the player's cell, whatever (tx, ty) is. So pass the player's
        position (or a point near it). For any other motion (strafing, backing away along flow.away,
        a flank point, a lunge, holding a range) use move_dir()."""
        now = world.now
        st = self.status
        if not st.can_move(now):
            return
        step = self.speed * speed_mult * st.speed_mult(now) * dt
        if step <= 0.0:
            return
        dx = tx - self.x
        dy = ty - self.y
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return
        ux = dx / d
        uy = dy / d
        fx, fy = world.flow.toward(self.x, self.y)
        if fx == 0.0 and fy == 0.0:
            w = 1.0
        elif d < 3.0 and self.has_los(world):
            w = core.clamp((3.0 - d) / 1.5, 0.0, 1.0)
        else:
            w = 0.0
        vx = fx * (1.0 - w) + ux * w
        vy = fy * (1.0 - w) + uy * w
        m = math.hypot(vx, vy)
        if m < 1e-9:
            vx, vy, m = ux, uy, 1.0
        vx /= m
        vy /= m
        if step > d and w >= 1.0:
            step = d
        self.x, self.y = move_slide(self.x, self.y, vx * step, vy * step, self.radius)
        self.angle = math.atan2(vy, vx)

    def move_dir(self, world, ux, uy, dt, speed_mult=1.0, *, speed=None, face=True):
        """Walk along direction (ux, uy) (any length; normalised here) with wall sliding, honouring
        root/stun/pinned and slows. Speed is self.speed x speed_mult, or `speed` cells/s when given
        (e.g. a 9 cells/s lunge). face=True turns toward the motion. Returns the distance moved."""
        now = world.now
        st = self.status
        if not st.can_move(now):
            return 0.0
        m = math.hypot(ux, uy)
        if m < 1e-9:
            return 0.0
        base = self.speed * speed_mult if speed is None else float(speed)
        step = base * st.speed_mult(now) * dt
        if step <= 0.0:
            return 0.0
        ox, oy = self.x, self.y
        self.x, self.y = move_slide(ox, oy, ux / m * step, uy / m * step, self.radius)
        if face:
            self.angle = math.atan2(uy, ux)
        return math.hypot(self.x - ox, self.y - oy)

    def fire_bolt(self, world, angle, speed, damage, radius=0.12, color=(255, 70, 50), ttl=1.25, *,
                  ability='bolt', core=(255, 255, 255), size=0.08, z=0.45):
        """One enemy bolt from just in front of the body. `damage` is the stage-1 number (x dmg_mult here).
        ability tags the bolt ('bolt', 'recon', 'sentry' ...: player_hurt / kill labels); core and size
        are the orb's look."""
        off = self.radius + 0.05
        sx = self.x + math.cos(angle) * off
        sy = self.y + math.sin(angle) * off
        if is_wall(sx, sy):
            sx, sy = self.x, self.y
        p = Projectile(sx, sy, angle, speed, team=TEAM_ENEMY, damage=damage * self.dmg_mult,
                       radius=radius, owner=self, ability=ability, ttl=ttl, z=z, color=color, core=core,
                       size=size)
        ok = world.add_projectile(p)
        if ok:
            world.bus.emit('sfx', name='enemy_shot', vol=0.6)
        return ok

    def melee(self, world, damage, ability='melee'):
        return enemy_hits_player(world, self, damage * self.dmg_mult, (self.x, self.y), ability)

    def remove_silently(self, world, particles=8):
        """Die with no score, no credit and no kill event (capture self-destruct, debug kill)."""
        if not self.alive:
            return
        self.alive = False
        self.dying_until = world.now + 0.3
        if particles:
            world.burst(self.x, self.y, self.height * 0.5, particles, (255, 160, 80), 2.0, 0.4, 2)


@core.register_enemy
class Dummy(Enemy):
    """Test target; never spawned by waves. fire_every (s or None) and bolt_damage are settable."""
    KIND = 'dummy'
    SCORE = 0
    BASE_HEALTH = 1000
    BASE_SPEED = 0.0
    radius = 0.30
    height = 0.70
    width = 0.44
    head_band = (0.0, 0.2)

    def __init__(self, world, x, y, elite=False):
        super().__init__(world, x, y, elite)
        self.fire_every = None
        self.bolt_damage = 10.0
        self._fire_left = 0.0

    def update(self, world, dt):
        if not self.fire_every:
            return
        self._fire_left -= dt
        if self._fire_left <= 0.0:
            self._fire_left += self.fire_every
            if self._fire_left <= 0.0:
                self._fire_left = self.fire_every
            p = world.player
            if self.can_attack(world) and los(self.x, self.y, p.x, p.y):
                self.fire_bolt(world, self.face_player(world), 8.0, self.bolt_damage)


# ============================ hitscan ========================================
class Hit:
    __slots__ = ('kind', 'target', 'dist', 'x', 'y', 'z', 'crit')

    def __init__(self, kind, target, dist, x, y, z, crit):
        self.kind = kind
        self.target = target
        self.dist = dist
        self.x = x
        self.y = y
        self.z = z
        self.crit = crit

    def __repr__(self):
        return 'Hit(%s, d=%.2f, crit=%s)' % (self.kind, self.dist, self.crit)


def hitscan(world, shooter, angle, pitch, max_range=MAX_DEPTH):
    sx, sy = shooter.x, shooter.y
    c = math.cos(angle)
    s = math.sin(angle)
    wall_d = cast_ray(sx, sy, angle)[0]
    if wall_d <= max_range:
        best, kind = wall_d, 'wall'
    else:
        best, kind = float(max_range), 'none'
    target = None
    crit = False
    team = shooter.team
    for b in world.barriers:
        if not b.active or b.team == team:
            continue
        t = b.intersects(sx, sy, sx + c * best, sy + s * best)
        if t is not None and t * best < best:
            best = t * best
            kind = 'barrier'
            target = b
    cands = world.enemies if team == TEAM_PLAYER else (world.player,)
    kz = pitch / 768.0
    for e in cands:
        if not e.alive:
            continue
        dx = e.x - sx
        dy = e.y - sy
        proj = dx * c + dy * s
        if proj <= 0.1 or proj >= best:
            continue
        if abs(dx * s - dy * c) > e.width * 0.5 + HIT_PAD:
            continue
        z_aim = EYE_Z + kz * proj
        h = e.height * e.height_mult
        z0 = e.z0
        if z0 - 0.03 <= z_aim <= z0 + h + 0.03:
            best = proj
            kind = 'enemy'
            target = e
            v0, v1 = e.head_band
            crit = z0 + h * (1 - v1) <= z_aim <= z0 + h * (1 - v0)
    if kind != 'enemy':
        crit = False
    return Hit(kind, target, best, sx + c * best, sy + s * best, EYE_Z + kz * best, crit)


# ============================ damage ==========================================
def _is_hero(ent):
    return ent is not None and hasattr(ent, 'ult_active_left')


def apply_damage(world, target, amount, source=None, *, ability='primary', crit=False, from_xy=None):
    """The one way HP goes down (spec 5.2). Crit x2 is applied by the CALLER. Returns damage dealt.

    'kill' is emitted for EVERY death, the player's included (then target is world.player, name is the
    hero NAME and killer the enemy's display name): kill feeds, pop-ups, stats and POTG must skip
    `d['target'] is world.player`. killer is the hero NAME for player kills, theme.enemy_name(KIND) when
    source is an enemy, and '' when source is None. label is source.label_for(ability) when the source
    has one (heroes), else ability.upper().
    """
    if target is None or not target.alive or amount <= 0:
        return 0.0
    now = world.now
    if target.status.taken_mult(now) == 0:
        return 0.0
    player = world.player
    to_player = target is player
    if from_xy is None and source is not None and hasattr(source, 'x'):
        from_xy = (source.x, source.y)
    fx, fy = from_xy if from_xy is not None else (None, None)
    bus = world.bus
    if to_player and world.debug.get('god'):
        bus.emit('player_hurt', amount=float(amount), from_x=fx, from_y=fy, ability=ability)
        return 0.0
    dealt = target.pool.absorb(amount, now)
    target.last_hit = now
    target.on_damaged(world, dealt, source, crit, ability)
    if source is not None and source is player and not to_player:
        source.add_ult(dealt)
    killed = target.pool.dead
    bus.emit('damage', target=target, source=source, amount=dealt, raw=float(amount), crit=bool(crit),
             ability=ability, killed=killed, x=target.x, y=target.y, to_player=to_player)
    if to_player:
        bus.emit('player_hurt', amount=dealt, from_x=fx, from_y=fy, ability=ability)
    if killed and target.alive:
        target.alive = False
        target.dying_until = now + 0.3
        target.on_death(world, source, ability)
        credited = source is not None and source is player
        score = 0
        if credited and isinstance(target, Enemy):
            st = max(1, int(world.stage))
            score = target.SCORE * (2 if target.elite else 1) * st
            if crit:
                score += 5 * st
            world.score += score
        if source is None:
            killer = ''
        elif _is_hero(source):
            killer = source.NAME
        elif hasattr(source, 'KIND'):
            killer = theme.enemy_name(source.KIND)
        else:
            killer = getattr(source, 'NAME', '')
        label_for = getattr(source, 'label_for', None)
        label = label_for(ability) if label_for is not None else str(ability).upper()
        ult = ability == 'ult' or (_is_hero(source) and source.ult_active_left > 0)
        bus.emit('kill', target=target, name=getattr(target, 'NAME', '?'), source=source, killer=killer,
                 ability=ability, label=label, crit=bool(crit), score=score,
                 boss=bool(getattr(target, 'BOSS', False)), ult=bool(ult), x=target.x, y=target.y)
    return dealt


def player_barrier_between(world, ax, ay, bx, by):
    """(t, barrier) for the nearest active player-team barrier crossing the segment a->b (t in [0, 1]
    along it), or None. Enemy code uses it to tell "blocked by the barrier" apart from god mode (both make
    enemy_hits_player return 0) and to stop motion at the barrier line (slicer lunge)."""
    best = None
    for b in world.barriers:
        if b.active and b.team == TEAM_PLAYER:
            t = b.intersects(ax, ay, bx, by)
            if t is not None and (best is None or t < best[0]):
                best = (t, b)
    return best


def enemy_hits_player(world, source, amount, from_xy, ability='melee'):
    """Melee / area damage from an enemy: an active player barrier across the path absorbs it."""
    p = world.player
    if from_xy is None:
        from_xy = (source.x, source.y) if source is not None else (p.x, p.y)
    fx, fy = from_xy
    blk = player_barrier_between(world, fx, fy, p.x, p.y)
    if blk is not None:
        blk[1].take(world, amount, source)
        return 0.0
    return apply_damage(world, p, amount, source, ability=ability, from_xy=from_xy)


def heal(world, target, amount, source=None, ability=''):
    """Heals health then armor; emits 'heal'. Never adds ult (the ability code does that)."""
    if target is None or not target.alive or amount <= 0:
        return 0.0
    healed = target.pool.heal(amount)
    if healed > 0:
        world.bus.emit('heal', target=target, amount=healed, source=source, ability=ability)
    return healed


def splash(world, x, y, radius, dmg_center, dmg_edge, source, team, ability, *, exclude=(),
           ignore_barriers=False, hit_player=False):
    """Linear falloff area damage to alive enemies (and the player if hit_player). Needs LOS."""
    hit = []
    r2 = radius * radius
    targets = [e for e in world.enemies if e.alive and e not in exclude]
    p = world.player
    if hit_player and p.alive and p not in exclude:
        targets.append(p)
    for t in targets:
        dx = t.x - x
        dy = t.y - y
        d2 = dx * dx + dy * dy
        if d2 > r2:
            continue
        if not los(x, y, t.x, t.y):
            continue
        d = math.sqrt(d2)
        dmg = dmg_center + (dmg_edge - dmg_center) * min(1.0, d / radius if radius > 0 else 1.0)
        if t is p:
            if team == TEAM_ENEMY:
                enemy_hits_player(world, source, dmg, (x, y), ability)
            else:
                apply_damage(world, p, dmg, source, ability=ability, from_xy=(x, y))
            hit.append(t)
            continue
        if not ignore_barriers:
            blocked = False
            for b in world.barriers:
                if b.active and b.team == t.team and b.intersects(x, y, t.x, t.y) is not None:
                    blocked = True
                    break
            if blocked:
                continue
        apply_damage(world, t, dmg, source, ability=ability, from_xy=(x, y))
        hit.append(t)
    world.bus.emit('explosion', x=x, y=y, radius=radius, team=team)
    return hit


def knockback(world, ent, from_x, from_y, dist):
    if dist <= 0 or getattr(ent, 'knockback_immune', False) or getattr(ent, 'BOSS', False):
        return
    dx = ent.x - from_x
    dy = ent.y - from_y
    d = math.hypot(dx, dy)
    if d < 1e-6:
        ux, uy = -math.cos(ent.angle), -math.sin(ent.angle)
    else:
        ux, uy = dx / d, dy / d
    step = dist / 4.0
    for _ in range(4):
        ent.x, ent.y = move_slide(ent.x, ent.y, ux * step, uy * step, ent.radius)


def cone_targets(world, x, y, angle, half_angle_rad, reach, need_los=True):
    """Alive enemies whose (centre distance - radius) <= reach inside +-half_angle, nearest first."""
    out = []
    for e in world.enemies:
        if not e.alive:
            continue
        dx = e.x - x
        dy = e.y - y
        d = math.hypot(dx, dy)
        if d - e.radius > reach:
            continue
        if d > 1e-6 and abs(core.wrap_angle(math.atan2(dy, dx) - angle)) > half_angle_rad:
            continue
        if need_los and not los(x, y, e.x, e.y):
            continue
        out.append((d, e))
    out.sort(key=lambda t: t[0])
    return [e for _, e in out]


def spark(world, x, y, z, color, n=3):
    """Impact spark, at most 6 per frame (spec 4.5)."""
    fr = world.frame
    if getattr(world, '_spark_frame', -1) != fr:
        world._spark_frame = fr
        world._spark_count = 0
    if world._spark_count >= 6:
        return
    world._spark_count += 1
    world.burst(x, y, z, n, color, 1.5, 0.25, 2)


# ============================ projectiles ====================================
class Projectile:
    """Collides in 2D (substeps <= 0.25 cells). ox/oy = where it was fired from.

    on_hit(world, proj, target, x, y) -> bool is called on every impact, BEFORE the default one:
      - target is an Enemy (player projectile): default impact = apply_damage(damage, + splash_center
        when splash_r > 0) + splash() around it that excludes it + a spark;
      - target is the player (enemy projectile): default impact = apply_damage(damage) + a spark;
      - target is a Barrier (isinstance(target, combat.Barrier)) of the other team, unless
        through_barriers: default impact = target.take(damage + splash_center, owner) + a blue spark,
        with NO splash behind the barrier;
      - target is None for a wall: default impact = splash() at the wall (if splash_r > 0) + a spark.
    Return True when you did the impact yourself; the default one is then skipped. Either way the
    projectile dies afterwards, except that a pierce projectile goes on after an Enemy/player hit.
    on_expire(world, proj) runs when ttl runs out. draw(scene, proj) replaces the default orb.

    Projectile has __slots__, so extra state cannot be set on a plain instance. Subclass it (a subclass
    without __slots__ gets a __dict__): `class Bomb(Projectile): pass`, then `b = Bomb(...); b.stuck = e`.
    """
    __slots__ = ('x', 'y', 'z', 'vx', 'vy', 'radius', 'team', 'damage', 'splash_r', 'splash_center',
                 'splash_edge', 'ttl', 'pierce', 'through_barriers', 'hit_ids', 'owner', 'ability', 'color',
                 'core', 'size', 'on_hit', 'on_expire', 'draw', 'alive', 'ox', 'oy')

    def __init__(self, x, y, angle, speed, *, team, damage, radius=0.12, owner=None, ability='projectile',
                 ttl=2.0, z=0.45, color=(255, 70, 50), core=(255, 255, 255), size=0.08, pierce=False,
                 through_barriers=False, splash_r=0.0, splash_center=0.0, splash_edge=0.0,
                 on_hit=None, on_expire=None, draw=None):
        self.x = float(x)
        self.y = float(y)
        self.z = z
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.radius = radius
        self.team = team
        self.damage = float(damage)
        self.splash_r = splash_r
        self.splash_center = splash_center
        self.splash_edge = splash_edge
        self.ttl = ttl
        self.pierce = pierce
        self.through_barriers = through_barriers
        self.hit_ids = set()
        self.owner = owner
        self.ability = ability
        self.color = color
        self.core = core
        self.size = size
        self.on_hit = on_hit
        self.on_expire = on_expire
        self.draw = draw
        self.alive = True
        self.ox = self.x
        self.oy = self.y

    def update(self, world, dt):
        if not self.alive:
            return
        self.ttl -= dt
        travel = math.hypot(self.vx, self.vy) * dt
        n = max(1, int(math.ceil(travel / 0.25)))
        stx = self.vx * dt / n
        sty = self.vy * dt / n
        for _ in range(n):
            px, py = self.x, self.y
            nx, ny = px + stx, py + sty
            if is_wall(nx, ny):
                self._hit_wall(world, px, py)
                return
            if not self.through_barriers:
                for b in world.barriers:
                    if b.active and b.team != self.team:
                        t = b.intersects(px, py, nx, ny)
                        if t is not None:
                            hx = px + (nx - px) * t * 0.98
                            hy = py + (ny - py) * t * 0.98
                            self.alive = False
                            done = False
                            if self.on_hit is not None:
                                done = bool(self.on_hit(world, self, b, hx, hy))
                            if not done:
                                b.take(world, self.damage + self.splash_center, self.owner)
                                spark(world, hx, hy, self.z, (120, 200, 255))
                            return
            self.x, self.y = nx, ny
            if self.team == TEAM_PLAYER:
                for e in world.enemies:
                    if not e.alive or e.id in self.hit_ids:
                        continue
                    rr = self.radius + e.radius
                    if (e.x - nx) ** 2 + (e.y - ny) ** 2 <= rr * rr:
                        self._impact(world, e, nx, ny)
                        if not self.alive:
                            return
            else:
                p = world.player
                if p.alive and p.id not in self.hit_ids:
                    rr = self.radius + 0.3
                    if (p.x - nx) ** 2 + (p.y - ny) ** 2 <= rr * rr:
                        self._impact(world, p, nx, ny)
                        if not self.alive:
                            return
        if self.ttl <= 0.0:
            self.alive = False
            if self.on_expire is not None:
                self.on_expire(world, self)

    def _hit_wall(self, world, x, y):
        self.alive = False
        done = False
        if self.on_hit is not None:
            done = bool(self.on_hit(world, self, None, x, y))
        if not done:
            if self.splash_r > 0:
                splash(world, x, y, self.splash_r, self.splash_center, self.splash_edge, self.owner,
                       self.team, self.ability)
            spark(world, x, y, self.z, self.color)

    def _impact(self, world, target, x, y):
        done = False
        if self.on_hit is not None:
            done = bool(self.on_hit(world, self, target, x, y))
        if not done:
            if target is world.player:
                apply_damage(world, target, self.damage, self.owner, ability=self.ability,
                             from_xy=(self.ox, self.oy))
            else:
                extra = self.splash_center if self.splash_r > 0 else 0.0
                apply_damage(world, target, self.damage + extra, self.owner, ability=self.ability,
                             from_xy=(x, y))
                if self.splash_r > 0:
                    splash(world, x, y, self.splash_r, self.splash_center, self.splash_edge, self.owner,
                           self.team, self.ability, exclude=(target,))
            spark(world, x, y, self.z, self.color)
        if self.pierce:
            self.hit_ids.add(target.id)
        else:
            self.alive = False


# ============================ barriers =======================================
class Barrier:
    """A world segment of hit points (spec 5.6). Pose it every frame with set_pose.

    Look (render.build_scene draws every active barrier that is not owner_view_only): color_add is the
    additive fill and edge the 1 px top/bottom lines; for 0.08 s after a hit the *_hit pair is used, and
    below 30% hp the *_low pair (None = derived from color_add / edge by the renderer). z1 is the top.
    """
    owner_view_only = False

    def __init__(self, team, max_hp, half_width, owner=None, color_add=(20, 60, 120), edge=(120, 200, 255), *,
                 color_hit=None, edge_hit=None, color_low=None, edge_low=None, z1=0.9):
        self.team = team
        self.max_hp = float(max_hp)
        self.hp = float(max_hp)
        self.half_width = half_width
        self.owner = owner
        self.active = True
        self.last_hit = -9.0
        self.color_add = color_add
        self.edge = edge
        self.color_hit = color_hit
        self.edge_hit = edge_hit
        self.color_low = color_low
        self.edge_low = edge_low
        self.z1 = z1
        self.x1 = self.y1 = self.x2 = self.y2 = 0.0
        self.cx = self.cy = 0.0
        self.facing = 0.0

    def set_pose(self, cx, cy, facing):
        self.cx = cx
        self.cy = cy
        self.facing = facing
        px = -math.sin(facing) * self.half_width
        py = math.cos(facing) * self.half_width
        self.x1 = cx + px
        self.y1 = cy + py
        self.x2 = cx - px
        self.y2 = cy - py

    def intersects(self, ax, ay, bx, by):
        rx = bx - ax
        ry = by - ay
        sx = self.x2 - self.x1
        sy = self.y2 - self.y1
        den = rx * sy - ry * sx
        if abs(den) < 1e-12:
            return None
        qx = self.x1 - ax
        qy = self.y1 - ay
        t = (qx * sy - qy * sx) / den
        u = (qx * ry - qy * rx) / den
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
            return t
        return None

    def take(self, world, amount, source=None):
        if not self.active or amount <= 0:
            return 0.0
        a = min(self.hp, float(amount))
        self.hp -= a
        self.last_hit = world.now
        world.bus.emit('barrier_damage', barrier=self, amount=a, team=self.team, source=source)
        p = world.player
        if p is not None:
            if self.owner is p:
                p.add_ult(0.5 * a)
            if source is p and self.team != p.team:
                p.add_ult(0.5 * a)
        if self.hp <= 1e-6:
            self.hp = 0.0
            self.active = False
            world.bus.emit('barrier_broken', barrier=self, team=self.team)
        return a


# ============================ effects ========================================
class Effect:
    """World-updated object (heal field, pulse bomb, quake wave ...). Capped at 24.

    minimap_ring: None, or (x, y, r, color) in map cells; the HUD draws it on the minimap each frame
    (spec 6.3: the Heal Field ring). Set it as an attribute and keep it current (None hides it).
    """
    alive = True
    minimap_ring = None

    def update(self, world, dt):
        pass

    def emit_visuals(self, scene):
        pass

    def draw_screen(self, surf, world):
        pass
