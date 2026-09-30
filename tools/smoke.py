"""Headless smoke harness (spec 9.1). FOUNDATION owns this file.

    python -X utf8 tools/smoke.py --suite foundation|campaign|perf|vector|flicker|rampart|enemies|hud|all
                                  [--shots] [--no-assets]

Each suite is tools/checks/check_<suite>.py. Every module-level function named
check_* is one check; it receives the Harness `h` and fails by raising
(AssertionError with a message). A check may return a short string that is
printed after PASS. Any exception or per-frame invariant violation inside a
run started by a check also fails that check. Output: one 'PASS <suite>: <check>'
or 'FAIL <suite>: <check>: <message>' line per check; exit code 1 on any FAIL.

Harness API for check modules (spec 9.1, plus a few helpers):
    h.run(hero='vector', frames=600, *, timeline=(), debug=None, setup=None, on_frame=None,
          seed=1, shots=(), name='run') -> Result
        debug defaults to {'god': True, 'skip_countdown': True, 'no_director': True} (merged).
        fixed_dt = 1/30. The player starts at (2.5, 7.5), angle 0 (east), pitch 0.
        Timeline entries: ('tap', f, action) | ('hold', f, action, n) | ('look', f, dx, dy)
                          | ('aim', f, angle, pitch) | ('call', f, fn(world))
        on_frame(world, i, state) runs after frame i; return 'stop' to end the run.
    h.spawn(world, kind, fwd, side=0.0, **attrs) -> Enemy   (relative to the player's facing, side > 0
        to the right; slides forward then sideways from the player and stops at walls, so it never spawns
        inside one; a clamp of more than 0.05 prints a NOTE line through h.log)
    h.place(world, x, y, angle=0.0, pitch=0.0)
    h.ROOMY = (9.5, 12.5, -pi/2)    h.place(w, *h.ROOMY) before spawning wide layouts (the default start
        is a 1-cell corridor); hero_contract() uses it
    h.tap_next(action, hold=1)      press on the next frame (use from on_frame)
    h.hero_contract(key)            generic hero contract (spec 9.3 step 1); raises on failure
    h.make_world(hero='vector', seed=1, debug=None) -> World (with WaveDirector, not running)
    h.screen                        the 1024x768 display surface
    h.save(surf, name)              write tools/out/<name>.png when --shots is given
    h.count_surfaces(on) / h.big_surfaces   Surface allocations >= 256x256 while counting (pygame.Surface
        is swapped for a counting subclass only while counting; isinstance(x, pygame.Surface) keeps working)
    h.log(msg)                      print an indented note under the current check
    Result: .world .events [(frame, name, data)] .exception .frame_ms .states .action .frames
            .count(name, **match) .first(name, **match) .total(name, key, **match) .where(name, **match)
            match values are plain (==) or callables (predicate on the payload value).
"""
import argparse
import asyncio
import importlib.util
import math
import os
import sys
import traceback
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.join(ROOT, 'game')
TOOLS = os.path.join(ROOT, 'tools')
CHECKS = os.path.join(TOOLS, 'checks')
OUT = os.path.join(TOOLS, 'out')
SUITES = ('foundation', 'campaign', 'perf', 'vector', 'flicker', 'rampart', 'enemies', 'hud')
FIXED_DT = 1.0 / 30.0


class CheckFailed(AssertionError):
    pass


class Result:
    def __init__(self, world, events, exception, frame_ms, states, action=None, frames=0, stats=None):
        self.world = world
        self.events = events
        self.exception = exception
        self.frame_ms = frame_ms
        self.states = states
        self.action = action
        self.frames = frames
        self.stats = stats

    @staticmethod
    def _match(d, match):
        for k, v in match.items():
            dv = d.get(k)
            if callable(v) and not isinstance(v, type):
                if not v(dv):
                    return False
            elif dv != v:
                return False
        return True

    def where(self, name, /, **match):
        return [d for f, n, d in self.events if n == name and self._match(d, match)]

    def count(self, name, /, **match):
        return len(self.where(name, **match))

    def first(self, name, /, **match):
        for f, n, d in self.events:
            if n == name and self._match(d, match):
                return d
        return None

    def total(self, name, key, /, **match):
        return sum(float(d.get(key) or 0.0) for d in self.where(name, **match))

    def frames_of(self, name, /, **match):
        return [f for f, n, d in self.events if n == name and self._match(d, match)]


class _Source:
    """input_source for app.run_match: synthesises real pygame events from a timeline."""

    def __init__(self, harness, timeline):
        import pygame
        from rwf import config as C
        self.pg = pygame
        self.C = C
        self.h = harness
        self.world = None
        self.frame = 0
        self.by_frame = defaultdict(list)
        for entry in timeline:
            self.add(entry)

    def _key_events(self, action):
        pg = self.pg
        for k, a in self.C.KEYMAP.items():
            if a == action:
                return (pg.event.Event(pg.KEYDOWN, key=k, mod=0, unicode='', scancode=0),
                        pg.event.Event(pg.KEYUP, key=k, mod=0, unicode='', scancode=0))
        for b, a in self.C.MOUSEMAP.items():
            if a == action:
                pos = (self.C.W // 2, self.C.H // 2)
                return (pg.event.Event(pg.MOUSEBUTTONDOWN, button=b, pos=pos),
                        pg.event.Event(pg.MOUSEBUTTONUP, button=b, pos=pos))
        raise ValueError('unknown action %r' % (action,))

    def add(self, entry):
        kind = entry[0]
        if kind in ('tap', 'hold'):
            f = int(entry[1])
            n = 1 if kind == 'tap' else max(1, int(entry[3]))
            down, up = self._key_events(entry[2])
            self.by_frame[f].append(('ev', down))
            self.by_frame[f + n].append(('ev', up))
        elif kind == 'look':
            pg = self.pg
            ev = pg.event.Event(pg.MOUSEMOTION, rel=(entry[2], entry[3]), pos=(self.C.W // 2, self.C.H // 2),
                                buttons=(0, 0, 0))
            self.by_frame[int(entry[1])].append(('ev', ev))
        elif kind == 'aim':
            ang, pitch = entry[2], entry[3]

            def fn(w, ang=ang, pitch=pitch):
                w.player.angle = ang
                w.player.pitch = pitch
                w._sync_camera()
            self.by_frame[int(entry[1])].append(('fn', fn))
        elif kind == 'call':
            self.by_frame[int(entry[1])].append(('fn', entry[2]))
        else:
            raise ValueError('unknown timeline entry %r' % (entry,))

    def events_for_frame(self, i):
        self.frame = i
        out = []
        for kind, x in self.by_frame.pop(i, ()):
            if kind == 'fn':
                x(self.world)
            else:
                out.append(x)
        return out


class Harness:
    def __init__(self, shots=False):
        import pygame
        self.pg = pygame
        self._install_counter()
        from rwf import app
        self.app = app
        self.screen = app.init_display()
        self.shots = shots
        self.runs = []
        self._src = None
        self.notes = []

    # --- surface counting (rule 12) ----------------------------------------------------
    def _install_counter(self):
        """pygame.Surface is swapped for a counting subclass ONLY between count_surfaces(True) and
        count_surfaces(False). Its metaclass keeps isinstance(x, pygame.Surface) True for every surface
        (also those made by transform/font/copy) while the swap is active, so game code behaves the same
        under the harness as in the shipped game."""
        pg = self.pg
        base = pg.Surface
        harness = self

        class _SurfaceMeta(type):
            def __instancecheck__(cls, obj):
                return isinstance(obj, base)

            def __subclasscheck__(cls, sub):
                return issubclass(sub, base)

        class CountingSurface(base, metaclass=_SurfaceMeta):
            def __init__(self, *a, **k):
                base.__init__(self, *a, **k)
                if harness._counting:
                    w, h = self.get_size()
                    if w >= 256 and h >= 256:
                        harness.big_surfaces += 1
        self._counting = False
        self.big_surfaces = 0
        self._base_surface = base
        self._counting_surface = CountingSurface

    def count_surfaces(self, on):
        if on and not self._counting:
            self.big_surfaces = 0
        self._counting = bool(on)
        self.pg.Surface = self._counting_surface if on else self._base_surface

    # --- helpers ---------------------------------------------------------------------
    def log(self, msg):
        self.notes.append(str(msg))
        print('      ' + str(msg))

    def save(self, surf, name):
        if not self.shots:
            return None
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, name + '.png')
        self.pg.image.save(surf, path)
        return path

    def make_world(self, hero='vector', seed=1, debug=None):
        from rwf import waves
        from rwf.world import World
        w = World(hero, seed=seed, debug=debug)
        w.director = waves.WaveDirector(w)
        self.place(w, 2.5, 7.5, 0.0, 0.0)
        return w

    def place(self, world, x, y, angle=0.0, pitch=0.0):
        p = world.player
        p.x, p.y, p.angle, p.pitch = float(x), float(y), float(angle), float(pitch)
        world._sync_camera()
        world.rebuild_flow()

    # Open floor for wide layouts: from (9.5, 12.5) facing north, the centre room spans x 8.0-12.0 for
    # y 8-12 (1.5 cells to the left, 2.5 to the right; side > 0 is to the right) and 5 cells ahead is the
    # open row y = 7.5. The default start (2.5, 7.5) facing east is a 1-cell corridor, so sideways offsets
    # there get clamped by walls (y 7.3-7.7 for a 0.3-radius dummy).
    ROOMY = (9.5, 12.5, -math.pi / 2)

    def spawn(self, world, kind, fwd, side=0.0, **attrs):
        """Spawn relative to the player's facing. Walls clamp the position (never inside a wall); a clamp
        of more than 0.05 is reported through h.log, so a layout that silently collapsed is visible."""
        from rwf.world import move_slide
        from rwf import core
        p = world.player
        a = p.angle
        r = getattr(core.ENEMY_TYPES[kind], 'radius', 0.3)
        x, y = move_slide(p.x, p.y, math.cos(a) * fwd, math.sin(a) * fwd, r)
        x, y = move_slide(x, y, -math.sin(a) * side, math.cos(a) * side, r)
        wx = p.x + math.cos(a) * fwd - math.sin(a) * side
        wy = p.y + math.sin(a) * fwd + math.cos(a) * side
        if math.hypot(x - wx, y - wy) > 0.05:
            self.log('NOTE: h.spawn(%s, fwd=%.2f, side=%.2f) from (%.2f, %.2f) was clamped by walls to '
                     '(%.2f, %.2f) instead of (%.2f, %.2f); use h.place(w, *h.ROOMY) for wide layouts'
                     % (kind, fwd, side, p.x, p.y, x, y, wx, wy))
        e = world.spawn_enemy(kind, x, y)
        e.angle = math.atan2(p.y - y, p.x - x)
        for k, v in attrs.items():
            setattr(e, k, v)
        return e

    def tap_next(self, action, hold=1):
        src = self._src
        if src is None:
            raise RuntimeError('tap_next() outside a run')
        src.add(('hold', src.frame + 1, action, hold))

    # --- invariants ------------------------------------------------------------------
    def _invariants(self, w):
        from rwf import config as C
        from rwf import core, render
        from rwf.world import is_wall
        from rwf.hero_base import HeroHUD
        p = w.player
        vals = [p.x, p.y, p.angle, p.pitch, p.ult_charge]
        pools = [('player', p.pool)]
        for e in w.enemies:
            vals += [e.x, e.y, e.angle]
            pools.append((e.KIND, e.pool))
        for _, pl in pools:
            vals += [pl.health, pl.armor, pl.shields]
        for v in vals:
            if v != v or v in (float('inf'), float('-inf')):
                return 'NaN/inf in positions, angles or pools'
        if is_wall(p.x, p.y):
            return 'player inside a wall at (%.2f, %.2f)' % (p.x, p.y)
        alive = 0
        for e in w.enemies:
            if e.alive:
                alive += 1
                if is_wall(e.x, e.y):
                    return '%s #%d inside a wall at (%.2f, %.2f)' % (e.KIND, e.id, e.x, e.y)
        if alive > C.CAP_ALIVE + C.CAP_SUMMONS:
            return 'alive enemies %d > cap' % alive
        if w.los_used > C.CAP_LOS_PER_FRAME:
            return 'LOS checks %d > %d per frame' % (w.los_used, C.CAP_LOS_PER_FRAME)
        for label, n, cap in (('projectiles', len(w.projectiles), C.CAP_PROJECTILES),
                              ('particles', len(w.particles), C.CAP_PARTICLES),
                              ('effects', len(w.effects), C.CAP_EFFECTS),
                              ('barriers', len(w.barriers), C.CAP_BARRIERS),
                              ('sprite cache', len(render._scaled), render.SPRITE_CACHE_SIZE),
                              ('text cache', len(core._text_cache), core.TEXT_CACHE_SIZE)):
            if n > cap:
                return '%s %d > cap %d' % (label, n, cap)
        if not (-1e-6 <= p.ult_charge <= p.ULT_COST + 1e-6):
            return 'ult_charge %.2f outside [0, %d]' % (p.ult_charge, p.ULT_COST)
        for label, pl in pools:
            for cur, mx, nm in ((pl.health, pl.max_health, 'health'), (pl.armor, pl.max_armor, 'armor'),
                                (pl.shields, pl.max_shields, 'shields')):
                if cur < -1e-6 or cur > mx + 1e-6:
                    return '%s %s %.2f outside [0, %.2f]' % (label, nm, cur, mx)
        if not (0 <= p.ammo <= p.MAX_AMMO):
            return 'ammo %r outside [0, %d]' % (p.ammo, p.MAX_AMMO)
        hs = p.hud_state(w)
        if not isinstance(hs, HeroHUD) or not (2 <= len(hs.abilities) <= 3):
            return 'hud_state() must be a HeroHUD with 2-3 abilities'
        return None

    # --- runs ------------------------------------------------------------------------
    def run(self, hero='vector', frames=600, *, timeline=(), debug=None, setup=None, on_frame=None,
            seed=1, shots=(), name='run'):
        dbg = {'god': True, 'skip_countdown': True, 'no_director': True}
        dbg.update(debug or {})
        src = _Source(self, timeline)
        self._src = src
        events = []
        inv = {'err': None}
        shots = set(shots or ())

        def _record(d):
            events.append((src.frame, d['event'], d))

        def _setup(world):
            src.world = world
            self.place(world, 2.5, 7.5, 0.0, 0.0)
            world.bus.on('*', _record)
            if setup is not None:
                setup(world)

        def _on_frame(world, i, state):
            src.world = world
            if inv['err'] is None:
                try:
                    err = self._invariants(world)
                except Exception:
                    err = 'invariant check raised: ' + traceback.format_exc().strip().splitlines()[-1]
                if err:
                    inv['err'] = 'invariant at frame %d (%s): %s' % (i, state, err)
            if self.shots and i in shots:
                self.save(self.screen, '%s_%04d' % (name, i))
            r = on_frame(world, i, state) if on_frame is not None else None
            if inv['err'] is not None:
                return 'stop'
            return r

        res = asyncio.run(self.app.run_match(self.screen, hero, input_source=src, fixed_dt=FIXED_DT,
                                             max_frames=frames, seed=seed, debug=dbg, setup=_setup,
                                             on_frame=_on_frame))
        self._src = None
        exc = res.exception or inv['err']
        r = Result(res.world, events, exc, res.frame_ms, res.states, res.action, res.frames, res.stats)
        self.runs.append((name, r))
        return r

    # --- generic hero contract (spec 9.3, step 1) --------------------------------------
    def hero_contract(self, key):
        import pygame
        seen = {'barrier': False}
        home_x, home_y, home_a = self.ROOMY

        def setup(w):
            self.place(w, home_x, home_y, home_a)       # room for the 3-wide layout (no wall clamping)
            for side in (-0.6, 0.0, 0.6):
                self.spawn(w, 'dummy', 4.0, side)

        def on_frame(w, i, st):
            if w.player_barrier() is not None:
                seen['barrier'] = True

        tl = [('hold', 10, 'fire', 60), ('hold', 100, 'alt', 20), ('tap', 150, 'ab1'), ('tap', 200, 'ab2'),
              ('look', 250, 150, 0), ('look', 262, -300, 0), ('look', 274, 150, 0), ('look', 286, 0, -40),
              ('look', 298, 0, 40), ('aim', 330, home_a, 0.0),
              ('tap', 400, 'ult'), ('hold', 450, 'fire', 40), ('tap', 520, 'reload'), ('tap', 560, 'melee'),
              ('tap', 700, 'melee')]
        r = self.run(key, 900, timeline=tl, debug={'inf_ult': True}, setup=setup, on_frame=on_frame,
                     name='contract_' + key)
        problems = []
        if r.exception:
            problems.append('exception: ' + r.exception.strip().splitlines()[-1])
        w = r.world
        if w is None:
            raise CheckFailed('; '.join(problems) or 'no world')
        hero = w.player
        need = {'primary', 'melee'} | set(hero.abilities)
        got = {d['slot'] for d in r.where('ability_used', hero=key)}
        if need - got:
            problems.append('no ability_used for %s' % sorted(need - got))
        alt_frames = [f for f in r.frames_of('ability_used', hero=key) if 100 <= f <= 125]
        if not alt_frames and not seen['barrier']:
            problems.append('alt did nothing (no ability_used in frames 100-125, no barrier raised)')
        if r.count('damage', source=lambda s: s is hero) < 1:
            problems.append('no damage dealt by the hero')
        if r.count('ult_used', hero=key) < 1:
            problems.append('no ult_used')
        surf = pygame.Surface((1024, 768))
        for fn in ('draw_viewmodel', 'draw_overlay', 'draw_crosshair'):
            try:
                getattr(hero, fn)(surf, w)
            except Exception:
                problems.append('%s raised %s' % (fn, traceback.format_exc().strip().splitlines()[-1]))
        for slot in ('portrait', 'secondary', 'ab1', 'ab2', 'ult'):
            for size in (52, 96):
                s = pygame.Surface((size, size))
                try:
                    type(hero).draw_icon(slot, s, s.get_rect())
                except Exception:
                    problems.append('draw_icon(%s, %d) raised %s' % (
                        slot, size, traceback.format_exc().strip().splitlines()[-1]))
        if problems:
            raise CheckFailed('%s contract: %s' % (key, '; '.join(problems)))
        return 'ability_used %s, damage events %d' % (sorted(got), r.count('damage', source=lambda s: s is hero))


# ============================ runner =========================================
def _no_power_throttling():
    """Windows 11 throttles background console processes (EcoQoS): Python then runs 2-3x slower
    and perf numbers mean nothing. The game itself runs in a foreground window/tab, so the
    harness opts out, to measure what a player gets. Set RWF_THROTTLED=1 to keep throttling."""
    if os.name != 'nt' or os.environ.get('RWF_THROTTLED'):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class _PPTS(ctypes.Structure):
            _fields_ = [('Version', wintypes.ULONG), ('ControlMask', wintypes.ULONG), ('StateMask', wintypes.ULONG)]
        st = _PPTS(1, 1, 0)             # PROCESS_POWER_THROTTLING_EXECUTION_SPEED off
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = wintypes.HANDLE
        return bool(k.SetProcessInformation(wintypes.HANDLE(k.GetCurrentProcess()), 4, ctypes.byref(st),
                                            ctypes.sizeof(st)))
    except Exception:
        return False


def _load_suite(suite):
    path = os.path.join(CHECKS, 'check_%s.py' % suite)
    if not os.path.exists(path):
        return None, 'tools/checks/check_%s.py not found (its builder has not delivered it yet)' % suite
    try:
        spec = importlib.util.spec_from_file_location('check_' + suite, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:
        return None, 'import failed: ' + traceback.format_exc().strip().splitlines()[-1]
    fns = [(getattr(mod, n).__code__.co_firstlineno, n, getattr(mod, n)) for n in dir(mod)
           if n.startswith('check_') and callable(getattr(mod, n))]
    fns.sort()
    return [(n, f) for _, n, f in fns], None


def run_suite(h, suite):
    checks, err = _load_suite(suite)
    if err:
        print('FAIL %s: %s' % (suite, err))
        return 0, 1
    passed = failed = 0
    for name, fn in checks:
        h.runs = []
        h.notes = []
        try:
            note = fn(h)
            bad = [(n, r) for n, r in h.runs if r.exception]
            if bad:
                n, r = bad[0]
                raise CheckFailed('run %r: %s' % (n, r.exception.strip().splitlines()[-1]))
            print('PASS %s: %s%s' % (suite, name, (' (%s)' % note) if note else ''))
            passed += 1
        except Exception as e:
            if isinstance(e, AssertionError):
                msg = str(e) or 'assertion failed'
            else:
                msg = traceback.format_exc().strip().splitlines()[-1]
            bad = [(n, r) for n, r in h.runs if r.exception]
            if bad and 'Traceback' in (bad[0][1].exception or ''):
                print(bad[0][1].exception)
            print('FAIL %s: %s: %s' % (suite, name, msg))
            failed += 1
    return passed, failed


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--suite', default='foundation', choices=SUITES + ('all',))
    ap.add_argument('--shots', action='store_true')
    ap.add_argument('--no-assets', action='store_true')
    args = ap.parse_args(argv)
    os.environ['SDL_VIDEODRIVER'] = 'dummy'
    os.environ['SDL_AUDIODRIVER'] = 'dummy'
    if args.no_assets:
        os.environ['RWF_NO_ASSETS'] = '1'
    if GAME not in sys.path:
        sys.path.insert(0, GAME)
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    if _no_power_throttling():
        print('note: Windows power throttling (EcoQoS) disabled for this process')
    h = Harness(shots=args.shots)
    suites = SUITES if args.suite == 'all' else (args.suite,)
    tp = tf = 0
    for s in suites:
        p, f = run_suite(h, s)
        tp += p
        tf += f
    print('%s: %d passed, %d failed%s' % ('OK' if tf == 0 else 'FAILED', tp, tf,
                                          ' (no assets)' if args.no_assets else ''))
    return 1 if tf else 0


if __name__ == '__main__':
    sys.exit(main())
