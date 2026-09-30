"""Map, raycast, LOS, movement helpers, FlowField, Camera, Particle, HealthPack, World (spec 7.4).

world must not import combat at module level: it reaches hero and enemy classes
through core.HEROES / core.ENEMY_TYPES, and projectiles/effects through methods.
"""
import math
import random
from collections import deque

from . import config as C
from . import core
from .config import MAX_DEPTH, PLAYER_RADIUS

# ============================ map ============================================
RAW_MAP = [
    "11111111111111111111",
    "10000000010000000001",
    "10111011110001110101",
    "10100010001000100101",
    "10101110001110101101",
    "10000000000000000001",
    "11011011011101101101",
    "10000000000000000001",
    "10111101000010111101",
    "10000001000010000001",
    "10000001000010000001",
    "10111101000010111101",
    "10000000000000000001",
    "11011011011101101101",
    "10000000000000000001",
    "10101110001110101101",
    "10100010001000100101",
    "10111011110001110101",
    "10000000010000000001",
    "11111111111111111111",
]
MAP_W = len(RAW_MAP[0])
MAP_H = len(RAW_MAP)
WALL_GRID = [[ch == '1' for ch in row] for row in RAW_MAP]

OPEN_CELLS = [
    (x + 0.5, y + 0.5)
    for y in range(MAP_H) for x in range(MAP_W)
    if RAW_MAP[y][x] == '0'
]

PLAYER_START = (1.5, 1.5, 0.0)


def is_wall(x, y):
    mx, my = int(x), int(y)
    if x < 0 or y < 0:
        return True
    if 0 <= mx < MAP_W and 0 <= my < MAP_H:
        return WALL_GRID[my][mx]
    return True


def cast_ray(px, py, angle):
    """Unchanged DDA from the original game: (distance along the ray, side, map x, map y)."""
    rd_x = math.cos(angle)
    rd_y = math.sin(angle)
    mx, my = int(px), int(py)
    delta_x = abs(1 / rd_x) if rd_x != 0 else 1e30
    delta_y = abs(1 / rd_y) if rd_y != 0 else 1e30

    if rd_x < 0:
        step_x, sx = -1, (px - mx) * delta_x
    else:
        step_x, sx = 1, (mx + 1 - px) * delta_x
    if rd_y < 0:
        step_y, sy = -1, (py - my) * delta_y
    else:
        step_y, sy = 1, (my + 1 - py) * delta_y

    side = 0
    for _ in range(MAX_DEPTH * 4):
        if sx < sy:
            sx += delta_x
            mx += step_x
            side = 0
        else:
            sy += delta_y
            my += step_y
            side = 1
        if 0 <= mx < MAP_W and 0 <= my < MAP_H and RAW_MAP[my][mx] == '1':
            break
    else:
        return MAX_DEPTH, side, mx, my

    dist = (mx - px + (1 - step_x) / 2) / rd_x if side == 0 else \
           (my - py + (1 - step_y) / 2) / rd_y
    return max(dist, 0.01), side, mx, my


def los(ax, ay, bx, by):
    """True when no wall cell lies on the segment a->b (exact grid traversal)."""
    dx = bx - ax
    dy = by - ay
    d = math.hypot(dx, dy)
    mx, my = int(ax), int(ay)
    if is_wall(ax, ay):
        return False
    if d < 1e-9:
        return True
    rx = dx / d
    ry = dy / d
    ddx = abs(1.0 / rx) if rx != 0 else 1e30
    ddy = abs(1.0 / ry) if ry != 0 else 1e30
    if rx < 0:
        stx, sx = -1, (ax - mx) * ddx
    else:
        stx, sx = 1, (mx + 1 - ax) * ddx
    if ry < 0:
        sty, sy = -1, (ay - my) * ddy
    else:
        sty, sy = 1, (my + 1 - ay) * ddy
    grid = WALL_GRID
    for _ in range(MAP_W + MAP_H + 4):
        if sx < sy:
            if sx >= d:
                return True
            mx += stx
            sx += ddx
        else:
            if sy >= d:
                return True
            my += sty
            sy += ddy
        if not (0 <= mx < MAP_W and 0 <= my < MAP_H) or grid[my][mx]:
            return False
    return True


def _blocked(x, y, r):
    return (is_wall(x - r, y - r) or is_wall(x + r, y - r)
            or is_wall(x - r, y + r) or is_wall(x + r, y + r))


def move_slide(x, y, dx, dy, r=PLAYER_RADIUS):
    """Axis-separated move of a circle-ish body (square footprint of half-size r) with wall sliding."""
    m = max(abs(dx), abs(dy))
    if m <= 0.0:
        return x, y
    n = int(m / 0.3) + 1
    sx = dx / n
    sy = dy / n
    for _ in range(n):
        stuck = _blocked(x, y, r)       # already overlapping: fall back to a centre test
        if sx:
            nx = x + sx
            if not (is_wall(nx, y) if stuck else _blocked(nx, y, r)):
                x = nx
            elif not stuck:
                if sx > 0:
                    fx = math.floor(nx + r) - r - 1e-4
                    if x < fx < nx and not _blocked(fx, y, r):
                        x = fx
                else:
                    fx = math.floor(nx - r) + 1 + r + 1e-4
                    if nx < fx < x and not _blocked(fx, y, r):
                        x = fx
        if sy:
            ny = y + sy
            if not (is_wall(x, ny) if stuck else _blocked(x, ny, r)):
                y = ny
            elif not stuck:
                if sy > 0:
                    fy = math.floor(ny + r) - r - 1e-4
                    if y < fy < ny and not _blocked(x, fy, r):
                        y = fy
                else:
                    fy = math.floor(ny - r) + 1 + r + 1e-4
                    if ny < fy < y and not _blocked(x, fy, r):
                        y = fy
    return x, y


def dash_target(x, y, ang, dist, step=0.1, margin=0.3):
    """Walk from (x, y) along ang in `step`s; stop `margin` short of any wall. Returns the end point."""
    c = math.cos(ang)
    s = math.sin(ang)
    bx, by = x, y
    d = 0.0
    while d < dist - 1e-9:
        nd = min(dist, d + step)
        nx = x + c * nd
        ny = y + s * nd
        if is_wall(nx + c * margin, ny + s * margin) or _blocked(nx, ny, PLAYER_RADIUS):
            break
        bx, by, d = nx, ny, nd
    return bx, by


def open_cells_far(px, py, min_dist):
    md2 = min_dist * min_dist
    return [c for c in OPEN_CELLS if (c[0] - px) ** 2 + (c[1] - py) ** 2 >= md2]


# ============================ camera / flow ==================================
class Camera:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.angle = 0.0
        self.pitch = 0.0
        self.shake_amp = 0.0
        self.shake_left = 0.0


_N8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
UNREACHABLE = 999


class FlowField:
    """BFS distance field toward the player's cell (8-way, no corner cutting)."""

    def __init__(self):
        self.cx = -1
        self.cy = -1
        self.grid = [[UNREACHABLE] * MAP_W for _ in range(MAP_H)]

    @staticmethod
    def _step_ok(x, y, ox, oy):
        nx, ny = x + ox, y + oy
        if not (0 <= nx < MAP_W and 0 <= ny < MAP_H) or WALL_GRID[ny][nx]:
            return False
        if ox and oy and (WALL_GRID[y][nx] or WALL_GRID[ny][x]):
            return False
        return True

    def rebuild(self, cx, cy):
        g = [[UNREACHABLE] * MAP_W for _ in range(MAP_H)]
        self.cx, self.cy = cx, cy
        if 0 <= cx < MAP_W and 0 <= cy < MAP_H and not WALL_GRID[cy][cx]:
            g[cy][cx] = 0
            q = deque(((cx, cy),))
            ok = self._step_ok
            while q:
                x, y = q.popleft()
                nd = g[y][x] + 1
                for ox, oy in _N8:
                    if ok(x, y, ox, oy):
                        nx, ny = x + ox, y + oy
                        if g[ny][nx] > nd:
                            g[ny][nx] = nd
                            q.append((nx, ny))
        self.grid = g

    def dist(self, x, y):
        ix, iy = int(x), int(y)
        if 0 <= ix < MAP_W and 0 <= iy < MAP_H:
            return self.grid[iy][ix]
        return UNREACHABLE

    def _pick(self, x, y, lower):
        ix, iy = int(x), int(y)
        if not (0 <= ix < MAP_W and 0 <= iy < MAP_H):
            return 0.0, 0.0
        g = self.grid
        cur = g[iy][ix]
        if cur >= UNREACHABLE or (lower and cur == 0):
            return 0.0, 0.0
        best = None
        best_d = cur
        for ox, oy in _N8:
            if not self._step_ok(ix, iy, ox, oy):
                continue
            d = g[iy + oy][ix + ox]
            if d >= UNREACHABLE:
                continue
            if (lower and d < best_d) or (not lower and d > best_d):
                best_d = d
                best = (ix + ox + 0.5, iy + oy + 0.5)
        if best is None:
            return 0.0, 0.0
        dx = best[0] - x
        dy = best[1] - y
        m = math.hypot(dx, dy)
        if m < 1e-9:
            return 0.0, 0.0
        return dx / m, dy / m

    def toward(self, x, y):
        return self._pick(x, y, True)

    def away(self, x, y):
        return self._pick(x, y, False)


# ============================ particles / packs ==============================
class Particle:
    __slots__ = ('x', 'y', 'z', 'vx', 'vy', 'vz', 'ttl', 'color', 'size')

    def __init__(self, x, y, z, vx, vy, vz, ttl, color, size):
        self.x = x
        self.y = y
        self.z = z
        self.vx = vx
        self.vy = vy
        self.vz = vz
        self.ttl = ttl
        self.color = color
        self.size = size


class HealthPack:
    def __init__(self, x, y, big):
        self.x = x
        self.y = y
        self.big = big
        heal, respawn, h = C.PACK_LARGE if big else C.PACK_SMALL
        self.heal = heal
        self.respawn = respawn
        self.height = h
        self.active = True
        self.left = 0.0
        self._t = 0.0

    def update(self, world, dt):
        self._t = world.now
        if not self.active:
            self.left -= dt
            if self.left <= 0.0:
                self.active = True
                self.left = 0.0
            return
        p = world.player
        if not p.alive:
            return
        if (p.x - self.x) ** 2 + (p.y - self.y) ** 2 > C.PACK_RADIUS ** 2:
            return
        pool = p.pool
        if pool.health >= pool.max_health - 1e-6 and pool.armor >= pool.max_armor - 1e-6:
            return
        amt = pool.heal(self.heal)
        self.active = False
        self.left = self.respawn
        world.bus.emit('pack_pickup', big=self.big, amount=amt)
        world.bus.emit('heal', target=p, amount=amt, source=None, ability='pack')

    def emit_visuals(self, scene):
        if not self.active:
            return
        bob = 0.02 * math.sin(self._t * 3.0 + self.x)
        scene.sprite(self.x, self.y, 'pack_big' if self.big else 'pack_small', 'idle',
                     self.height, self.height * 0.9, z0=0.03 + bob)


# ============================ world ==========================================
class NullDirector:
    """Placeholder with the WaveDirector attributes; app swaps in waves.WaveDirector."""

    def __init__(self, world=None):
        self.stage = 1
        self.wave = 0
        self.wave_in_stage = 0
        self.kind = 'assault'
        self.state = 'idle'
        self.in_combat = False
        self.objective = None
        self.boss = None
        self.remaining = 0
        self.label = ''
        self.intermission_left = 0.0

    def start(self):
        pass

    def update(self, world, dt):
        pass

    def emit_visuals(self, scene):
        pass

    def skip_intermission(self):
        pass

    def debug_kill_all(self, world):
        pass


class World:
    def __init__(self, hero_key, seed=None, debug=None):
        self.clock = core.SimClock()
        self.bus = core.EventBus(self.clock)
        self.rng = random.Random(seed)                                   # gameplay randomness
        self.fx_rng = random.Random(None if seed is None else seed + 7919)  # cosmetic only
        self.debug = dict(debug or {})
        self.cam = Camera()
        self.dt = 0.0
        self.enemies = []
        self.projectiles = []
        self.barriers = []
        self.effects = []
        self.particles = []
        self.packs = ([HealthPack(x, y, True) for x, y in C.PACKS_LARGE]
                      + [HealthPack(x, y, False) for x, y in C.PACKS_SMALL])
        self.flow = FlowField()
        self.director = NullDirector(self)
        self.score = 0
        self.victory = False
        self.over = False
        self.projection = {}
        self.perf = {}
        self.los_used = 0
        self.frame = 0
        self._flow_cell = None
        self.player = core.HEROES[hero_key](self)
        self.player.x, self.player.y, self.player.angle = PLAYER_START
        self._sync_camera()
        self.rebuild_flow()
        self.bus.on('stage_clear', self._on_stage_clear)

    # --- properties ---------------------------------------------------------
    @property
    def now(self):
        return self.clock.now

    @property
    def stage(self):
        return self.director.stage

    # --- helpers --------------------------------------------------------------
    def _on_stage_clear(self, data):
        restore = getattr(self.player, 'restore', None)
        if restore is not None:
            restore(self)

    def rebuild_flow(self):
        cell = (int(self.player.x), int(self.player.y))
        self.flow.rebuild(*cell)
        self._flow_cell = cell

    def _sync_camera(self):
        p = self.player
        cam = self.cam
        cam.x = p.x
        cam.y = p.y
        cam.angle = p.angle
        cam.pitch = p.pitch

    def set_hero(self, key, keep_ult_frac=None):
        old = self.player
        if old is not None:
            old.on_removed(self)
        new = core.HEROES[key](self)
        if old is not None:
            new.x, new.y, new.angle, new.pitch = old.x, old.y, old.angle, old.pitch
            if keep_ult_frac is not None and old.ULT_COST > 0:
                frac = min(old.ult_charge / old.ULT_COST, keep_ult_frac)
                new.ult_charge = max(0.0, min(new.ULT_COST, frac * new.ULT_COST))
        self.player = new
        self._sync_camera()
        self.bus.emit('hero_swap', old=old.KEY if old is not None else None, new=key)
        return new

    def spawn_enemy(self, kind, x, y, elite=False, summon=False):
        cls = core.ENEMY_TYPES[kind]
        e = cls(self, x, y, elite=elite)
        e.summoned = bool(summon)
        self.enemies.append(e)
        self.bus.emit('enemy_spawn', enemy=e, kind=kind, elite=bool(elite), summon=bool(summon))
        return e

    def alive_enemies(self):
        return [e for e in self.enemies if e.alive]

    def enemies_near(self, x, y, r):
        r2 = r * r
        return [e for e in self.enemies if e.alive and (e.x - x) ** 2 + (e.y - y) ** 2 <= r2]

    def add_projectile(self, p):
        projs = self.projectiles
        if len(projs) >= C.CAP_PROJECTILES:
            if p.team == C.TEAM_ENEMY:
                return False
            for i, q in enumerate(projs):
                if q.team == C.TEAM_ENEMY:
                    del projs[i]
                    break
            else:
                return False
        projs.append(p)
        return True

    def add_effect(self, e):
        if len(self.effects) >= C.CAP_EFFECTS:
            return False
        self.effects.append(e)
        return True

    def add_barrier(self, b):
        if b in self.barriers:
            return True
        if len(self.barriers) >= C.CAP_BARRIERS:
            return False
        same = sum(1 for x in self.barriers if x.team == b.team)
        cap = C.CAP_PLAYER_BARRIERS if b.team == C.TEAM_PLAYER else C.CAP_ENEMY_BARRIERS
        if same >= cap:
            return False
        self.barriers.append(b)
        return True

    def remove_barrier(self, b):
        if b in self.barriers:
            self.barriers.remove(b)

    def player_barrier(self):
        for b in self.barriers:
            if b.team == C.TEAM_PLAYER and b.active:
                return b
        return None

    def burst(self, x, y, z, n, color, speed=2.0, ttl=0.5, size=2):
        parts = self.particles
        n = min(int(n), C.CAP_PARTICLES)
        over = len(parts) + n - C.CAP_PARTICLES
        if over > 0:
            del parts[:over]
        rnd = self.fx_rng.random
        for _ in range(n):
            a = rnd() * 6.2831853
            sp = speed * (0.4 + 0.6 * rnd())
            parts.append(Particle(x, y, z, math.cos(a) * sp, math.sin(a) * sp,
                                  speed * (0.3 + 0.9 * rnd()), ttl * (0.6 + 0.4 * rnd()), color, size))

    def shake(self, px, seconds):
        cam = self.cam
        cam.shake_amp = max(cam.shake_amp, float(px))
        cam.shake_left = max(cam.shake_left, float(seconds))

    def los(self, ax, ay, bx, by):
        return los(ax, ay, bx, by)

    def los_budgeted(self, ax, ay, bx, by, default=False):
        if self.los_used >= C.CAP_LOS_PER_FRAME:
            return default
        self.los_used += 1
        return los(ax, ay, bx, by)

    # --- frame ------------------------------------------------------------------
    def update(self, dt, inp):
        self.dt = dt
        self.los_used = 0
        self.frame += 1
        now = self.clock.now
        p = self.player

        # 2. player
        p.pool.update(dt, now)
        p.handle_input(inp, self)
        p.update(self, dt)

        # 3. flow
        cell = (int(self.player.x), int(self.player.y))
        if cell != self._flow_cell:
            self.flow.rebuild(*cell)
            self._flow_cell = cell

        # 4. director
        self.director.update(self, dt)

        # 5. enemies
        dead = False
        for e in tuple(self.enemies):
            if not e.alive:
                e.height_mult = max(0.0, (e.dying_until - now) / 0.3)
                if now >= e.dying_until:
                    dead = True
                continue
            e.pool.update(dt, now)
            st = e.status
            if st.can_act(now):
                e.update(self, dt)
            else:
                e.update_disabled(self, dt)
            if e.alive:
                if st.has('stun', now):
                    e.height_mult = 0.6
                    e._stun_scaled = True
                elif getattr(e, '_stun_scaled', False):
                    e.height_mult = 1.0
                    e._stun_scaled = False
        if dead:
            self.enemies = [e for e in self.enemies if e.alive or now < e.dying_until]

        # 6. separation
        self._separate(now)

        # 7. projectiles
        if self.projectiles:
            for pr in tuple(self.projectiles):
                if pr.alive:
                    pr.update(self, dt)
            self.projectiles = [pr for pr in self.projectiles if pr.alive]

        # 8. effects
        if self.effects:
            for ef in tuple(self.effects):
                if ef.alive:
                    ef.update(self, dt)
            self.effects = [ef for ef in self.effects if ef.alive]

        # 9. barriers: drop inactive ones whose owner is gone
        if self.barriers:
            self.barriers = [b for b in self.barriers
                             if b.active or (b.owner is not None and getattr(b.owner, 'alive', False))]

        # 10. packs
        for pk in self.packs:
            pk.update(self, dt)

        # 11. particles
        if self.particles:
            keep = []
            for q in self.particles:
                q.ttl -= dt
                q.vz -= 9.0 * dt
                q.x += q.vx * dt
                q.y += q.vy * dt
                q.z += q.vz * dt
                if q.ttl > 0.0 and q.z >= 0.0:
                    keep.append(q)
            self.particles = keep

        # 12. camera + shake decay
        self._sync_camera()
        cam = self.cam
        if cam.shake_left > 0.0:
            cam.shake_left -= dt
            if cam.shake_left <= 0.0:
                cam.shake_left = 0.0
                cam.shake_amp = 0.0

        # 13. death
        if not self.over and self.player.pool.dead:
            self.player.alive = False
            self.over = True
            self.bus.emit('player_death', hero=self.player.KEY)

    def _separate(self, now):
        al = [e for e in self.enemies if e.alive]
        n = len(al)
        for i in range(n):
            a = al[i]
            a_fixed = a.status.has('pinned', now)
            for j in range(i + 1, n):
                b = al[j]
                dx = b.x - a.x
                dy = b.y - a.y
                d2 = dx * dx + dy * dy
                if d2 >= 0.36:
                    continue
                d = math.sqrt(d2)
                if d < 1e-6:
                    ang = (a.id * 2.399963) % 6.2831853
                    ux, uy = math.cos(ang), math.sin(ang)
                else:
                    ux, uy = dx / d, dy / d
                push = (0.6 - d) * 0.5
                if not a_fixed:
                    a.x, a.y = move_slide(a.x, a.y, -ux * push, -uy * push, a.radius)
                if not b.status.has('pinned', now):
                    b.x, b.y = move_slide(b.x, b.y, ux * push, uy * push, b.radius)
        p = self.player
        for e in al:
            if e.status.has('pinned', now):
                continue
            min_d = e.radius + 0.25
            dx = e.x - p.x
            dy = e.y - p.y
            d2 = dx * dx + dy * dy
            if d2 < min_d * min_d:
                d = math.sqrt(d2)
                if d < 1e-6:
                    ux, uy = math.cos(p.angle), math.sin(p.angle)
                else:
                    ux, uy = dx / d, dy / d
                e.x, e.y = move_slide(e.x, e.y, ux * (min_d - d), uy * (min_d - d), e.radius)
