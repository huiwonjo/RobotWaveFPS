"""FOUNDATION acceptance (spec 9.2 items 1-9, plus unit checks builders rely on)."""
import ast
import math
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAME = os.path.join(ROOT, 'game')


def _game_py_files():
    out = []
    for base, dirs, files in os.walk(GAME):
        rel = os.path.relpath(base, GAME).replace('\\', '/')
        if rel == 'build' or rel.startswith('build/') or '__pycache__' in rel:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in ('build', '__pycache__')]
        for f in files:
            if f.endswith('.py'):
                out.append(os.path.join(base, f))
    return sorted(out)


FORBIDDEN = [
    (re.compile(r'^\s*(import|from)\s+(numpy|threading|subprocess)\b', re.M), 'import numpy/threading/subprocess'),
    (re.compile(r'\btime\.sleep\b'), 'time.sleep'),
    (re.compile(r'\bK_TAB\b'), 'K_TAB'),
    (re.compile(r'\bK_F\d+\b'), 'K_F<n>'),
    (re.compile(r'\bK_[LR](CTRL|ALT|META|GUI)\b'), 'Ctrl/Alt/Meta/GUI keys'),
    (re.compile(r'\bKMOD_'), 'KMOD_'),
    (re.compile(r'pygame\.mouse\.get_pressed'), 'pygame.mouse.get_pressed'),
]
FORBIDDEN_RWF = [(re.compile(r'\btime\.time\('), 'time.time(')]


def _async_sleep_ok(fn):
    has_while = any(isinstance(n, ast.While) for n in ast.walk(fn))
    if not has_while:
        return True
    for n in ast.walk(fn):
        if isinstance(n, ast.Await) and isinstance(n.value, ast.Call):
            f = n.value.func
            if (isinstance(f, ast.Attribute) and f.attr == 'sleep' and isinstance(f.value, ast.Name)
                    and f.value.id == 'asyncio' and n.value.args
                    and isinstance(n.value.args[0], ast.Constant) and n.value.args[0].value == 0):
                return True
    return False


def check_static(h):
    """9.5 items 1-5: ASCII, 3.12 syntax, forbidden names, async sleeps, game/ layout."""
    problems = []
    files = _game_py_files()
    assert files, 'no python files under game/'
    for path in files:
        rel = os.path.relpath(path, ROOT).replace('\\', '/')
        raw = open(path, 'rb').read()
        bad = [i for i, b in enumerate(raw) if b > 127]
        if bad:
            line = raw[:bad[0]].count(b'\n') + 1
            problems.append('%s:%d non-ASCII byte' % (rel, line))
            continue
        src = raw.decode('ascii')
        try:
            tree = ast.parse(src, filename=rel, feature_version=(3, 12))
        except SyntaxError as e:
            problems.append('%s:%s not valid Python 3.12 syntax: %s' % (rel, e.lineno, e.msg))
            continue
        rules = FORBIDDEN + (FORBIDDEN_RWF if '/rwf/' in '/' + rel else [])
        for rx, label in rules:
            m = rx.search(src)
            if m:
                problems.append('%s:%d forbidden %s' % (rel, src[:m.start()].count('\n') + 1, label))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and not _async_sleep_ok(node):
                problems.append('%s:%d async def %s has a while loop without await asyncio.sleep(0)'
                                % (rel, node.lineno, node.name))
    allowed = {'main.py', 'favicon.png', 'assets', 'rwf', 'build', '__pycache__'}
    for name in os.listdir(GAME):
        if name not in allowed:
            problems.append('game/ must only contain main.py, favicon.png, assets/, rwf/ (found %s)' % name)
    for name in ('platform.py', 'config.py'):
        if os.path.exists(os.path.join(GAME, name)):
            problems.append('game/%s shadows a module' % name)
    assert not problems, '; '.join(problems[:8])
    return '%d files' % len(files)


IMPORT_TIERS = [('config',), ('theme',), ('core',), ('world',), ('combat',), ('render',), ('hero_base',),
                ('hero_vector', 'hero_flicker', 'hero_rampart', 'enemies', 'waves'),
                ('hud', 'screens', 'stats', 'potg', 'sfx'), ('app',)]


def check_import_rules(h):
    """7.2: an rwf module imports only modules to its left; world never imports combat at module level."""
    tier = {m: i for i, grp in enumerate(IMPORT_TIERS) for m in grp}
    rwf = os.path.join(GAME, 'rwf')
    problems = []
    for f in sorted(os.listdir(rwf)):
        if not f.endswith('.py') or f == '__init__.py':
            continue
        me = f[:-3]
        if me not in tier:
            problems.append('rwf/%s is not in the 7.1 file list' % f)
            continue
        tree = ast.parse(open(os.path.join(rwf, f), encoding='ascii').read())
        for node in tree.body:
            mods = []
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                if node.module:
                    mods.append(node.module.split('.')[0])
                else:
                    mods += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('rwf'):
                mods.append(node.module.split('.')[1] if '.' in node.module else '')
            for m in mods:
                if m in tier and tier[m] >= tier[me]:
                    problems.append('rwf/%s imports %s (not to its left)' % (f, m))
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split('.')[0] in ('numpy', 'threading', 'subprocess'):
                        problems.append('rwf/%s imports %s' % (f, a.name))
    assert not problems, '; '.join(problems)


def check_web_build_archive(h):
    """Replaces 9.2 item 10: if a pygbag build exists, its game.apk ships main.py and every rwf/*.py."""
    apk = os.path.join(GAME, 'build', 'web', 'game.apk')
    if not os.path.exists(apk):
        return 'SKIP: run python -m pygbag --build game first'
    names = set(zipfile.ZipFile(apk).namelist())
    want = ['assets/main.py'] + ['assets/rwf/' + f for f in os.listdir(os.path.join(GAME, 'rwf'))
                                 if f.endswith('.py')]
    missing = [n for n in want if n not in names]
    assert not missing, 'game.apk is missing %s (stale build?)' % missing[:5]
    return '%d files in apk' % len(names)


def check_pool_math(h):
    from rwf.combat import HealthPool
    p = HealthPool(100, 50, 50)
    dealt = p.absorb(100, 0.0)
    assert abs(p.shields) < 1e-9 and abs(p.armor - 15) < 1e-6 and abs(p.health - 100) < 1e-6, \
        'absorb(100): %r %r %r' % (p.shields, p.armor, p.health)
    assert abs(dealt - 85) < 1e-6, 'absorb(100) dealt %r' % dealt
    p = HealthPool(100, 50, 50)
    dealt = p.absorb(200, 0.0)
    assert p.shields == 0 and p.armor == 0 and abs(p.health - 21.428571) < 1e-3, 'absorb(200): %r' % p.health
    assert abs(dealt - 178.571428) < 1e-3, 'absorb(200) dealt %r' % dealt
    p = HealthPool(100, 50, 0)
    p.absorb(120, 0.0)
    healed = p.heal(60)
    assert abs(p.health - 100) < 1e-6 and abs(healed - 60) < 1e-6 and p.armor > 0, 'heal order'
    p = HealthPool(100, 0, 50)
    p.absorb(30, 10.0)
    p.update(0.1, 12.9)
    assert abs(p.shields - 20) < 1e-9, 'shields regenerated at 2.9 s'
    p.update(0.1, 13.1)
    assert p.shields > 20, 'no shield regen at 3.1 s'
    p.add_max_shields(300)
    assert p.max_shields == 350 and p.shields > 320
    assert not HealthPool(10).dead and HealthPool(0).dead


def check_statuses(h):
    from rwf.combat import StatusSet
    s = StatusSet()
    s.add('stun', 2.0, 0.0)
    s.add('stun', 1.0, 0.5)
    assert s.has('stun', 1.9) and not s.has('stun', 2.01), 'stun keeps the max duration'
    assert not s.can_act(1.0) and not s.can_move(1.0) and s.can_act(2.5)
    s.add('root', 1.0, 3.0)
    assert s.can_act(3.5) and not s.can_move(3.5)
    s.add('slow', 1.5, 4.0, 0.6)
    s.add('slow', 0.5, 4.0, 0.8)
    assert abs(s.speed_mult(4.2) - 0.6) < 1e-9 and s.speed_mult(6.0) == 1.0
    s.add('invuln', 0.5, 7.0)
    assert s.taken_mult(7.2) == 0 and s.taken_mult(7.6) == 1
    assert 'invuln' in s.active(7.2)


def check_hitscan_geometry(h):
    """5.4: trooper-sized dummy 5 ahead: pitch 0 body, +20 crit, +60 miss above, -120 miss below."""
    from rwf.combat import hitscan, Barrier
    from rwf.config import TEAM_ENEMY
    w = h.make_world()
    d = h.spawn(w, 'dummy', 5.0)
    p = w.player
    res = {}
    for pitch in (0, 20, 60, -120):
        hit = hitscan(w, p, 0.0, pitch)
        res[pitch] = (hit.kind, hit.crit)
    assert res[0] == ('enemy', False), 'pitch 0: %r' % (res[0],)
    assert res[20] == ('enemy', True), 'pitch +20: %r' % (res[20],)
    assert res[60][0] != 'enemy', 'pitch +60 should miss: %r' % (res[60],)
    assert res[-120][0] != 'enemy', 'pitch -120 should miss: %r' % (res[-120],)
    hit = hitscan(w, p, 0.0, 0)
    assert abs(hit.dist - 5.0) < 0.05 and hit.target is d
    b = Barrier(TEAM_ENEMY, 400, 1.0)
    b.set_pose(p.x + 3.0, p.y, math.pi)
    w.add_barrier(b)
    hit = hitscan(w, p, 0.0, 0)
    assert hit.kind == 'barrier' and abs(hit.dist - 3.0) < 0.01, 'barrier: %r' % hit
    w.remove_barrier(b)
    hit = hitscan(w, p, math.pi, 0)
    assert hit.kind == 'wall' and abs(hit.dist - 1.5) < 0.01, 'wall behind: %r' % hit
    d.height_mult = 0.6          # stunned: drawn and hit-tested at 60% height
    assert hitscan(w, p, 0.0, 0).kind != 'enemy', 'eye level passes over a stunned trooper-sized target'
    hit = hitscan(w, p, 0.0, -20)
    assert hit.kind == 'enemy' and hit.crit, 'stunned head band: %r' % hit
    assert hitscan(w, p, 0.0, -60).kind == 'enemy'


def check_damage_pipeline(h):
    from rwf import combat
    w = h.make_world()
    ev = []
    w.bus.on('*', lambda d: ev.append(d))
    e = h.spawn(w, 'dummy', 3.0)
    e.pool = combat.HealthPool(50)
    e.SCORE = 10
    p = w.player
    dealt = combat.apply_damage(w, e, 30, p, ability='primary')
    assert dealt == 30 and p.ult_charge == 30, 'ult +1 per damage dealt'
    dmg = [d for d in ev if d['event'] == 'damage'][0]
    for k in ('target', 'source', 'amount', 'raw', 'crit', 'ability', 'killed', 'x', 'y', 'to_player'):
        assert k in dmg, 'damage payload lacks %s' % k
    dealt = combat.apply_damage(w, e, 100, p, ability='primary', crit=True)
    assert abs(dealt - 20) < 1e-9, 'no overkill in dealt (%r)' % dealt
    assert not e.alive and e.dying_until > w.now
    kill = [d for d in ev if d['event'] == 'kill'][0]
    for k in ('target', 'name', 'source', 'killer', 'ability', 'label', 'crit', 'score', 'boss', 'ult', 'x', 'y'):
        assert k in kill, 'kill payload lacks %s' % k
    assert kill['name'] == 'DUMMY' and kill['killer'] == p.NAME and kill['label'] == p.label_for('primary')
    assert kill['score'] == 10 + 5 and w.score == 15, 'score = SCORE x stage + 5 x stage crit (%r)' % kill['score']
    assert combat.apply_damage(w, e, 10, p) == 0, 'dead targets take nothing'
    # god mode: player_hurt with raw amount, no HP change
    w.debug['god'] = True
    hp = p.pool.health
    ev.clear()
    assert combat.apply_damage(w, p, 25, None, ability='bolt', from_xy=(5.0, 7.5)) == 0
    hurt = [d for d in ev if d['event'] == 'player_hurt']
    assert hurt and hurt[0]['amount'] == 25 and hurt[0]['from_x'] == 5.0 and p.pool.health == hp
    w.debug['god'] = False
    p.status.add('invuln', 0.5, w.now)
    assert combat.apply_damage(w, p, 25, None) == 0, 'invuln'
    p.status.clear()
    ev.clear()
    assert combat.apply_damage(w, p, 25, None, ability='bolt', from_xy=(5.0, 7.5)) == 25
    assert [d for d in ev if d['event'] == 'player_hurt'][0]['amount'] == 25


def check_barrier_rules(h):
    """Enemy melee through a player barrier hits the barrier; barriers give ult; broken barrier events."""
    from rwf import combat
    from rwf.config import TEAM_PLAYER, TEAM_ENEMY
    w = h.make_world()
    p = w.player
    ev = []
    w.bus.on('*', lambda d: ev.append(d['event']))
    b = combat.Barrier(TEAM_PLAYER, 600, 1.2, owner=p)
    b.set_pose(p.x + 1.0, p.y, 0.0)
    assert w.add_barrier(b) and w.player_barrier() is b
    assert not w.add_barrier(combat.Barrier(TEAM_PLAYER, 600, 1.2)), 'one player barrier max'
    src = h.spawn(w, 'dummy', 2.0)
    hp = p.pool.health
    assert combat.enemy_hits_player(w, src, 40, (src.x, src.y)) == 0
    assert p.pool.health == hp and abs(b.hp - 560) < 1e-6 and 'barrier_damage' in ev
    assert abs(p.ult_charge - 20) < 1e-6, 'owner gains 0.5 ult per HP absorbed'
    b.take(w, 1000, src)
    assert not b.active and 'barrier_broken' in ev
    eb = combat.Barrier(TEAM_ENEMY, 400, 1.0)
    eb.set_pose(p.x + 1.5, p.y, math.pi)
    w.add_barrier(eb)
    p.ult_charge = 0
    eb.take(w, 100, p)
    assert abs(p.ult_charge - 50) < 1e-6, 'damage to enemy barriers gives 0.5 ult per HP'
    for _ in range(3):
        w.add_barrier(combat.Barrier(TEAM_ENEMY, 400, 1.0))
    assert sum(1 for x in w.barriers if x.team == TEAM_ENEMY) == 3, 'three enemy barriers max'


def check_projectiles(h):
    """9.2 item 4: bolt into a player barrier -> barrier_damage, no player_hurt; 16 c/s never tunnels."""
    from rwf import combat
    from rwf.config import TEAM_PLAYER

    def setup(w):
        d = h.spawn(w, 'dummy', 5.0, fire_every=0.5)
        b = combat.Barrier(TEAM_PLAYER, 600, 1.2, owner=w.player)
        b.owner_view_only = True
        w.add_barrier(b)
        w._test_barrier = b

    def on_frame(w, i, st):
        p = w.player
        w._test_barrier.set_pose(p.x + 1.0, p.y, 0.0)

    r = h.run('vector', 150, setup=setup, on_frame=on_frame, debug={'god': False}, name='bolt_barrier')
    assert r.count('barrier_damage') >= 2, 'bolts did not hit the barrier (%d)' % r.count('barrier_damage')
    assert r.count('player_hurt') == 0, 'player hurt through the barrier'
    # tunnelling: 16 cells/s at 1/30 s = 0.53 cells per frame vs a 0.22-radius target
    w = h.make_world()
    e = h.spawn(w, 'dummy', 6.0, radius=0.22)
    p = w.player
    for off in (0.0, 0.13, 0.27, 0.41):
        e.pool = combat.HealthPool(1000)
        pr = combat.Projectile(p.x + off, p.y, 0.0, 16.0, team=TEAM_PLAYER, damage=10, radius=0.0, owner=p)
        w.add_projectile(pr)
        for _ in range(30):
            if not pr.alive:
                break
            pr.update(w, 1 / 30)
        assert e.pool.health < 1000, 'projectile tunnelled through the dummy (start offset %.2f)' % off
    # cap + eviction
    w = h.make_world()
    from rwf.config import TEAM_ENEMY, CAP_PROJECTILES
    for i in range(CAP_PROJECTILES):
        w.add_projectile(combat.Projectile(10, 7.5, math.pi, 1, team=TEAM_ENEMY, damage=1))
    assert not w.add_projectile(combat.Projectile(10, 7.5, math.pi, 1, team=TEAM_ENEMY, damage=1))
    assert w.add_projectile(combat.Projectile(3, 7.5, 0, 1, team=TEAM_PLAYER, damage=1))
    assert len(w.projectiles) == CAP_PROJECTILES


def check_splash_knockback_cone(h):
    from rwf import combat
    from rwf.config import TEAM_PLAYER, TEAM_ENEMY
    w = h.make_world()
    a = h.spawn(w, 'dummy', 5.0)
    b = h.spawn(w, 'dummy', 6.0)
    for e in (a, b):
        e.pool = combat.HealthPool(1000)
    hit = combat.splash(w, a.x, a.y, 1.5, 80, 40, w.player, TEAM_PLAYER, 'secondary', exclude=(a,))
    assert hit == [b] and abs((1000 - b.pool.health) - (80 - 40 * (1.0 / 1.5))) < 0.5, 'linear falloff'
    eb = combat.Barrier(TEAM_ENEMY, 400, 1.0)
    eb.set_pose(a.x + 0.5, a.y, math.pi)
    w.add_barrier(eb)
    hp = b.pool.health
    combat.splash(w, a.x, a.y, 1.5, 80, 40, w.player, TEAM_PLAYER, 'secondary', exclude=(a,))
    assert b.pool.health == hp, 'an enemy barrier shields its own team from splash'
    combat.splash(w, a.x, a.y, 1.5, 80, 40, w.player, TEAM_PLAYER, 'ult', exclude=(a,), ignore_barriers=True)
    assert b.pool.health < hp
    x0 = b.x
    combat.knockback(w, b, a.x, a.y, 0.6)
    assert b.x > x0 + 0.5, 'knockback moves away from the source'
    t = combat.cone_targets(w, w.player.x, w.player.y, 0.0, math.radians(45), 10.0)
    assert t and t[0] is a, 'cone_targets sorted nearest first'
    assert combat.cone_targets(w, w.player.x, w.player.y, math.pi, math.radians(45), 10.0) == []


def check_flow_field(h):
    from rwf.world import FlowField, OPEN_CELLS, is_wall, UNREACHABLE
    f = FlowField()
    f.rebuild(18, 18)
    assert f.dist(1.5, 1.5) < UNREACHABLE, 'no path (1.5,1.5) -> (18.5,18.5)'
    x, y = 1.5, 1.5
    for _ in range(200):
        vx, vy = f.toward(x, y)
        if vx == 0 and vy == 0:
            break
        x, y = x + vx * 0.25, y + vy * 0.25
        assert not is_wall(x, y), 'walking the flow entered a wall at (%.2f, %.2f)' % (x, y)
    assert int(x) == 18 and int(y) == 18, 'flow walk ended at (%.2f, %.2f)' % (x, y)
    for tx, ty in ((2, 7), (10, 10), (18, 1)):
        f.rebuild(tx, ty)
        for cx, cy in OPEN_CELLS:
            vx, vy = f.toward(cx, cy)
            if vx or vy:
                assert not is_wall(cx + vx * 0.5, cy + vy * 0.5), 'toward() points into a wall at %r' % ((cx, cy),)
                assert not is_wall(cx + vx, cy + vy)
            assert f.dist(cx, cy) < UNREACHABLE, 'unreachable open cell %r' % ((cx, cy),)


def check_movement_helpers(h):
    import random
    from rwf.world import move_slide, dash_target, is_wall, los, OPEN_CELLS, open_cells_far
    rng = random.Random(3)
    for _ in range(3000):
        x, y = rng.choice(OPEN_CELLS)
        for _ in range(5):
            a = rng.random() * 6.283
            d = rng.random() * 1.2
            x, y = move_slide(x, y, math.cos(a) * d, math.sin(a) * d, rng.choice((0.22, 0.25, 0.35, 0.45)))
            assert not is_wall(x, y), 'move_slide ended in a wall'
    x, y = dash_target(2.5, 7.5, 0.0, 3.5)
    assert abs(x - 6.0) < 0.11 and y == 7.5, 'blink in the open row: %r' % ((x, y),)
    x, y = dash_target(17.5, 7.5, 0.0, 3.5)
    assert x <= 18.75 and not is_wall(x, y), 'blink into the east wall: %r' % ((x, y),)
    for _ in range(500):
        cx, cy = rng.choice(OPEN_CELLS)
        x, y = dash_target(cx, cy, rng.random() * 6.283, 3.5)
        assert not is_wall(x, y)
    assert los(2.5, 7.5, 17.5, 7.5) and not los(2.5, 7.5, 2.5, 9.5)
    assert all((c[0] - 2.5) ** 2 + (c[1] - 7.5) ** 2 >= 49 for c in open_cells_far(2.5, 7.5, 7.0))


def check_input_and_bus(h):
    import pygame
    from rwf import core
    inp = core.InputState()
    inp.feed(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w))
    inp.feed(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
    inp.poll_keyboard()
    assert inp.down('fwd') and inp.hit('fwd') and inp.axes() == (1, 0)
    inp.end_frame()
    inp.feed(pygame.event.Event(pygame.KEYUP, key=pygame.K_w))
    inp.poll_keyboard()
    assert inp.down('fwd'), 'fwd still held by K_UP'
    inp.feed(pygame.event.Event(pygame.KEYUP, key=pygame.K_UP))
    inp.poll_keyboard()
    assert not inp.down('fwd') and inp.up('fwd')
    inp.end_frame()
    inp.feed(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=(0, 0)))
    inp.feed(pygame.event.Event(pygame.MOUSEMOTION, rel=(5, -3), pos=(0, 0), buttons=(0, 0, 1)))
    inp.poll_keyboard()
    assert inp.hit('alt') and inp.down('alt') and inp.mouse_dx == 5 and inp.mouse_dy == -3
    inp.clear()
    inp.poll_keyboard()
    assert not inp.held and inp.mouse_dx == 0
    clk = core.SimClock()
    bus = core.EventBus(clk)
    got = []
    bus.on('kill', lambda d: got.append(('kill', d['name'], d['event'])))
    bus.on('*', lambda d: got.append(('*', d['name'], d['event'])))
    clk.tick(0.02)
    bus.emit('kill', name='TROOPER')
    bus.emit('wave_clear', stage=1, wave=2)
    assert got == [('kill', 'TROOPER', 'kill'), ('*', 'TROOPER', 'kill'), ('*', 'wave_clear', 'wave_clear')], got
    clk.slowmo(0.35, 0.3)
    assert abs(clk.tick(0.02) - 0.007) < 1e-9
    for _ in range(20):
        clk.tick(0.02)
    assert clk.timescale == 1.0
    clk.paused = True
    n = clk.now
    assert clk.tick(0.02) == 0 and clk.now == n
    assert core.wrap_angle(3 * math.pi) == math.pi or abs(abs(core.wrap_angle(3 * math.pi)) - math.pi) < 1e-9
    assert core.text('HELLO', 'm') is core.text('HELLO', 'm'), 'text cache'


def check_world_hooks(h):
    """los budget, packs only when hurt, swap keeps ult, stage clear restores, burst cap."""
    from rwf import config as C
    w = h.make_world()
    for _ in range(C.CAP_LOS_PER_FRAME):
        w.los_budgeted(2.5, 7.5, 5.5, 7.5)
    assert w.los_budgeted(2.5, 7.5, 5.5, 7.5, default='X') == 'X'
    p = w.player
    pk = [k for k in w.packs if not k.big][0]
    h.place(w, pk.x, pk.y)
    pk.update(w, 0.03)
    assert pk.active, 'pack picked up at full health'
    p.pool.health = 100
    pk.update(w, 0.03)
    assert not pk.active and p.pool.health == 175
    p.ult_charge = p.ULT_COST
    new = w.set_hero('rampart', C.ULT_SWAP_KEEP)
    assert w.player is new and abs(new.ult_charge / new.ULT_COST - 0.30) < 1e-9
    new.pool.health = 10
    new.abilities['ab2'].use(w)
    w.bus.emit('stage_clear', stage=1)
    assert new.pool.health == new.pool.max_health and new.abilities['ab2'].charges == 2
    assert abs(new.ult_charge / new.ULT_COST - 0.30) < 1e-9, 'stage clear keeps ult'
    w.burst(5, 7.5, 0.5, 200, (255, 0, 0))
    assert len(w.particles) == C.CAP_PARTICLES


def check_clock_and_pause(h):
    """9.2 item 6: pause freezes world.now and enemies; a click resumes; time.time never called."""
    import time
    orig = time.time

    def boom():
        raise RuntimeError('time.time() called')
    rec = {}

    def setup(w):
        rec['e'] = h.spawn(w, 'trooper', 7.0)

    def on_frame(w, i, st):
        e = rec['e']
        if i == 32:
            rec['t32'] = (w.now, e.x, e.y, st)
        if i == 92:
            rec['t92'] = (w.now, e.x, e.y, st)
        if i == 130:
            rec['t130'] = (w.now, st)

    time.time = boom
    try:
        r = h.run('vector', 140, timeline=[('tap', 30, 'pause'), ('tap', 100, 'fire')], setup=setup,
                  on_frame=on_frame, name='pause')
    finally:
        time.time = orig
    assert rec['t32'][3] == 'PAUSED' and rec['t92'][3] == 'PAUSED', 'not paused: %r' % (rec['t32'][3],)
    assert rec['t32'][:3] == rec['t92'][:3], 'world moved while paused'
    assert rec['t130'][1] == 'PLAYING' and rec['t130'][0] > rec['t92'][0], 'click did not resume'
    assert r.count('shot') == 0, 'the resume click fired a shot'


def check_debug_hooks(h):
    w_ev = {}

    def on_frame(w, i, st):
        if i == 5:
            w_ev['ult'] = w.player.ult_ready
    r = h.run('flicker', 40, timeline=[('tap', 10, 'ab1'), ('tap', 12, 'ab1'), ('tap', 14, 'ab1'),
                                       ('tap', 16, 'ab1'), ('tap', 20, 'ult')],
              debug={'inf_ult': True, 'no_cooldowns': True, 'perf': True}, on_frame=on_frame, name='debug')
    assert w_ev['ult'], 'inf_ult: ult always ready'
    assert r.count('ability_used', slot='ab1') == 4, 'no_cooldowns: 4 blinks (%d)' % r.count('ability_used', slot='ab1')
    assert r.count('ult_used') == 1
    assert set(r.world.perf) >= {'update', 'render', 'hud', 'total'}, 'perf keys %r' % r.world.perf
    r = h.run('vector', 60, debug={'kill_player_at': 10, 'skip_end_screens': True}, name='kill_at')
    assert r.count('player_death') == 1 and r.action == 'death' and r.frames <= 12, 'skip_end_screens'


def check_registries_and_painters(h):
    import pygame
    from rwf import core, render
    assert sorted(core.HEROES) == ['flicker', 'rampart', 'vector'], sorted(core.HEROES)
    assert core.HERO_ORDER == ['vector', 'flicker', 'rampart']
    need = {'trooper', 'slicer', 'detonator', 'eradicator', 'warden', 'dummy'}
    assert need <= set(core.ENEMY_TYPES), 'ENEMY_TYPES %r' % sorted(core.ENEMY_TYPES)
    states = {
        'trooper': ('idle', 'move', 'windup', 'attack', 'stun'),
        'slicer': ('idle', 'move', 'windup', 'lunge', 'stun'),
        'detonator': ('idle', 'move', 'armed_a', 'armed_b', 'stun'),
        'eradicator': ('idle', 'move', 'attack', 'stun'),
        'warden': ('recon', 'recon_attack', 'sentry_windup', 'sentry', 'stomp_windup', 'stun'),
        'dummy': ('idle',), 'pack_small': ('idle',), 'pack_big': ('idle',),
    }
    for key, sts in states.items():
        assert key in render.PAINTERS, 'no painter for %s' % key
        fn, bw, bh = render.PAINTERS[key]
        for st in sts + ('no_such_state',):
            for elite in (False, True):
                s = pygame.Surface((bw, bh), pygame.SRCALPHA)
                fn(s, st, elite)
                s = render.paint_base(key, st, elite, 'f')
                assert s.get_size() == (bw, bh)
    for key in render.PAINTERS:
        fn, bw, bh = render.PAINTERS[key]
        fn(pygame.Surface((bw, bh), pygame.SRCALPHA), 'idle', False)
    for kind, cls in core.ENEMY_TYPES.items():
        for a in ('KIND', 'SCORE', 'BASE_HEALTH', 'BASE_SPEED', 'radius', 'height', 'width', 'head_band'):
            assert hasattr(cls, a), '%s lacks %s' % (kind, a)
    return '%d painters' % len(render.PAINTERS)


def check_enemy_stats(h):
    """4.2 table and 4.3 scaling on spawn."""
    from rwf import core
    table = {'trooper': (75, 0, 0, 1.8, 0.25, 0.70, 0.44, (0.00, 0.20), 10),
             'slicer': (40, 0, 40, 3.4, 0.22, 0.46, 0.36, (0.00, 0.30), 15),
             'detonator': (100, 100, 0, 1.6, 0.30, 0.58, 0.56, (0.30, 0.55), 15),
             'eradicator': (150, 0, 100, 1.3, 0.35, 0.80, 0.66, (0.00, 0.18), 30),
             'warden': (800, 600, 0, 1.1, 0.45, 1.00, 0.90, (0.35, 0.55), 150)}
    for kind, (hp, ar, sh, sp, r, ht, wd, band, score) in table.items():
        c = core.ENEMY_TYPES[kind]
        got = (c.BASE_HEALTH, c.BASE_ARMOR, c.BASE_SHIELDS, c.BASE_SPEED, c.radius, c.height, c.width,
               tuple(c.head_band), c.SCORE)
        assert got == (hp, ar, sh, sp, r, ht, wd, band, score), '%s stats %r' % (kind, got)
    assert core.ENEMY_TYPES['warden'].BOSS and not core.ENEMY_TYPES['warden'].PINNABLE
    assert core.ENEMY_TYPES['warden'].STUN_MULT == 0.4
    w = h.make_world()
    w.director.stage = 3
    e = w.spawn_enemy('trooper', 10.5, 7.5, elite=True)
    assert abs(e.pool.max_health - 75 * 1.3 * 1.6) < 1e-6 and abs(e.dmg_mult - 1.3) < 1e-9
    assert abs(e.speed - 1.8 * 1.1 * 1.2) < 1e-9 and e.NAME == 'TROOPER'


def check_hero_attrs(h):
    """3.4 class attributes the select screen and HUD read."""
    from rwf import core
    want = {'vector': ('VECTOR', 'DAMAGE', 1, 200, 0, 0, 4.2, 1500, 'LOCK-ON', 'LOCKED ON!', 30, 1.5),
            'flicker': ('FLICKER', 'DAMAGE', 3, 150, 0, 0, 4.6, 1100, 'PULSE BOMB', 'BOMB AWAY!', 40, 1.0),
            'rampart': ('RAMPART', 'TANK', 2, 300, 200, 0, 3.9, 1400, 'QUAKE SLAM', 'QUAKE!', 0, 0)}
    for key, t in want.items():
        c = core.HEROES[key]
        got = (c.NAME, c.ROLE, c.DIFFICULTY, c.HEALTH, c.ARMOR, c.SHIELDS, c.SPEED, c.ULT_COST, c.ULT_NAME,
               c.ULT_CALLOUT, c.MAX_AMMO, c.RELOAD_TIME)
        assert got == t, '%s attrs %r' % (key, got)
        assert len(c.KIT) == 5 and c.KEY == key and c.LABELS.get('melee', 'MELEE') == 'MELEE'
    assert core.HEROES['vector'].HUD_ORDER == ('ab1', 'ab2', 'secondary')
    assert core.HEROES['flicker'].HUD_ORDER == ('ab1', 'ab2')
    assert core.HEROES['rampart'].HUD_ORDER == ('ab1', 'ab2', 'secondary')


def check_screens_draw(h):
    from rwf import screens
    w = h.make_world()
    from rwf.stats import MatchStats
    st = MatchStats(w)
    surf = h.screen
    objs = [screens.TitleScreen(), screens.HeroSelectScreen('flicker'), screens.CountdownOverlay(3.0),
            screens.PauseOverlay(w, st, surf.copy()), screens.IntermissionOverlay(w), screens.EndBanner(True),
            screens.EndBanner(False), screens.PotgScreen({'frames': [], 'hero': 'vector', 'kills': 0, 'span': 0.0,
                                                          'kill_frames': []}),
            screens.SummaryScreen(w, st, 'vector')]
    for o in objs:
        o.update(1 / 30)
        o.draw(surf)
        h.save(surf, 'screen_' + type(o).__name__)
    assert st.rank(2000)[0] == 'A' and st.rank(299)[0] == 'D' and st.rank(5000)[0] == 'S'


def check_screen_flow(h):
    """9.2 item 8: COUNTDOWN -> PLAYING -> death -> END_BANNER -> (POTG) -> SUMMARY via Enter."""
    tl = [('tap', f, 'confirm') for f in range(200, 400, 20)]
    r = h.run('vector', 420, timeline=tl, debug={'skip_countdown': False, 'no_director': False,
                                                 'kill_player_at': 150}, name='flow', shots=(60, 160, 260))
    seen = []
    for s in r.states:
        if not seen or seen[-1] != s:
            seen.append(s)
    for s in ('COUNTDOWN', 'PLAYING', 'END_BANNER', 'SUMMARY'):
        assert s in seen, 'state %s never reached: %r' % (s, seen)
    order = [s for s in seen if s in ('COUNTDOWN', 'PLAYING', 'END_BANNER', 'POTG', 'SUMMARY')]
    assert order[:3] == ['COUNTDOWN', 'PLAYING', 'END_BANNER'], order
    assert r.action == 'again', 'Enter on SUMMARY should return again (got %r)' % r.action
    assert r.count('wave_start') >= 1, 'the director never started after the countdown'
    return ' -> '.join(seen)


def check_intermission_swap_and_endmatch(h):
    """Pause -> X ends the match; hero swap only through the intermission overlay."""
    tl = [('tap', 20, 'pause'), ('tap', 30, 'end_match')]
    r = h.run('vector', 120, timeline=tl, name='end_match')
    assert 'END_BANNER' in r.states and 'SUMMARY' in r.states, 'X on the pause screen should end the match'
    r = h.run('vector', 30, timeline=[('tap', 5, 'hero2')], name='no_swap_midwave')
    assert r.world.player.KEY == 'vector', 'swapped outside the intermission'


def check_hero_contracts(h):
    notes = []
    for key in ('vector', 'flicker', 'rampart'):
        h.hero_contract(key)
        notes.append(key)
    return 'contract ok for ' + ', '.join(notes)
