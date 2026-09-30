"""Headless balance bot (integration, spec 9.6). Plays the real game through the smoke Harness.

    python -X utf8 tools/autoplay.py [--heroes vector,flicker,rampart] [--stages 1,2,3] [--seeds 1,2,3]
                                     [--json PATH] [--shots] [--max-seconds 900] [--quiet]

Each run is one hero, one stage (its 5 waves, started with debug 'start_wave'), one seed, with NO god mode
and no other debug help ('skip_countdown', 'perf' and 'skip_end_screens' only). The bot feeds real pygame
events (keys, mouse buttons, mouse motion) through app.run_match's input_source, exactly like the harness
timeline, so every rule of the game applies (turn limits, cooldowns, ammo, pointer-free aiming).

Policy (the same for every run; hero specifics below):
- Perception: alive enemies with world.los from the player (the bot's eyes are not budgeted).
- Target: the nearest visible enemy (an arming/rushing Detonator or a close Slicer first), kept with some
  hysteresis. Aim: yaw at its centre, pitch at 60% of its height (upper body), turned with mouse motion at
  most 8 rad/s and 1400 px/s, plus a human-like error: 3 deg / 35 px on a new target that settles
  (Ornstein-Uhlenbeck, tau 0.3 s) to 0.6 deg / 8 px, and a 0.18 s reaction delay before the first shot.
  Fires only while the (post-turn) crosshair is on the target's body.
- Movement (grid BFS + look-ahead): capture waves -> stand on the point until it resolves; health below
  40% (RAMPART 35%) -> nearest active health pack; VECTOR's Heal Field -> stay inside it while hurt;
  otherwise keep a range band (VECTOR 4.5-8.5, FLICKER 3-5.5, RAMPART closes to 1.8), strafing inside
  the band, backing off an armed Detonator or a Warden stomp. No target in sight -> walk to the nearest
  enemy. Stuck for 1.5 s -> a random sidestep.
- Reload when the mag is empty (auto) or below half with no target in sight.
- Ult when ready and >= 3 enemies are in view (LOS, within the 60 deg FOV; RAMPART: in its 8-cell quake
  cone, FLICKER: within 7 cells, aimed at the densest cluster).
- VECTOR: Helix on cooldown when on target; Heal Field below 60%; Sprint when travelling with no enemy in
  sight. FLICKER: Blink away from close melee threats / an armed Detonator, Blink to travel, Rewind below 35%
  when the history holds 40+ more health, quick melee point-blank. RAMPART: hold the Barrier toward ranged
  enemies while closing in and lower it to swing; Charge a pinnable target 2.5-7 ahead; Flame Strike on
  target; hammer when in reach.

Output: a per-run line, then per-hero aggregates, and (--json) everything as JSON. Timings are sim seconds.
"""
import argparse
import json
import math
import os
import random
import statistics
import sys
import time
from collections import OrderedDict, deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.join(ROOT, 'game')
TOOLS = os.path.join(ROOT, 'tools')
DT = 1.0 / 30.0
TAU = 2.0 * math.pi

# bot tuning (NOT game tuning)
BOT = {
    'turn_rate': 8.0,               # rad/s max mouse turn
    'pitch_rate': 1400.0,           # px/s
    'err_yaw0': math.radians(6.0), 'err_pitch0': 70.0,       # error on acquiring a new target (sigma)
    'err_yaw': math.radians(3.0), 'err_pitch': 40.0,         # steady tracking error (sigma)
    'err_tau': 0.35,
    'lag': 4,                       # frames: the bot aims where the target was 0.13 s ago (tracking lag)
    'react': 0.18,                  # s after acquiring before the first shot
    'aim_frac': 0.55,               # aim at this fraction of the body height (from the floor)
    'fire_pad': (0.35, 25.0),       # hold fire while the crosshair is this near the body (cells, px)
    'retarget': 0.25,               # s between target re-evaluations
    'view_range': 16.0,
    'band': {'vector': (4.5, 8.5), 'flicker': (3.0, 5.5), 'rampart': (0.0, 1.8)},
    'pack_hp': {'vector': 0.40, 'flicker': 0.40, 'rampart': 0.35},
    'pack_done': 0.80,
}
# --profile average: a weaker player (slower turns and reactions, a wider aim error)
PROFILES = {
    'good': {},
    'average': {'turn_rate': 5.0, 'err_yaw0': math.radians(8.0), 'err_pitch0': 90.0, 'err_yaw': math.radians(4.5),
                'err_pitch': 55.0, 'react': 0.30, 'lag': 6},
}


def _setup_paths(no_assets=False):
    os.environ['SDL_VIDEODRIVER'] = 'dummy'
    os.environ['SDL_AUDIODRIVER'] = 'dummy'
    if no_assets:
        os.environ['RWF_NO_ASSETS'] = '1'
    for p in (GAME, TOOLS):
        if p not in sys.path:
            sys.path.insert(0, p)


def _wrap(a):
    return (a + math.pi) % TAU - math.pi


def _pct(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * q))]


# ============================ navigation ======================================
class Nav:
    """BFS distance fields (world.FlowField) toward goal cells, cached, plus look-ahead steering."""

    def __init__(self, world_mod):
        self.W = world_mod
        self.cache = OrderedDict()

    def field(self, gx, gy):
        key = (int(gx), int(gy))
        f = self.cache.get(key)
        if f is None:
            f = self.W.FlowField()
            f.rebuild(*key)
            self.cache[key] = f
            if len(self.cache) > 96:
                self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(key)
        return f

    def dist(self, x, y, gx, gy):
        return self.field(gx, gy).dist(x, y)

    def clear(self, ax, ay, bx, by, r=0.24):
        los = self.W.los
        if not los(ax, ay, bx, by):
            return False
        dx = bx - ax
        dy = by - ay
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return True
        nx = -dy / d * r
        ny = dx / d * r
        return los(ax + nx, ay + ny, bx + nx, by + ny) and los(ax - nx, ay - ny, bx - nx, by - ny)

    def direction(self, x, y, gx, gy):
        """Unit vector to walk from (x, y) toward (gx, gy), or (0, 0) when there."""
        d = math.hypot(gx - x, gy - y)
        if d < 0.15:
            return 0.0, 0.0
        if d < 6.0 and self.clear(x, y, gx, gy):
            return (gx - x) / d, (gy - y) / d
        f = self.field(gx, gy)
        g = f.grid
        cx, cy = int(x), int(y)
        if g[cy][cx] >= 999:
            return (gx - x) / d, (gy - y) / d
        path = []
        for _ in range(6):
            cur = g[cy][cx]
            if cur == 0:
                break
            best = None
            for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                if not f._step_ok(cx, cy, ox, oy):
                    continue
                v = g[cy + oy][cx + ox]
                if v < cur and (best is None or v < best[0]):
                    best = (v, cx + ox, cy + oy)
            if best is None:
                break
            cx, cy = best[1], best[2]
            path.append((cx + 0.5, cy + 0.5))
        if not path:
            return (gx - x) / d, (gy - y) / d
        wx, wy = path[0]
        for px, py in path[1:]:
            if self.clear(x, y, px, py):
                wx, wy = px, py
            else:
                break
        m = math.hypot(wx - x, wy - y)
        if m < 1e-6:
            return 0.0, 0.0
        return (wx - x) / m, (wy - y) / m


# ============================ the bot ==========================================
class Bot:
    def __init__(self, hero_key, seed, mods):
        self.key = hero_key
        self.rng = random.Random(seed * 7919 + len(hero_key))
        self.M = mods
        self.nav = Nav(mods['world'])
        self.target = None
        self.acq_t = -9.0
        self.next_pick = 0.0
        self.err_y = 0.0
        self.err_p = 0.0
        self.trail = deque(maxlen=BOT['lag'] + 1)
        self.strafe = 1
        self.strafe_until = 0.0
        self.pack = None
        self.stuck_ref = None
        self.unstick_until = -1.0
        self.unstick_dir = (0.0, 0.0)
        self.app_state = 'PLAYING'
        self.skip_sent = False

    # --- perception -----------------------------------------------------------------------------
    def visible(self, w):
        p = w.player
        out = []
        for e in w.enemies:
            if not e.alive:
                continue
            d = math.hypot(e.x - p.x, e.y - p.y)
            if d <= BOT['view_range'] and w.los(p.x, p.y, e.x, e.y):
                out.append((d, e))
        out.sort(key=lambda t: t[0])
        return out

    def in_view(self, p, vis, max_d=15.0, half=math.radians(30.0), angle=None):
        a = p.angle if angle is None else angle
        n = 0
        for d, e in vis:
            if d <= max_d and abs(_wrap(math.atan2(e.y - p.y, e.x - p.x) - a)) <= half:
                n += 1
        return n

    def pick_target(self, w, vis):
        best = None
        for d, e in vis:
            s = d
            k = e.KIND
            if k == 'detonator' and d < 5.0:
                s -= 4.0
            elif k == 'slicer' and d < 4.0:
                s -= 2.0
            if e is self.target:
                s -= 1.5
            if best is None or s < best[0]:
                best = (s, e)
        return best[1] if best else None

    # --- aim ------------------------------------------------------------------------------------
    def _update_error(self, dt):
        k = math.exp(-dt / BOT['err_tau'])
        q = math.sqrt(max(0.0, 1.0 - k * k))
        g = self.rng.gauss
        self.err_y = self.err_y * k + g(0.0, BOT['err_yaw']) * q
        self.err_p = self.err_p * k + g(0.0, BOT['err_pitch']) * q

    def _acquire(self, e, now):
        if e is not self.target:
            self.target = e
            self.acq_t = now
            self.trail.clear()
            if e is not None:
                self.err_y = self.rng.gauss(0.0, BOT['err_yaw0'])
                self.err_p = self.rng.gauss(0.0, BOT['err_pitch0'])

    @staticmethod
    def aim_point(p, e, frac, pos=None):
        ex, ey = (e.x, e.y) if pos is None else pos
        d = max(0.3, math.hypot(ex - p.x, ey - p.y))
        z = e.z0 + e.height * e.height_mult * frac
        return math.atan2(ey - p.y, ex - p.x), (z - 0.5) * 768.0 / d, d

    def on_body(self, p, e, yaw, pitch, pad=(0.0, 0.0)):
        """Is a hitscan along (yaw, pitch) on e's body, or within pad = (cells sideways, px vertically) of
        it? (the same geometry as combat.hitscan)"""
        dx = e.x - p.x
        dy = e.y - p.y
        c = math.cos(yaw)
        s = math.sin(yaw)
        proj = dx * c + dy * s
        if proj <= 0.1:
            return False
        if abs(dx * s - dy * c) > e.width * 0.5 + 0.08 + pad[0]:
            return False
        z = 0.5 + pitch / 768.0 * proj
        h = e.height * e.height_mult
        zp = pad[1] * proj / 768.0
        return e.z0 - 0.03 - zp <= z <= e.z0 + h + 0.03 + zp

    # --- movement helpers -----------------------------------------------------------------------
    def walkable(self, w, x, y, ux, uy, dist=0.6):
        nx, ny = self.M['world'].move_slide(x, y, ux * dist, uy * dist, 0.25)
        return math.hypot(nx - x, ny - y)

    def away_dir(self, w, p, sx, sy):
        base = math.atan2(p.y - sy, p.x - sx)
        best = None
        for off in (0.0, 0.6, -0.6, 1.2, -1.2, 1.9, -1.9):
            a = base + off
            ux, uy = math.cos(a), math.sin(a)
            m = self.walkable(w, p.x, p.y, ux, uy)
            score = m - abs(off) * 0.15
            if best is None or score > best[0]:
                best = (score, ux, uy)
        return best[1], best[2]

    def strafe_dir(self, w, p, e, now):
        if now >= self.strafe_until:
            self.strafe = -self.strafe if self.rng.random() < 0.7 else self.strafe
            self.strafe_until = now + self.rng.uniform(0.8, 1.8)
        a = math.atan2(e.y - p.y, e.x - p.x) + self.strafe * math.pi / 2
        ux, uy = math.cos(a), math.sin(a)
        if self.walkable(w, p.x, p.y, ux, uy, 0.4) < 0.2:
            self.strafe = -self.strafe
            self.strafe_until = now + self.rng.uniform(0.8, 1.8)
            ux, uy = -ux, -uy
        return ux, uy

    @staticmethod
    def keys_for(vx, vy, angle):
        m = math.hypot(vx, vy)
        out = set()
        if m < 1e-6:
            return out
        f = (vx * math.cos(angle) + vy * math.sin(angle)) / m
        r = (-vx * math.sin(angle) + vy * math.cos(angle)) / m
        if f > 0.38:
            out.add('fwd')
        elif f < -0.38:
            out.add('back')
        if r > 0.38:
            out.add('right')
        elif r < -0.38:
            out.add('left')
        return out

    @staticmethod
    def shielded(w, p, e):
        """True when e's own team barrier stands between the player and e."""
        for b in w.barriers:
            if b.active and b.team == e.team and b.owner is e and b.intersects(p.x, p.y, e.x, e.y) is not None:
                return True
        return False

    def cover_from(self, w, p, src, now):
        """The nearest open cell (by walking distance, at most 6) that src cannot see; kept 0.5 s."""
        c = getattr(self, '_cover', None)
        if c is not None and now < c[1]:
            return c[0]
        los = w.los
        best = None
        for cx, cy in self.M['world'].OPEN_CELLS:
            fd = w.flow.dist(cx, cy)
            if fd > 6 or (best is not None and fd >= best[0]):
                continue
            if any(los(src.x, src.y, cx + ox, cy + oy) for ox, oy in ((0, 0), (0.3, 0.3), (-0.3, 0.3),
                                                                     (0.3, -0.3), (-0.3, -0.3))):
                continue
            best = (fd, (cx, cy))
        self._cover = ((best[1] if best else None), now + 0.5)
        return self._cover[0]

    def nearest_pack(self, w, p):
        best = None
        for pk in w.packs:
            if not pk.active:
                continue
            d = self.nav.dist(p.x, p.y, pk.x, pk.y)
            if best is None or d < best[0]:
                best = (d, pk)
        return best[1] if best else None

    # --- the decision ---------------------------------------------------------------------------
    def decide(self, w, now):
        """-> (held actions, tapped actions, dyaw rad, dpitch px) for the next frame."""
        p = w.player
        hold = set()
        taps = set()
        if not p.alive:
            return hold, taps, 0.0, 0.0
        if self.app_state == 'INTERMISSION':
            if not self.skip_sent:
                self.skip_sent = True
                taps.add('confirm')
            return hold, taps, 0.0, 0.0
        self.skip_sent = False
        d_ = w.director
        pool = p.pool
        hp = pool.total / max(1.0, pool.max_total)
        vis = self.visible(w)
        self._update_error(DT)
        if now >= self.next_pick or self.target is None or not self.target.alive or \
                all(e is not self.target for _, e in vis):
            self.next_pick = now + BOT['retarget']
            self._acquire(self.pick_target(w, vis), now)
        tgt = self.target if (self.target is not None and self.target.alive) else None
        tdist = math.hypot(tgt.x - p.x, tgt.y - p.y) if tgt is not None else 99.0

        # ---- movement goal ----
        mv = (0.0, 0.0)
        goal = None
        ob = getattr(d_, 'objective', None)
        capture = d_.kind == 'capture' and d_.state == 'active' and ob is not None and not ob.done
        if self.pack is not None and (not self.pack.active or hp >= BOT['pack_done']):
            self.pack = None
        if self.pack is None and hp < BOT['pack_hp'][self.key] and not capture:
            self.pack = self.nearest_pack(w, p)
        threat = None
        for d, e in vis:
            if e.KIND == 'detonator' and getattr(e, 'mode', '') == 'armed' and d < 2.8:
                threat = e
                break
            if e.KIND == 'warden' and getattr(e, 'mode', '') == 'stomp_windup' and d < 3.4:
                threat = e
                break
        sentry = None
        if self.key != 'rampart':
            for d, e in vis:
                if e.KIND == 'warden' and getattr(e, 'mode', '') in ('sentry_windup', 'sentry') and d < 14.0:
                    sentry = e
                    break
        field = getattr(p, 'field', None)
        band = BOT['band'][self.key]
        cover = self.cover_from(w, p, sentry, now) if sentry is not None else None
        if threat is not None and not (self.key == 'rampart' and p.barrier_up):
            mv = self.away_dir(w, p, threat.x, threat.y)
        elif cover is not None:
            goal = cover                    # break line of sight while the Warden is in sentry mode
        elif capture:
            dd = math.hypot(p.x - ob.x, p.y - ob.y)
            if dd > ob.radius * 0.55:
                goal = (ob.x, ob.y)
            elif tgt is not None:
                mv = self.strafe_dir(w, p, tgt, now)
                nx, ny = p.x + mv[0] * 0.5, p.y + mv[1] * 0.5
                if math.hypot(nx - ob.x, ny - ob.y) > ob.radius * 0.7:
                    mv = (0.0, 0.0)
        elif self.pack is not None:
            goal = (self.pack.x, self.pack.y)
        elif field is not None and field.alive and hp < 0.95 and math.hypot(p.x - field.x, p.y - field.y) > 1.4:
            goal = (field.x, field.y)
        elif tgt is not None and self.shielded(w, p, tgt):
            goal = (tgt.x, tgt.y)           # an Eradicator behind its barrier: walk in past the barrier
        elif tgt is not None:
            lo, hi = band
            if tdist < lo:
                mv = self.away_dir(w, p, tgt.x, tgt.y)
            elif tdist > hi:
                goal = (tgt.x, tgt.y)
            elif self.key != 'rampart':
                mv = self.strafe_dir(w, p, tgt, now)
        else:
            al = [e for e in w.enemies if e.alive]
            if al:
                e = min(al, key=lambda e: math.hypot(e.x - p.x, e.y - p.y))
                goal = (e.x, e.y)
            elif hp < 0.9:
                pk = self.nearest_pack(w, p)
                if pk is not None:
                    goal = (pk.x, pk.y)
        if goal is not None:
            mv = self.nav.direction(p.x, p.y, goal[0], goal[1])
        # stuck: wanted to move but barely moved for 1.5 s -> sidestep
        moving = abs(mv[0]) + abs(mv[1]) > 1e-6
        if now < self.unstick_until:
            mv = self.unstick_dir
        elif moving:
            ref = self.stuck_ref
            if ref is None or math.hypot(p.x - ref[0], p.y - ref[1]) > 0.4:
                self.stuck_ref = (p.x, p.y, now)
            elif now - ref[2] > 1.5:
                a = self.rng.uniform(0.0, TAU)
                self.unstick_dir = (math.cos(a), math.sin(a))
                self.unstick_until = now + 0.5
                self.stuck_ref = None
        else:
            self.stuck_ref = None

        # ---- aim ----
        if tgt is not None:
            self.trail.append((tgt.x, tgt.y))
            yaw, pitch, _ = self.aim_point(p, tgt, BOT['aim_frac'] if self.key != 'rampart' else 0.5,
                                           self.trail[0])
            yaw += self.err_y
            pitch += self.err_p
        elif abs(mv[0]) + abs(mv[1]) > 1e-6:
            yaw, pitch = math.atan2(mv[1], mv[0]), 0.0
        else:
            yaw, pitch = p.angle, 0.0
        yaw, pitch, hold, taps = self.hero_policy(w, p, now, vis, tgt, tdist, yaw, pitch, mv, goal, hp,
                                                  capture, hold, taps)
        dyaw = _wrap(yaw - p.angle)
        lim = BOT['turn_rate'] * DT
        dyaw = max(-lim, min(lim, dyaw))
        plim = BOT['pitch_rate'] * DT
        dpitch = max(-plim, min(plim, pitch - p.pitch))
        new_yaw = p.angle + dyaw
        hold |= self.keys_for(mv[0], mv[1], new_yaw)
        if 'fire?' in hold:
            hold.discard('fire?')
            if tgt is not None and now - self.acq_t >= BOT['react'] and \
                    self.on_body(p, tgt, new_yaw, p.pitch + dpitch, BOT['fire_pad']):
                hold.add('fire')
        return hold, taps, dyaw, dpitch

    # --- hero policies ------------------------------------------------------------------------------
    def hero_policy(self, w, p, now, vis, tgt, tdist, yaw, pitch, mv, goal, hp, capture, hold, taps):
        fn = getattr(self, 'policy_' + self.key)
        return fn(w, p, now, vis, tgt, tdist, yaw, pitch, mv, goal, hp, capture, hold, taps)

    def _aim_err(self, p, yaw):
        return abs(_wrap(yaw - p.angle))

    def policy_vector(self, w, p, now, vis, tgt, tdist, yaw, pitch, mv, goal, hp, capture, hold, taps):
        ab = p.abilities
        ult_on = p.ult_active_left > 0.0
        if ult_on:
            if self.in_view(p, vis) > 0:
                hold.add('fire')
        elif tgt is not None:
            hold.add('fire?')
            if ab['secondary'].ready() and tdist > 1.5 and self._aim_err(p, yaw) < math.radians(2.5) and \
                    now - self.acq_t > BOT['react']:
                taps.add('alt')
        if p.ult_ready and not ult_on and self.in_view(p, vis) >= 3:
            taps.add('ult')
        if hp < 0.6 and ab['ab2'].ready() and (vis or pool_hurt_recent(w, p)):
            taps.add('ab2')
        if not p.reloading and p.ammo < p.MAX_AMMO // 2 and not vis and not ult_on:
            taps.add('reload')
        # sprint while travelling with nobody in sight (the latch needs W: the bot looks where it walks)
        if tgt is None and goal is not None and not vis and math.hypot(goal[0] - p.x, goal[1] - p.y) > 5.0:
            if not getattr(p, '_latched', False) and ab['ab1'].ready():
                taps.add('ab1')
        return yaw, pitch, hold, taps

    def policy_flicker(self, w, p, now, vis, tgt, tdist, yaw, pitch, mv, goal, hp, capture, hold, taps):
        ab = p.abilities
        blink = ab['ab1']
        if tgt is not None and tdist < 12.0:
            hold.add('fire?')
            if tdist < 1.4 and p.melee_left <= 0.0 and self._aim_err(p, yaw) < math.radians(25):
                taps.add('melee')
        # pulse bomb: >= 3 enemies within 7 in view -> aim at the densest cluster and throw
        if p.ult_ready:
            near = [(d, e) for d, e in vis if d <= 7.0]
            if self.in_view(p, near, 7.0) >= 3:
                best = None
                for d, e in near:
                    if d > 6.0:
                        continue
                    n = sum(1 for _, o in near if math.hypot(o.x - e.x, o.y - e.y) <= 2.5)
                    if best is None or n > best[0]:
                        best = (n, e)
                if best is not None and best[0] >= 2:
                    e = best[1]
                    self._acquire(e, now)
                    yaw, pitch, _ = self.aim_point(p, e, 0.5)
                    if self._aim_err(p, yaw) < math.radians(3.0):
                        taps.add('ult')
        # rewind when low and the history holds much more health
        hist = getattr(p, 'history', None)
        if hp < 0.35 and ab['ab2'].ready() and hist and hist[0][3] >= p.pool.health + 40.0:
            taps.add('ab2')
            return yaw, pitch, hold, taps
        # blink: escape close threats, or travel
        if blink.charges > 0 and p.rewind is None:
            close = [(d, e) for d, e in vis if d < 2.2 and e.KIND in ('slicer', 'detonator', 'trooper', 'eradicator')]
            armed = [(d, e) for d, e in vis if e.KIND == 'detonator' and getattr(e, 'mode', '') == 'armed' and d < 3.0]
            if armed or (close and hp < 0.7):
                src = (armed or close)[0][1]
                ux, uy = self.away_dir(w, p, src.x, src.y)
                if self.walkable(w, p.x, p.y, ux, uy, 2.0) > 1.2:
                    self._blink_dir = (ux, uy)          # BotSource sets the move keys for this blink
                    taps.add('ab1')
            elif (tgt is None and goal is not None and blink.charges == blink.max_charges
                  and self.nav.dist(p.x, p.y, goal[0], goal[1]) > 6):
                taps.add('ab1')
        return yaw, pitch, hold, taps

    def policy_rampart(self, w, p, now, vis, tgt, tdist, yaw, pitch, mv, goal, hp, capture, hold, taps):
        ab = p.abilities
        pitch = 0.0
        reach = tgt is not None and tdist - tgt.radius <= 2.35
        if tgt is not None and reach and self._aim_err(p, yaw) < math.radians(38) and not p.charging:
            hold.add('fire')
        ranged = [(d, e) for d, e in vis if e.KIND in ('trooper', 'eradicator', 'warden') and d > 2.8]
        incoming = False
        for q in w.projectiles:
            if q.team == 1 and q.alive:
                dx, dy = p.x - q.x, p.y - q.y
                dd = math.hypot(dx, dy)
                if dd < 4.0 and (q.vx * dx + q.vy * dy) > 0.6 * dd * math.hypot(q.vx, q.vy):
                    incoming = True
                    break
        armed = any(e.KIND == 'detonator' and getattr(e, 'mode', '') == 'armed' and d < 3.0 for d, e in vis)
        bar = p.barrier
        want_bar = (not reach and (ranged or incoming) and bar.hp > 120.0) or (armed and bar.hp > 60.0)
        if want_bar and not p.charging:
            hold.add('alt')
            hold.discard('fire')
        if p.ult_ready and not p.charging:
            n = self.in_view(p, [(d, e) for d, e in vis if d - e.radius <= 7.6], 7.6, math.radians(28))
            if n >= 3:
                taps.add('ult')
        if tgt is not None and not p.charging and self._aim_err(p, yaw) < math.radians(4.0):
            if ab['ab2'].charges > 0 and 2.5 <= tdist <= 11.0 and 'ult' not in taps:
                taps.add('ab2')
            if (ab['ab1'].ready() and 2.5 <= tdist <= 7.0 and tgt.PINNABLE and hp > 0.35
                    and (not capture or math.hypot(tgt.x - 10.0, tgt.y - 10.0) < 3.0)
                    and self.nav.clear(p.x, p.y, tgt.x, tgt.y, 0.3)):
                taps.add('ab1')
        return yaw, pitch, hold, taps


def pool_hurt_recent(w, p):
    return w.now - p.pool.last_damage < 2.0


class BotSource:
    """input_source for app.run_match: turns the bot's wishes into real pygame events."""

    def __init__(self, bot, pg, C):
        self.bot = bot
        self.pg = pg
        self.C = C
        self.world = None
        self.held = set()
        self.up_next = []
        self.keys = {}
        for k, a in C.KEYMAP.items():
            self.keys.setdefault(a, k)
        self.buttons = {a: b for b, a in C.MOUSEMAP.items()}

    def _ev(self, action, down):
        pg = self.pg
        if action in self.buttons:
            t = pg.MOUSEBUTTONDOWN if down else pg.MOUSEBUTTONUP
            return pg.event.Event(t, button=self.buttons[action], pos=(self.C.W // 2, self.C.H // 2))
        t = pg.KEYDOWN if down else pg.KEYUP
        return pg.event.Event(t, key=self.keys[action], mod=0, unicode='', scancode=0)

    def events_for_frame(self, i):
        w = self.world
        out = [self._ev(a, False) for a in self.up_next if a not in self.held]
        self.up_next = []
        if w is None:
            return out
        hold, taps, dyaw, dpitch = self.bot.decide(w, w.now)
        blink_dir = getattr(self.bot, '_blink_dir', None)
        if blink_dir is not None and 'ab1' in taps:
            hold = (hold - {'fwd', 'back', 'left', 'right'}) | self.bot.keys_for(blink_dir[0], blink_dir[1],
                                                                                w.player.angle + dyaw)
            self.bot._blink_dir = None
        for a in self.held - hold:
            out.append(self._ev(a, False))
        for a in hold - self.held:
            out.append(self._ev(a, True))
        self.held = set(hold)
        for a in taps:
            if a in self.held:
                continue
            out.append(self._ev(a, True))
            self.up_next.append(a)
        if dyaw or dpitch:
            sens = 1.0
            try:
                sens = self.bot.M['core'].SETTINGS['sens']
            except Exception:
                pass
            dx = dyaw / (self.C.MOUSE_YAW * sens)
            dy = -dpitch / (self.C.MOUSE_PITCH * sens)
            out.append(self.pg.event.Event(self.pg.MOUSEMOTION, rel=(dx, dy), pos=(self.C.W // 2, self.C.H // 2),
                                           buttons=(0, 0, 0)))
        return out


# ============================ one run ==========================================
def play(h, hero, stage, seed, max_seconds=900.0, shots=False, trace=0.0):
    import itertools
    import pygame
    from rwf import combat, config as C, core, world as world_mod
    combat._ids = itertools.count(1)        # entity ids (slicer flanking, AI stagger) as in a fresh process
    mods = {'world': world_mod, 'core': core}
    bot = Bot(hero, seed, mods)
    src = BotSource(bot, pygame, C)
    start_wave = (stage - 1) * C.WAVES_PER_STAGE + 1
    ev = []
    st = {'stop': False, 'end': None, 'perf': [], 'inv': None}
    src_pts = {'damage': 0.0, 'ult_damage': 0.0, 'heal': 0.0, 'barrier': 0.0, 'passive': 0.0, 'capture': 0.0}
    st['src'] = src_pts

    def gain(kind, pts):
        """Ult charge by source (spec 5.9), counted only while it can actually be gained."""
        p = st['w'].player
        if pts > 0 and p.ult_active_left <= 0.0 and p.ult_charge < p.ULT_COST - 1e-6:
            src_pts[kind] += min(pts, p.ULT_COST - p.ult_charge)

    def rec(d):
        n = d['event']
        keep = None
        me = st['w'].player
        if n == 'damage' and d.get('source') is me and not d.get('to_player'):
            gain('ult_damage' if d.get('ability') == 'ult' else 'damage', float(d.get('amount') or 0.0))
        elif n == 'heal' and d.get('ability') == 'ab2':
            gain('heal', float(d.get('amount') or 0.0))
        elif n == 'barrier_damage':
            b = d.get('barrier')
            if b is not None and b.owner is me:
                gain('barrier', 0.5 * float(d.get('amount') or 0.0))
            if d.get('source') is me and d.get('team') != me.team:
                gain('barrier', 0.5 * float(d.get('amount') or 0.0))
        elif n == 'objective' and d.get('state') == 'captured':
            src_pts['capture'] += 0.2 * me.ULT_COST
        if n in ('wave_start', 'wave_clear', 'stage_clear', 'ult_ready', 'ult_used', 'ult_end', 'boss_spawn',
                 'boss_phase', 'player_death', 'victory', 'hero_swap'):
            keep = {k: v for k, v in d.items() if k in ('stage', 'wave', 'wave_in_stage', 'kind', 'hero')}
        elif n == 'objective':
            keep = {'state': d.get('state')}
        elif n == 'kill':
            keep = {'kind': getattr(d.get('target'), 'KIND', '?'), 'boss': d.get('boss'), 'ult': d.get('ult'),
                    'player': d.get('source') is not None and d.get('source') is st['w'].player,
                    'ability': d.get('ability'), 'crit': d.get('crit'),
                    'me': d.get('target') is st['w'].player}
        elif n == 'damage':
            src_ = d.get('source')
            keep = {'amount': d.get('amount'), 'to_player': d.get('to_player'), 'ability': d.get('ability'),
                    'mine': src_ is not None and src_ is st['w'].player,
                    'boss': bool(getattr(d.get('target'), 'BOSS', False))}
        elif n == 'player_hurt':
            keep = {'amount': d.get('amount'), 'ability': d.get('ability')}
        elif n == 'heal':
            keep = {'amount': d.get('amount'), 'ability': d.get('ability')}
        elif n == 'barrier_damage':
            b = d.get('barrier')
            keep = {'amount': d.get('amount'), 'team': d.get('team'),
                    'mine': b is not None and b.owner is st['w'].player,
                    'by_me': d.get('source') is st['w'].player}
        elif n == 'shot':
            keep = {'hit': d.get('hit'), 'crit': d.get('crit')}
        elif n == 'pack_pickup':
            keep = {'amount': d.get('amount')}
        if keep is not None:
            ev.append((d['t'], n, keep))
            if n == 'stage_clear' and d.get('stage') == stage:
                st['stop'] = True
                st['end'] = 'stage_clear'

    def setup(w):
        st['w'] = w
        src.world = w
        w.bus.on('*', rec)

    def on_frame(w, i, state):
        bot.app_state = state
        p = w.player
        if w.director.in_combat and p.ult_active_left <= 0.0 and p.ult_charge < p.ULT_COST and w.dt > 0:
            src_pts['passive'] += 5.0 * w.dt
        if w.perf:
            st['perf'].append((w.perf.get('update', 0.0), w.perf.get('render', 0.0), w.perf.get('hud', 0.0),
                               w.perf.get('total', 0.0)))
        if st['inv'] is None:
            try:
                err = h._invariants(w)
            except Exception as e:     # noqa: BLE001
                err = 'invariant check raised %r' % e
            if err:
                st['inv'] = 'frame %d: %s' % (i, err)
        if trace and i % int(trace / DT) == 0:
            p = w.player
            d_ = w.director
            print('  t %6.1f w%d %s %s rem %d | me (%.1f, %.1f) hp %.0f tgt %s | %s' % (
                w.now, d_.wave, d_.kind, d_.state, d_.remaining, p.x, p.y, p.pool.total,
                getattr(bot.target, 'KIND', None),
                ' '.join('%s(%.1f,%.1f,%s)' % (e.KIND[:3], e.x, e.y, getattr(e, 'mode', '')) for e in w.enemies
                         if e.alive)))
        if shots and i % 900 == 450:
            h.save(h.screen, 'autoplay_%s_s%d_%d_%05d' % (hero, stage, seed, i))
        if st['stop']:
            return 'stop'
        if w.now > max_seconds:
            st['end'] = 'timeout'
            return 'stop'
        return None

    dbg = {'skip_countdown': True, 'perf': True, 'skip_end_screens': True, 'start_wave': start_wave}
    t0 = time.perf_counter()
    import asyncio
    res = asyncio.run(h.app.run_match(h.screen, hero, input_source=src, fixed_dt=DT,
                                      max_frames=int(max_seconds / DT) + 600, seed=seed, debug=dbg,
                                      setup=setup, on_frame=on_frame))
    wall = time.perf_counter() - t0
    w = res.world
    end = st['end'] or ('death' if (w is not None and w.over) else 'frames')
    return summarize(hero, stage, seed, ev, res, st, end, wall)


def summarize(hero, stage, seed, ev, res, st, end, wall):
    w = res.world
    waves = []
    cur = None
    boss_t = None
    boss_first_hit = None
    boss_fights = []
    ult_ready = []
    ult_used = []
    deaths = []
    captures = []
    shots = hits = crits = 0
    dmg_out = heal_ab = bar_abs = bar_dealt = 0.0
    packs = 0
    last_hurt = None
    for t, n, d in ev:
        if n == 'wave_start':
            cur = {'wave': d['wave'], 'kind': d['kind'], 't0': t, 't1': None, 'taken': 0.0, 'ults': 0,
                   'ults_ready': 0, 'kills': 0, 'capture': None}
            waves.append(cur)
        elif n == 'wave_clear' and cur is not None:
            cur['t1'] = t
        elif n == 'boss_spawn':
            boss_t = t
            boss_first_hit = None
        elif n == 'damage' and d.get('boss') and d.get('mine') and boss_t is not None and boss_first_hit is None:
            boss_first_hit = t
        elif n == 'kill':
            if d.get('boss') and boss_t is not None:
                boss_fights.append({'spawn_to_kill': t - boss_t,
                                    'engage_to_kill': t - (boss_first_hit if boss_first_hit is not None else boss_t)})
                boss_t = None
            if d.get('player') and cur is not None:
                cur['kills'] += 1
        elif n == 'ult_ready':
            ult_ready.append(t)
            if cur is not None:
                cur['ults_ready'] += 1
        elif n == 'ult_used':
            ult_used.append(t)
            if cur is not None:
                cur['ults'] += 1
        elif n == 'player_hurt':
            last_hurt = d.get('ability')
            if cur is not None:
                cur['taken'] += float(d.get('amount') or 0.0)
        elif n == 'player_death':
            deaths.append({'t': t, 'wave': cur['wave'] if cur else None, 'kind': cur['kind'] if cur else None,
                           'into_wave': (t - cur['t0']) if cur else None, 'by': last_hurt})
        elif n == 'objective' and cur is not None and d['state'] in ('captured', 'failed'):
            cur['capture'] = d['state']
            captures.append(d['state'])
        elif n == 'shot':
            shots += 1
            hits += 1 if d.get('hit') else 0
            crits += 1 if d.get('crit') else 0
        elif n == 'damage' and d.get('mine') and not d.get('to_player'):
            dmg_out += float(d.get('amount') or 0.0)
        elif n == 'heal' and d.get('ability') == 'ab2':
            heal_ab += float(d.get('amount') or 0.0)
        elif n == 'barrier_damage':
            if d.get('mine'):
                bar_abs += float(d.get('amount') or 0.0)
            if d.get('by_me'):
                bar_dealt += float(d.get('amount') or 0.0)
        elif n == 'pack_pickup':
            packs += 1
    # ult charge times: previous ult_used (or the run's first wave start) -> ult_ready
    t_start = waves[0]['t0'] if waves else 0.0
    charge = []
    hold_t = []
    prev = t_start
    ui = 0
    for tr in ult_ready:
        charge.append(tr - prev)
        nxt = [u for u in ult_used if u >= tr - 1e-9]
        if nxt:
            hold_t.append(nxt[0] - tr)
            prev = nxt[0]
        else:
            prev = None
            break
        ui += 1
    gaps = [b - a for a, b in zip(ult_used, ult_used[1:])]
    perf = st['perf'][60:]
    tot = [x[3] for x in perf]
    frame_ms = res.frame_ms[60:] if res.frame_ms else []
    out = {
        'hero': hero, 'stage': stage, 'seed': seed, 'end': end, 'sim_time': w.now if w else 0.0,
        'wall_s': round(wall, 1), 'frames': res.frames, 'exception': res.exception, 'invariant': st['inv'],
        'waves': [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in x.items()} for x in waves],
        'boss': [{k: round(v, 2) for k, v in b.items()} for b in boss_fights],
        'ult_ready': [round(x, 2) for x in ult_ready], 'ult_used': [round(x, 2) for x in ult_used],
        'charge_times': [round(x, 2) for x in charge], 'hold_times': [round(x, 2) for x in hold_t],
        'ult_gaps': [round(x, 2) for x in gaps],
        'deaths': deaths, 'captures': captures,
        'accuracy': round(hits / shots, 3) if shots else None, 'crit_rate': round(crits / hits, 3) if hits else None,
        'damage_out': round(dmg_out), 'heal_ab': round(heal_ab), 'barrier_absorbed': round(bar_abs),
        'barrier_dealt': round(bar_dealt), 'packs': packs,
        'ult_sources': {k: round(v) for k, v in st['src'].items()},
        'score': w.score if w else 0,
        'frame_ms_p50': _pct(frame_ms, 0.5), 'frame_ms_p95': _pct(frame_ms, 0.95),
        'perf_p95': {k: _pct([x[j] for x in perf], 0.95) for j, k in enumerate(('update', 'render', 'hud', 'total'))},
    }
    if tot:
        out['perf_p50_total'] = _pct(tot, 0.5)
    return out


def _fmt_run(r):
    wv = ' '.join('%d%s:%s%s' % (x['wave'], x['kind'][0].upper(),
                                 ('%.0f' % (x['t1'] - x['t0'])) if x['t1'] is not None else '-',
                                 '' if x['capture'] is None else ('+' if x['capture'] == 'captured' else 'x'))
                  for x in r['waves'])
    ct = r['charge_times']
    return ('%-7s s%d seed %d: %-11s t %5.0f s | waves %s | ults %d (charge med %s) | boss %s | acc %s crit %s '
            '| deaths %s | p95 %.1f ms' % (
                r['hero'], r['stage'], r['seed'], r['end'], r['sim_time'], wv, len(r['ult_used']),
                ('%.0f' % statistics.median(ct)) if ct else '-',
                ','.join('%.0f' % b['spawn_to_kill'] for b in r['boss']) or '-',
                r['accuracy'], r['crit_rate'],
                ','.join('w%s+%.0fs' % (d['wave'], d['into_wave'] or 0) for d in r['deaths']) or '0',
                r['frame_ms_p95'] or 0.0))


def aggregate(runs):
    by = {}
    for r in runs:
        by.setdefault(r['hero'], []).append(r)
    agg = {}
    for hero, rs in by.items():
        charge = [c for r in rs for c in r['charge_times']]
        gaps = [c for r in rs for c in r['ult_gaps']]
        wl = [x['t1'] - x['t0'] for r in rs for x in r['waves'] if x['t1'] is not None]
        wl_by_kind = {}
        for r in rs:
            for x in r['waves']:
                if x['t1'] is not None:
                    wl_by_kind.setdefault(x['kind'], []).append(x['t1'] - x['t0'])
        w3 = [x for r in rs for x in r['waves'] if (x['wave'] - 1) % 5 + 1 >= 3 and x['t1'] is not None]
        boss = [b['spawn_to_kill'] for r in rs for b in r['boss']]
        engage = [b['engage_to_kill'] for r in rs for b in r['boss']]
        caps = [c for r in rs for c in r['captures']]
        p95 = [r['frame_ms_p95'] for r in rs if r['frame_ms_p95'] is not None]
        agg[hero] = {
            'runs': len(rs),
            'cleared': sum(1 for r in rs if r['end'] == 'stage_clear'),
            'deaths': [('s%d/seed%d w%s +%.0fs by %s' % (r['stage'], r['seed'], d['wave'], d['into_wave'] or 0,
                                                          d['by'])) for r in rs for d in r['deaths']],
            'charge_median': statistics.median(charge) if charge else None,
            'charge_n': len(charge),
            'ult_gap_median': statistics.median(gaps) if gaps else None,
            'ults_per_wave_w3plus': (sum(x['ults'] for x in w3) / len(w3)) if w3 else None,
            'ult_ready_per_wave_w3plus': (sum(x['ults_ready'] for x in w3) / len(w3)) if w3 else None,
            'waves_w3plus_with_ult': (sum(1 for x in w3 if x['ults'] >= 1) / len(w3)) if w3 else None,
            'wave_median': statistics.median(wl) if wl else None,
            'wave_by_kind': {k: round(statistics.median(v), 1) for k, v in wl_by_kind.items()},
            'boss_median': statistics.median(boss) if boss else None,
            'boss_engage_median': statistics.median(engage) if engage else None,
            'boss_n': len(boss),
            'capture': '%d/%d' % (caps.count('captured'), len(caps)),
            'accuracy': statistics.mean([r['accuracy'] for r in rs if r['accuracy'] is not None] or [0]),
            'frame_p95_max': max(p95) if p95 else None,
            'frame_p95_median': statistics.median(p95) if p95 else None,
        }
        tot = {}
        for r in rs:
            for k, v in r.get('ult_sources', {}).items():
                tot[k] = tot.get(k, 0) + v
        allp = sum(tot.values()) or 1
        agg[hero]['ult_source_pct'] = {k: round(100.0 * v / allp) for k, v in tot.items()}
        agg[hero]['sim_minutes'] = round(sum(r['sim_time'] for r in rs) / 60.0, 1)
    return agg


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--heroes', default='vector,flicker,rampart')
    ap.add_argument('--stages', default='1,2,3')
    ap.add_argument('--seeds', default='1,2,3')
    ap.add_argument('--json', default=None)
    ap.add_argument('--shots', action='store_true')
    ap.add_argument('--no-assets', action='store_true')
    ap.add_argument('--max-seconds', type=float, default=900.0)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--trace', type=float, default=0.0, help='print the state every N sim seconds')
    ap.add_argument('--profile', default='good', choices=sorted(PROFILES))
    a = ap.parse_args(argv)
    BOT.update(PROFILES[a.profile])
    BOT['profile'] = a.profile
    _setup_paths(a.no_assets)
    import smoke
    smoke._no_power_throttling()
    h = smoke.Harness(shots=a.shots)
    runs = []
    for hero in a.heroes.split(','):
        for stage in [int(s) for s in a.stages.split(',')]:
            for seed in [int(s) for s in a.seeds.split(',')]:
                r = play(h, hero, stage, seed, a.max_seconds, a.shots, a.trace)
                runs.append(r)
                if r['exception']:
                    print('EXCEPTION', hero, stage, seed)
                    print(r['exception'])
                if r['invariant']:
                    print('INVARIANT', hero, stage, seed, r['invariant'])
                if not a.quiet:
                    print(_fmt_run(r), flush=True)
    agg = aggregate(runs)
    for hero, g in agg.items():
        print('%s: %s' % (hero, json.dumps(g, default=str)))
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump({'runs': runs, 'agg': agg, 'bot': {k: (v if not isinstance(v, float) else round(v, 4))
                                                         for k, v in BOT.items()}}, f, indent=1, default=str)
    bad = [r for r in runs if r['exception'] or r['invariant']]
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
