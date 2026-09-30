"""FLICKER acceptance checks (spec 9.3, HERO_B; kit numbers from 3.2 / 3.4). HERO_B owns this file.

    python -X utf8 tools/smoke.py --suite flicker [--shots] [--no-assets]

Every run uses the harness defaults (god, skip_countdown, no_director, fixed dt 1/30) unless a check says
otherwise. The player starts at (2.5, 7.5) facing east in the open row y = 7.5 (x 1..19).
"""
import math

DT = 1.0 / 30.0


def _hf():
    from rwf import hero_flicker
    return hero_flicker


def _events(r, name, pred=None):
    """[(frame, payload)] of one event, optionally filtered by pred(payload)."""
    return [(f, d) for f, n, d in r.events if n == name and (pred is None or pred(d))]


def _in_wall_footprint(x, y, r=0.25):
    from rwf.world import is_wall
    return is_wall(x - r, y - r) or is_wall(x + r, y - r) or is_wall(x - r, y + r) or is_wall(x + r, y + r)


# ============================ contract / attributes ===========================
def check_flicker_contract(h):
    """9.3 step 1: the generic hero contract."""
    return h.hero_contract('flicker')


def check_flicker_attrs(h):
    """3.2 / 3.4: class attributes, slots, HUD order, labels, kit rows, TUNING numbers."""
    from rwf import core
    hf = _hf()
    c = core.HEROES['flicker']
    assert c is hf.Flicker, 'registry does not hold hero_flicker.Flicker'
    got = (c.KEY, c.NAME, c.ROLE, c.DIFFICULTY, tuple(c.COLOR), c.HEALTH, c.ARMOR, c.SHIELDS, c.SPEED, c.ULT_COST,
           c.ULT_NAME, c.ULT_CALLOUT, c.MAX_AMMO, c.RELOAD_TIME, tuple(c.HUD_ORDER), c.BLURB)
    want = ('flicker', 'FLICKER', 'DAMAGE', 3, (255, 150, 40), 150, 0, 0, 4.6, 1210, 'PULSE BOMB', 'BOMB AWAY!',
            40, 1.0, ('ab1', 'ab2'), 'Blink through fights, rewind mistakes.')
    assert got == want, 'attrs %r' % (got,)
    keys = [k for k, _, _ in c.KIT]
    names = [n for _, n, _ in c.KIT]
    assert keys == ['LMB', 'RMB/F', 'E', 'V', 'Q'], 'KIT keys %r' % keys
    assert names[0] == 'TWIN PISTOLS' and names[1].startswith('BLINK') and names[2] == 'REWIND' \
        and names[3] == 'QUICK MELEE' and names[4] == 'PULSE BOMB', 'KIT names %r' % names
    assert 'SHIFT' in c.KIT[1][2] and '3' in c.KIT[1][1], 'the BLINK row must say SHIFT and 3 charges'
    for row in c.KIT:
        for s in row:
            assert all(ord(ch) < 128 for ch in s), 'non-ASCII KIT text %r' % (s,)
    w = h.make_world('flicker')
    p = w.player
    assert (p.label_for('primary'), p.label_for('ult'), p.label_for('melee')) == ('PISTOLS', 'PULSE BOMB', 'MELEE')
    assert sorted(p.abilities) == ['ab1', 'ab2'], 'abilities %r (no separate secondary entry)' % sorted(p.abilities)
    b, rw = p.abilities['ab1'], p.abilities['ab2']
    assert (b.name, b.key_label, b.max_charges, b.charges, b.cooldown) == ('BLINK', 'SHIFT', 3, 3, 3.0), \
        'blink slot %r' % ((b.name, b.key_label, b.max_charges, b.charges, b.cooldown),)
    assert (rw.name, rw.key_label, rw.max_charges, rw.cooldown) == ('REWIND', 'E', 1, 12.0), 'rewind slot'
    hs = p.hud_state(w)
    assert [a.slot for a in hs.abilities] == ['ab1', 'ab2'] and hs.abilities[0].max_charges == 3
    assert (hs.ammo, hs.max_ammo) == (40, 40)
    T = hf.TUNING
    want_t = {'pistol_damage': 12.0, 'pistol_interval': 0.05, 'pistol_falloff': (5.0, 10.0, 0.5),
              'pistol_spread': 0.014, 'blink_charges': 3, 'blink_cd': 3.0, 'blink_dist': 3.5, 'blink_step': 0.1,
              'blink_margin': 0.3, 'blink_fx': 0.12, 'rewind_cd': 12.0, 'rewind_samples': 30, 'rewind_hz': 10.0,
              'rewind_time': 0.5, 'bomb_speed': 12.0, 'bomb_radius': 0.25, 'bomb_range': 6.0, 'bomb_fuse': 1.0,
              'bomb_blast_r': 2.5, 'bomb_stuck_damage': 350.0, 'bomb_center': 350.0, 'bomb_edge': 105.0,
              'bomb_beep': 0.2, 'bomb_ring_hz': 8.0, 'bomb_shake': (8.0, 0.3), 'kick_px': 30.0}
    bad = {k: T.get(k) for k, v in want_t.items() if T.get(k) != v}
    assert not bad, 'TUNING differs from spec 3.2: %r' % bad


# ============================ TWIN PISTOLS ===================================
def check_flicker_pistol_rate(h):
    """20 shots/s from a 1.0 s hold, guns alternating, one 'shot' + 'ability_used' primary per shot."""
    st = {'guns': [0, 0], 'prev': None}

    def setup(w):
        st['d'] = h.spawn(w, 'dummy', 4.0)

    def on_frame(w, i, s):
        g = tuple(w.player.gun_fired)
        if st['prev'] is not None:
            for k in (0, 1):
                if g[k] != st['prev'][k]:
                    st['guns'][k] += 1
        st['prev'] = g

    r = h.run('flicker', 60, timeline=[('hold', 10, 'fire', 30)], setup=setup, on_frame=on_frame,
              name='fl_rate', shots=(11, 12))
    hero = r.world.player
    shots = r.frames_of('shot', hero='flicker')
    assert len(shots) == 20, '1.0 s of fire gave %d shots, want 20' % len(shots)
    assert shots[0] == 10 and shots[-1] <= 39, 'shots outside the hold: %r' % shots[:3]
    per = {}
    for f in shots:
        per[f] = per.get(f, 0) + 1
    assert max(per.values()) == 1, 'at 30 fps at most one trace per frame'
    assert st['guns'] == [10, 10], 'guns must alternate: shots per gun %r' % st['guns']
    assert r.count('ability_used', hero='flicker', slot='primary') == 20, 'ability_used primary per shot'
    assert hero.ammo == 20, 'ammo %d after 20 shots' % hero.ammo
    dmg = [d['amount'] for d in r.where('damage', source=lambda s: s is hero)]
    assert len(dmg) >= 18 and all(abs(a - 12.0) < 1e-9 or abs(a - 24.0) < 1e-9 for a in dmg), \
        'damage at 4 cells: %r' % sorted(set(round(a, 3) for a in dmg))
    return '%d shots in 1.0 s, guns %r, %d hits' % (len(shots), st['guns'], len(dmg))


def check_flicker_accumulator(h):
    """Frame times above 0.05 s still give 20 shots/s: several traces in one frame (direct handle_input)."""
    import pygame
    from rwf import core
    out = []
    for dt, frames in ((0.15, 4), (1.0 / 12.0, 13)):
        w = h.make_world('flicker')
        p = w.player
        shots = []
        w.bus.on('shot', shots.append)
        inp = core.InputState()
        inp.feed(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(512, 384)))
        per = []
        for _ in range(frames):
            w.dt = dt
            n0 = len(shots)
            p.handle_input(inp, w)
            per.append(len(shots) - n0)
            inp.end_frame()
        # the press frame banks one shot; after that dt / 0.05 traces per frame
        want = 1 + int(round((frames - 1) * dt / 0.05))
        assert sum(per) == want, 'dt %.3f: %d shots over %d frames (%r), want %d' % (dt, sum(per), frames, per, want)
        if dt == 0.15:
            assert per == [1, 3, 3, 3], 'dt 0.15: shots per frame %r, want [1, 3, 3, 3]' % per
        out.append('dt %.3f -> %r' % (dt, per))
    return '; '.join(out)


def check_flicker_spread(h):
    """Random yaw within +-0.014 rad (0.8 deg): wall hits 16.5 cells away stay within +-0.231 of the aim line."""
    r = h.run('flicker', 50, timeline=[('hold', 10, 'fire', 30)], name='fl_spread')
    walls = r.where('shot', hero='flicker', kind='wall')
    assert len(walls) >= 18, 'only %d wall shots' % len(walls)
    offs = [abs(d['y'] - 7.5) for d in walls]
    lim = 16.5 * math.tan(0.014) + 1e-6
    assert max(offs) <= lim, 'yaw spread too wide: %.4f > %.4f' % (max(offs), lim)
    assert max(offs) > 0.03, 'no spread at all (max offset %.4f)' % max(offs)
    return 'max lateral offset %.3f of %.3f' % (max(offs), lim)


def check_flicker_reload(h):
    """Mag 40; the reload starts on its own when the mag empties with fire held; 1.0 s; no fire while
    reloading; R with a full mag is a no-op."""
    rec = {}

    def on_frame(w, i, s):
        rec[i] = (w.player.ammo, w.player.reloading)

    r = h.run('flicker', 130, timeline=[('hold', 10, 'fire', 110)], on_frame=on_frame, name='fl_reload')
    shots = r.frames_of('shot', hero='flicker')
    r0 = min(i for i, v in rec.items() if v[1])
    r1 = min(i for i, v in rec.items() if i > r0 and not v[1])
    first = [f for f in shots if f <= r0]
    assert len(first) == 40, 'first mag gave %d shots' % len(first)
    assert rec[r0][0] == 0 and shots.count(r0) >= 1, 'the reload must start on the frame the mag empties'
    assert 0.95 <= (r1 - r0) * DT <= 1.05, 'reload took %.3f s' % ((r1 - r0) * DT)
    assert rec[r1][0] == 40, 'ammo %d after the reload' % rec[r1][0]
    assert not [f for f in shots if r0 < f <= r1], 'fired while reloading'
    assert [f for f in shots if f > r1], 'fire did not resume after the reload'

    rec2 = {}

    def on_frame2(w, i, s):
        rec2[i] = (w.player.ammo, w.player.reloading)

    tl = [('tap', 5, 'reload'), ('hold', 10, 'fire', 5), ('tap', 20, 'reload'), ('hold', 25, 'fire', 10)]
    r2 = h.run('flicker', 60, timeline=tl, on_frame=on_frame2, name='fl_reload2')
    assert not any(rec2[i][1] for i in range(5, 10)), 'R with a full mag started a reload'
    assert rec2[20][1], 'R with a partial mag did not reload'
    s2 = r2.frames_of('shot', hero='flicker')
    assert not [f for f in s2 if 20 <= f < 49], 'fired while reloading (manual reload)'
    done = min(i for i in range(21, 60) if not rec2[i][1])
    assert rec2[done][0] == 40 and 0.95 <= (done - 20) * DT <= 1.05, 'manual reload %d frames' % (done - 20)
    return '40 shots, auto reload %.2f s, manual reload %.2f s' % ((r1 - r0) * DT, (done - 20) * DT)


def _falloff(h, fwd, pitch, spread=None, name='fl_falloff'):
    st = {}

    def setup(w):
        st['d'] = h.spawn(w, 'dummy', fwd)
        if spread is not None:
            w.player.spread = spread

    r = h.run('flicker', 45, timeline=[('aim', 5, 0.0, pitch), ('hold', 10, 'fire', 30)], setup=setup, name=name)
    hero = r.world.player
    d = st['d']
    evs = r.where('damage', source=lambda s: s is hero, target=lambda t: t is d)
    return [e['amount'] for e in evs if not e['crit']], [e['amount'] for e in evs if e['crit']]


def check_flicker_falloff(h):
    """9.3: 12 per body hit at 3 cells; 6.6-7.2 at 9 cells. Also 9.0 at 7.5 cells and 6.0 beyond 10."""
    body, crit = _falloff(h, 3.0, 0.0, name='fl_fall3')
    assert len(body) >= 15, 'only %d body hits at 3 cells' % len(body)
    assert all(abs(a - 12.0) < 1e-9 for a in body), 'body damage at 3 cells %r' % sorted(set(body))
    assert all(abs(a - 24.0) < 1e-9 for a in crit), 'crit damage at 3 cells %r' % sorted(set(crit))
    # 9 cells, aimed low so every shot is a body hit. Spread off: the along-ray distance is exactly 9.
    b9, _ = _falloff(h, 9.0, -25.0, spread=0.0, name='fl_fall9')
    assert len(b9) >= 15 and all(6.6 <= a <= 7.2 for a in b9), 'body damage at 9 cells %r' % sorted(set(b9))
    # the same with the real +-0.8 deg spread: the hit distance along a slanted ray is up to 0.01% shorter,
    # so allow the spec range at 0.005 precision
    b9s, _ = _falloff(h, 9.0, -25.0, name='fl_fall9s')
    assert len(b9s) >= 15 and all(6.595 <= a <= 7.205 for a in b9s), \
        'body damage at 9 cells with spread %.4f-%.4f' % (min(b9s), max(b9s))
    b75, _ = _falloff(h, 7.5, -20.0, spread=0.0, name='fl_fall75')
    assert b75 and all(abs(a - 9.0) < 1e-9 for a in b75), 'damage at 7.5 cells %r' % sorted(set(b75))
    b12, _ = _falloff(h, 12.0, -15.0, spread=0.0, name='fl_fall12')
    assert b12 and all(abs(a - 6.0) < 1e-9 for a in b12), 'damage at 12 cells %r' % sorted(set(b12))
    return '3 cells %.1f (crit %s); 9 cells %.3f-%.3f (spread %.4f-%.4f); 7.5 cells %.1f; 12 cells %.1f' % (
        body[0], '%.0f' % crit[0] if crit else '-', min(b9), max(b9), min(b9s), max(b9s), b75[0], b12[0])


# ============================ BLINK ==========================================
def check_flicker_blink_distance(h):
    """9.3: 3.5 +- 0.1 in the open row; through an enemy; RMB/F triggers the same Blink; direction from
    WASD relative to the view (forward with no input)."""
    from rwf.world import is_wall
    st = {}

    def setup(w):
        st['d'] = h.spawn(w, 'dummy', 1.5)

    def on_frame(w, i, s):
        p = w.player
        if i in (4, 5, 9, 10):
            st[i] = (p.x, p.y)

    r = h.run('flicker', 20, timeline=[('tap', 5, 'ab1'), ('tap', 10, 'alt')], setup=setup, on_frame=on_frame,
              name='fl_blink', shots=(5, 6))
    d1 = math.hypot(st[5][0] - st[4][0], st[5][1] - st[4][1])
    assert abs(d1 - 3.5) <= 0.1 and abs(st[5][1] - 7.5) < 1e-6 and st[5][0] > st[4][0], \
        'blink moved %.3f to %r' % (d1, st[5])
    assert st[5][0] > st['d'].x + 1.0, 'blink must pass through the dummy'
    d2 = math.hypot(st[10][0] - st[9][0], st[10][1] - st[9][1])
    assert abs(d2 - 3.5) <= 0.1, 'alt (RMB/F) blink moved %.3f' % d2
    ab = r.where('ability_used', hero='flicker', slot='ab1')
    assert len(ab) == 2 and r.count('sfx', name='blink') == 2, 'ab1 used %d times' % len(ab)
    assert r.world.player.abilities['ab1'].charges == 1

    # direction: right / left while facing north, back while facing east
    got = {}

    def on_frame2(w, i, s):
        p = w.player
        if i in (5, 10, 16) and p.blink_to is not None:
            got[i] = (p.blink_to[0] - p.blink_from[0], p.blink_to[1] - p.blink_from[1])
        assert not is_wall(p.x, p.y)

    def setup2(w):
        h.place(w, 9.5, 7.5, -math.pi / 2)

    tl = [('hold', 4, 'right', 3), ('tap', 5, 'ab1'), ('hold', 9, 'left', 3), ('tap', 10, 'ab1'),
          ('aim', 13, 0.0, 0.0), ('hold', 15, 'back', 3), ('tap', 16, 'ab1')]
    h.run('flicker', 22, timeline=tl, setup=setup2, on_frame=on_frame2, name='fl_blink_dir')
    want = {5: (3.5, 0.0), 10: (-3.5, 0.0), 16: (-3.5, 0.0)}
    for i, (wx, wy) in want.items():
        assert i in got, 'no blink recorded at frame %d' % i
        gx, gy = got[i]
        assert abs(gx - wx) <= 0.1 and abs(gy - wy) <= 0.1, 'blink at %d went (%.2f, %.2f), want (%.1f, %.1f)' % (
            i, gx, gy, wx, wy)
    return 'fwd %.2f, alt %.2f, right/left/back ok' % (d1, d2)


def check_flicker_blink_wall(h):
    """9.3: facing the east wall from (17.5, 7.5): ends with x <= 18.75 and never in a wall."""
    from rwf.world import is_wall
    st = {'bad': []}

    def setup(w):
        h.place(w, 17.5, 7.5, 0.0)

    def on_frame(w, i, s):
        p = w.player
        if is_wall(p.x, p.y) or _in_wall_footprint(p.x, p.y, 0.24):
            st['bad'].append((i, p.x, p.y))
        st[i] = (p.x, p.y)

    tl = [('tap', 5, 'ab1'), ('tap', 8, 'ab1'), ('aim', 10, math.pi / 4, 0.0), ('tap', 11, 'ab1')]
    r = h.run('flicker', 16, timeline=tl, setup=setup, on_frame=on_frame, name='fl_blink_wall')
    x5 = st[5][0]
    assert x5 <= 18.75 and x5 > 18.2, 'blink into the east wall ended at x %.3f' % x5
    assert abs(st[8][0] - x5) < 0.11, 'a second blink into the wall moved %.3f' % (st[8][0] - x5)
    assert not st['bad'], 'in a wall: %r' % st['bad'][:3]
    assert r.count('ability_used', hero='flicker', slot='ab1') == 3
    return 'ended at x %.2f (<= 18.75); diagonal into the corner at (%.2f, %.2f)' % (x5, st[11][0], st[11][1])


def check_flicker_blink_charges(h):
    """9.3: charges 3 -> 0; 1 charge back after 3.0 s, then one after another (6.0 s, 9.0 s)."""
    rec = {}

    def on_frame(w, i, s):
        rec[i] = (w.now, w.player.abilities['ab1'].charges)

    tl = [('tap', 10, 'ab1'), ('tap', 12, 'ab1'), ('tap', 14, 'ab1'), ('tap', 16, 'ab1')]
    r = h.run('flicker', 300, timeline=tl, on_frame=on_frame, name='fl_charges')
    used = r.frames_of('ability_used', hero='flicker', slot='ab1')
    assert used == [10, 12, 14], 'blinks at %r (the 4th press must fail)' % used
    assert rec[14][1] == 0 and rec[16][1] == 0, 'charges after 3 blinks: %d' % rec[14][1]
    t0 = rec[10][0]
    back = []
    for n in (1, 2, 3):
        f = min(i for i in rec if i > 14 and rec[i][1] >= n)
        back.append(rec[f][0] - t0)
    for n, (t, want) in enumerate(zip(back, (3.0, 6.0, 9.0)), 1):
        assert abs(t - want) <= 0.05, 'charge %d came back after %.3f s, want %.1f' % (n, t, want)
    return 'charges back after %s s' % ', '.join('%.2f' % t for t in back)


# ============================ REWIND =========================================
def check_flicker_rewind(h):
    """9.3: record P at t; move 3 cells and take ~80 damage over 2.9 s (god off, dummy fire_every); tap ab2 at
    t + 3.0. After 0.5 s: within 0.4 of P, health >= health at t, no damage during the travel, ammo 40."""
    T0 = 30                 # t
    TR = T0 + 90            # t + 3.0 s
    st = {'pos': {}}

    def setup(w):
        # P = (8.5, 7.5). The dummy is 5 cells behind P at (3.5, 7.5): its first bolt lands ~0.6 s after t
        # (so the oldest sample, t + 0..0.1 s, still has full health), and the bolts still in flight at
        # t + 3.0 meet the player during the travel back.
        h.place(w, 8.5, 7.5, 0.0)
        st['d'] = h.spawn(w, 'dummy', -5.0)
        w.player.ult_charge = float(w.player.ULT_COST)     # a ready ult must stay unused while rewinding

    def start_fire(w):
        st['d'].fire_every = 0.28
        st['d'].bolt_damage = 10.0

    def on_frame(w, i, s):
        p = w.player
        if i == T0:
            st['P'] = (p.x, p.y)
            st['hp_t'] = p.pool.health
        if i == TR - 1:
            st['pre_pos'] = (p.x, p.y)
            st['pre'] = (p.pool.health, p.ult_charge, p.abilities['ab1'].charges, p.reloading, p.ammo,
                         len(p.history))
            st['bolts'] = sum(1 for q in w.projectiles if q.team == 1)
        if TR <= i <= TR + 16:
            st['pos'][i] = (p.x, p.y, p.status.has('invuln', w.now), p.lock_input, p.rewind is not None)
        if TR - 1 <= i <= TR + 14:
            # bolts that vanish right next to the player during the travel reached the player (and did 0)
            cur = {id(q): (q.x, q.y) for q in w.projectiles if q.team == 1 and q.alive}
            for k, (bx, by) in st.get('bolt_pos', {}).items():
                if k not in cur and i >= TR and math.hypot(bx - p.x, by - p.y) < 1.0:
                    st['absorbed'] = st.get('absorbed', 0) + 1
            st['bolt_pos'] = cur
        if i == TR + 16:
            st['end'] = (p.x, p.y, p.pool.health, p.ammo, p.reloading, len(p.history),
                         p.abilities['ab1'].charges, p.ult_charge, p.abilities['ab2'].charges)

    tl = [('call', T0, start_fire), ('hold', T0 + 6, 'fwd', 20), ('hold', 60, 'fire', 10), ('tap', TR - 3, 'reload'),
          ('tap', TR, 'ab2'), ('hold', TR + 2, 'fire', 10), ('tap', TR + 5, 'ab1'), ('tap', TR + 8, 'ult')]
    r = h.run('flicker', TR + 20, timeline=tl, setup=setup, on_frame=on_frame, debug={'god': False},
              name='fl_rewind', shots=(TR + 4,))
    p = r.world.player
    hurt_before = sum(d['amount'] for f, d in _events(r, 'player_hurt') if T0 <= f < TR)
    hurt_during = [(f, d['amount']) for f, d in _events(r, 'player_hurt') if TR <= f <= TR + 15]
    moved = st['pre_pos'][0] - st['P'][0]
    ex, ey, ehp, eammo, ereload, ehist, echarges, eult, eab2 = st['end']
    dist = math.hypot(ex - st['P'][0], ey - st['P'][1])
    assert moved >= 2.8, 'setup: moved only %.2f cells before the rewind' % moved
    assert 70.0 <= hurt_before <= 100.0, 'setup: took %.0f damage before the rewind, want about 80' % hurt_before
    assert st['hp_t'] == 150.0, 'setup: already hurt at t (%.0f)' % st['hp_t']
    assert st.get('absorbed', 0) >= 1, 'setup: no bolt reached the player during the travel'
    assert st['pre'][0] < st['hp_t'] and st['pre'][3], 'setup: expected lost health and a reload in progress'
    assert dist <= 0.4, 'rewind ended %.2f from P %r at (%.2f, %.2f)' % (dist, st['P'], ex, ey)
    assert ehp >= st['hp_t'], 'health %.1f < health at t %.1f' % (ehp, st['hp_t'])
    assert not hurt_during, 'damage during the travel: %r' % hurt_during
    assert eammo == 40 and not ereload, 'ammo %d reloading %s after the rewind' % (eammo, ereload)
    travel = [st['pos'][i] for i in range(TR, TR + 14)]
    assert all(v[2] and v[3] and v[4] for v in travel), 'invuln + locked input for the whole 0.5 s travel'
    assert not st['pos'][TR + 16][4] and not st['pos'][TR + 16][3], 'still rewinding 0.53 s later'
    xs = [v[0] for v in travel]
    assert all(b <= a + 1e-9 for a, b in zip(xs, xs[1:])) and xs[7] < xs[0] - 0.8, 'no travel along the path'
    assert not [f for f in r.frames_of('shot', hero='flicker') if TR <= f <= TR + 14], 'fired while rewinding'
    assert r.frames_of('ability_used', hero='flicker', slot='ab1') == [], 'blinked while rewinding'
    assert r.count('ult_used') == 0, 'ult used while rewinding'
    assert echarges == st['pre'][2] and abs(eult - st['pre'][1]) < 1e-6, 'cooldowns / ult must be untouched'
    assert eab2 == 0 and ehist <= 2, 'rewind not on cooldown (%d) or buffer not cleared (%d)' % (eab2, ehist)
    assert st['pre'][5] == 30, 'history holds %d samples, want 30' % st['pre'][5]
    return ('moved %.2f, took %.0f; %d bolts hit during the travel for 0; back at %.2f from P, health %.0f -> %.0f,'
            ' ammo %d' % (moved, hurt_before, st['absorbed'], dist, st['pre'][0], ehp, eammo))


def check_flicker_rewind_short(h):
    """Fewer than 30 samples: the oldest available is used. The 12 s cooldown blocks a second use."""
    st = {}

    def on_frame(w, i, s):
        p = w.player
        if i == 23:
            st['n'] = len(p.history)
        if i == 40:
            st['end'] = (p.x, p.y)

    tl = [('hold', 3, 'fwd', 12), ('tap', 24, 'ab2'), ('tap', 60, 'ab2'), ('tap', 24 + 361, 'ab2')]
    r = h.run('flicker', 24 + 380, timeline=tl, on_frame=on_frame, name='fl_rewind_short')
    d = math.hypot(st['end'][0] - 2.5, st['end'][1] - 7.5)
    assert st['n'] < 30, 'expected a partial buffer, got %d samples' % st['n']
    assert d <= 0.4, 'partial-buffer rewind ended %.2f from the start' % d
    used = r.frames_of('ability_used', hero='flicker', slot='ab2')
    assert used == [24, 24 + 361], 'rewind used at %r (cooldown 12 s)' % used
    return '%d samples, back within %.2f; second use after %.1f s' % (st['n'], d, (used[1] - used[0]) * DT)


def check_flicker_rewind_path(h):
    """A path round two corners (north through the gap at (5.5, 6.5), then east along row 5): the travel
    never enters a wall and ends on the oldest sample."""
    from rwf.world import is_wall
    st = {'bad': [], 'oldest': None}

    def on_frame(w, i, s):
        p = w.player
        if i == 99:
            st['oldest'] = p.history[0][:2]
        if is_wall(p.x, p.y) or _in_wall_footprint(p.x, p.y, 0.2):
            st['bad'].append((i, round(p.x, 2), round(p.y, 2)))
        if i == 118:
            st['end'] = (p.x, p.y)

    tl = [('hold', 2, 'fwd', 20), ('aim', 22, -math.pi / 2, 0.0), ('hold', 23, 'fwd', 12),
          ('aim', 35, 0.0, 0.0), ('hold', 36, 'fwd', 14), ('aim', 52, math.pi, 0.0), ('tap', 55, 'ab1'),
          ('tap', 100, 'ab2')]
    h.run('flicker', 120, timeline=tl, on_frame=on_frame, name='fl_rewind_path', shots=(106,))
    assert not st['bad'], 'inside a wall: %r' % st['bad'][:4]
    ox, oy = st['oldest']
    d = math.hypot(st['end'][0] - ox, st['end'][1] - oy)
    assert d < 1e-6, 'ended %.3f from the oldest sample' % d
    return 'oldest sample (%.2f, %.2f), wall-free travel' % (ox, oy)


# ============================ PULSE BOMB =====================================
def _bomb_run(h, name, frames=80, setup=None, extra=None, tl=None, ult_at=10, place=None, shots=()):
    """Throw a Pulse Bomb at frame ult_at with a full ult bar (no inf_ult). Returns (result, state)."""
    hf = _hf()
    st = {'stick': None, 'target': None, 'shake': 0.0, 'ult_after': None, 'bomb': None, 'now': {}}

    def _setup(w):
        if place is not None:
            h.place(w, *place)
        w.player.ult_charge = float(w.player.ULT_COST)
        if setup is not None:
            setup(w, st)

    def on_frame(w, i, s):
        st['now'][i] = w.now            # frames are not equal in sim time: the ult starts a 0.35x slow-mo
        if i == ult_at:
            st['ult_after'] = w.player.ult_charge
        for e in w.effects:
            if isinstance(e, hf.PulseBomb) and st['stick'] is None:
                st['stick'] = i
                st['target'] = e.target
                st['bomb'] = e
                st['stuck_at'] = (e.x, e.y, e.z)
        st['shake'] = max(st['shake'], w.cam.shake_amp)
        if extra is not None:
            extra(w, i, st)

    r = h.run('flicker', frames, timeline=[('tap', ult_at, 'ult')] + list(tl or ()), setup=_setup,
              on_frame=on_frame, name=name, shots=shots)
    return r, st


def check_flicker_pulse_bomb(h):
    """9.3: dummy at 4 cells, tap ult: it sticks, and 1.0-1.1 s later the dummy takes 350; a second dummy
    1.5 away takes 190-240. No self-damage; 5 beeps; 8 px shake; callout; the ult bar empties."""
    def setup(w, st):
        st['a'] = h.spawn(w, 'dummy', 4.0)
        st['b'] = h.spawn(w, 'dummy', 5.5)

    r, st = _bomb_run(h, 'fl_bomb', setup=setup, shots=(18, 30, 45, 55, 57))
    now = st['now']
    hero = r.world.player
    a, b = st['a'], st['b']
    assert st['stick'] is not None and st['target'] is a, 'the bomb did not stick to the first dummy'
    ua = [(f, d) for f, d in _events(r, 'damage', lambda d: d['target'] is a and d['ability'] == 'ult')]
    ub = [(f, d) for f, d in _events(r, 'damage', lambda d: d['target'] is b and d['ability'] == 'ult')]
    assert len(ua) == 1 and abs(ua[0][1]['amount'] - 350.0) < 1e-6, 'stuck dummy took %r' % [
        d['amount'] for _, d in ua]
    fuse = now[ua[0][0]] - now[st['stick']]
    assert 1.0 - 1e-6 <= fuse <= 1.1, 'exploded %.3f s after sticking' % fuse
    assert len(ub) == 1 and 190.0 <= ub[0][1]['amount'] <= 240.0, 'second dummy took %r' % [
        d['amount'] for _, d in ub]
    assert ua[0][1]['source'] is hero and not ua[0][1]['crit'], 'credit / crit'
    assert r.count('player_hurt') == 0, 'the bomb hurt the player'
    assert st['ult_after'] == 0.0, 'ult charge %r right after the throw' % st['ult_after']
    uu = r.first('ult_used', hero='flicker')
    assert uu is not None and uu['callout'] == 'BOMB AWAY!' and uu['name'] == 'PULSE BOMB'
    beeps = r.frames_of('sfx', name='beep')
    since = [round(now[f] - now[st['stick']], 3) for f in beeps]
    assert len(beeps) == 5 and all(abs(t - 0.2 * k) < 0.02 for k, t in enumerate(since)), \
        'beeps at %r s (every 0.2 s from the stick)' % since
    ex = r.where('explosion', team=0)
    assert len(ex) == 1 and abs(ex[0]['radius'] - 2.5) < 1e-9, 'explosion events %r' % ex
    assert st['shake'] >= 8.0, 'shake %.1f' % st['shake']
    flight = now[st['stick']] - now[10]
    assert 0.2 <= flight <= 0.4, 'flight to 4 cells took %.3f s at 12 cells/s' % flight
    return 'stuck after %.2f s, 350 at +%.2f s, neighbour %.1f, %d beeps' % (flight, fuse, ub[0][1]['amount'],
                                                                            len(beeps))


def check_flicker_pulse_bomb_follow(h):
    """Once stuck it follows the target; if the target dies it stays where it was."""
    from rwf import combat

    def setup(w, st):
        st['a'] = h.spawn(w, 'dummy', 4.0)

    def extra(w, i, st):
        if st['stick'] is not None and i == st['stick'] + 5:
            st['a'].x += 1.5                            # the target walks away: the bomb goes with it
        if st['stick'] is not None and i == st['stick'] + 10:
            st['moved_to'] = (st['a'].x, st['a'].y)

    r, st = _bomb_run(h, 'fl_bomb_follow', setup=setup, extra=extra)
    ex = r.first('explosion', team=0)
    mx, my = st['moved_to']
    assert ex is not None and math.hypot(ex['x'] - mx, ex['y'] - my) < 1e-6, \
        'explosion at (%.2f, %.2f), target at (%.2f, %.2f)' % (ex['x'], ex['y'], mx, my)
    ua = r.where('damage', target=lambda t: t is st['a'], ability='ult')
    assert len(ua) == 1 and abs(ua[0]['amount'] - 350.0) < 1e-6

    def setup2(w, st):
        st['a'] = h.spawn(w, 'dummy', 4.0)
        st['b'] = h.spawn(w, 'dummy', 5.5)

    def extra2(w, i, st):
        if st['stick'] is not None and i == st['stick'] + 5:
            st['death_at'] = (st['a'].x, st['a'].y)
            combat.apply_damage(w, st['a'], 5000.0, None, ability='test')
        if st['stick'] is not None and i == st['stick'] + 6:
            st['a'].x += 3.0                            # a dead body moving must not drag the bomb

    r2, st2 = _bomb_run(h, 'fl_bomb_dead', setup=setup2, extra=extra2)
    ex2 = r2.first('explosion', team=0)
    dx, dy = st2['death_at']
    assert ex2 is not None and math.hypot(ex2['x'] - dx, ex2['y'] - dy) < 1e-6, 'bomb left its spot after the kill'
    ub = r2.where('damage', target=lambda t: t is st2['b'], ability='ult')
    assert len(ub) == 1 and 190.0 <= ub[0]['amount'] <= 240.0, 'neighbour took %r' % [d['amount'] for d in ub]
    return 'followed +1.5 cells; stayed at the death spot, neighbour %.1f' % ub[0]['amount']


def check_flicker_pulse_bomb_wall(h):
    """No enemy on the line: it sticks to the wall on contact. Walls block the blast (LOS from the bomb)."""
    def setup(w, st):
        st['open'] = w.spawn_enemy('dummy', 18.5, 5.5)       # 2.0 from the stick point, clear LOS
        st['hidden'] = w.spawn_enemy('dummy', 17.5, 5.5)     # 2.4 away, behind the wall cell (17, 6)

    r, st = _bomb_run(h, 'fl_bomb_wall', setup=setup, place=(14.5, 7.5, 0.0), frames=70, shots=(30, 60))
    assert st['stick'] is not None and st['target'] is None, 'no wall stick'
    sx, sy, sz = st['stuck_at']
    assert 18.5 < sx < 19.0 and abs(sy - 7.5) < 1e-6 and sz > 0.3, 'stuck at %r' % (st['stuck_at'],)
    ex = r.first('explosion', team=0)
    assert ex is not None
    fuse = st['now'][r.frames_of('explosion', team=0)[0]] - st['now'][st['stick']]
    assert 1.0 - 1e-6 <= fuse <= 1.0 + DT, 'wall fuse %.3f s' % fuse
    ho = r.where('damage', target=lambda t: t is st['open'], ability='ult')
    hh = r.where('damage', target=lambda t: t is st['hidden'], ability='ult')
    d_open = math.hypot(18.5 - sx, 5.5 - sy)
    want = 350.0 + (105.0 - 350.0) * d_open / 2.5
    assert len(ho) == 1 and abs(ho[0]['amount'] - want) < 1e-6, 'open dummy took %r, want %.1f' % (
        [d['amount'] for d in ho], want)
    assert not hh, 'a dummy behind a wall was hit'
    return 'stuck at x %.2f; open dummy %.1f, walled dummy 0' % (sx, ho[0]['amount'])


def check_flicker_pulse_bomb_drop(h):
    """No contact within 6 cells: it drops to the floor at max range; the fuse starts on landing."""
    def setup(w, st):
        st['a'] = w.spawn_enemy('dummy', 10.0, 7.5)          # 1.5 past the drop point

    r, st = _bomb_run(h, 'fl_bomb_drop', setup=setup, frames=70)
    sx, sy, sz = st['stuck_at']
    assert st['target'] is None and abs(sx - 8.5) <= 0.05 and abs(sy - 7.5) < 1e-6 and sz < 0.1, \
        'dropped at %r' % (st['stuck_at'],)
    flight = st['now'][st['stick']] - st['now'][10]
    assert abs(flight - 0.5) <= DT + 1e-6, 'flight %.3f s, want 0.5' % flight
    ha = r.where('damage', target=lambda t: t is st['a'], ability='ult')
    want = 350.0 + (105.0 - 350.0) * math.hypot(10.0 - sx, 7.5 - sy) / 2.5
    assert len(ha) == 1 and abs(ha[0]['amount'] - want) < 1e-6, 'dummy took %r, want %.1f' % (
        [d['amount'] for d in ha], want)
    return 'dropped at x %.2f z %.2f; dummy 1.5 away took %.1f' % (sx, sz, ha[0]['amount'])


def check_flicker_pulse_bomb_barrier(h):
    """An enemy barrier stops the throw (the bomb sticks to it, the barrier takes nothing); the blast ignores
    barriers, so the dummy behind it is hit."""
    from rwf import combat
    from rwf.config import TEAM_ENEMY

    def setup(w, st):
        b = combat.Barrier(TEAM_ENEMY, 400, 1.0)
        b.set_pose(5.0, 7.5, math.pi)
        w.add_barrier(b)
        st['bar'] = b
        st['a'] = w.spawn_enemy('dummy', 6.0, 7.5)

    r, st = _bomb_run(h, 'fl_bomb_barrier', setup=setup, frames=70)
    sx = st['stuck_at'][0]
    assert st['target'] is None and 4.7 <= sx <= 5.0, 'stuck at %r, want the barrier line x 5.0' % (st['stuck_at'],)
    assert st['bar'].hp == 400 and r.count('barrier_damage') == 0, 'the barrier took damage'
    ha = r.where('damage', target=lambda t: t is st['a'], ability='ult')
    assert len(ha) == 1 and 240.0 <= ha[0]['amount'] <= 260.0, 'dummy behind the barrier took %r' % [
        d['amount'] for d in ha]
    return 'stuck at x %.2f on the barrier; dummy behind it took %.1f' % (sx, ha[0]['amount'])


def check_flicker_pulse_bomb_kill(h):
    """Bomb kills are credited to the player as ult kills labelled PULSE BOMB."""
    from rwf.combat import HealthPool

    def setup(w, st):
        st['a'] = h.spawn(w, 'dummy', 4.0)
        st['a'].pool = HealthPool(300)

    r, st = _bomb_run(h, 'fl_bomb_kill', setup=setup, frames=60)
    k = r.first('kill', target=lambda t: t is st['a'])
    assert k is not None and k['source'] is r.world.player, 'no credited kill'
    assert k['ult'] and k['label'] == 'PULSE BOMB' and k['killer'] == 'FLICKER', 'kill %r' % (
        {x: k[x] for x in ('ult', 'label', 'killer')},)
    assert r.world.player.ult_charge > 0.0, 'bomb damage gave no ult charge'
    return 'kill: ult %s, label %s' % (k['ult'], k['label'])


# ============================ presentation ===================================
def check_flicker_visuals(h):
    """Viewmodel / overlays / crosshair / icons draw in every state, and steady play (fire, blink, rewind,
    bomb) allocates no large surface (rule 12 counter, after the first-use caches exist)."""
    import pygame
    hf = _hf()
    st = {'drawn': 0}

    def setup(w):
        h.place(w, *h.ROOMY)
        for side in (-0.6, 0.0, 0.6):
            h.spawn(w, 'dummy', 4.0, side)
        w.player.ult_charge = float(w.player.ULT_COST)

    def on_frame(w, i, s):
        if i == 30:
            h.count_surfaces(True)
        if i == 200:
            st['big'] = h.big_surfaces
            h.count_surfaces(False)
        p = w.player
        if p.rewind is not None:
            st['rw'] = True

    tl = [('tap', 5, 'ab2'), ('hold', 25, 'fire', 30), ('tap', 60, 'ab1'), ('hold', 62, 'fire', 20),
          ('tap', 90, 'ult'), ('hold', 95, 'left', 20), ('tap', 150, 'ab2'), ('hold', 170, 'fire', 20)]
    r = h.run('flicker', 205, timeline=tl, setup=setup, on_frame=on_frame, name='fl_vis',
              debug={'no_cooldowns': True}, shots=(27, 60, 61, 100, 118, 153, 175))
    h.count_surfaces(False)
    assert st.get('rw'), 'no rewind happened'
    assert st.get('big', 99) == 0, '%d surfaces >= 256x256 allocated during play' % st.get('big', 99)
    assert r.count('explosion', team=0) == 1
    # every draw entry point in odd states
    w = r.world
    p = w.player
    surf = pygame.Surface((1024, 768))
    for state in ('idle', 'fire', 'blink', 'rewind', 'dead'):
        if state == 'fire':
            p.gun_fired = [w.now, w.now - 0.03]
            p.last_fire = w.now
        elif state == 'blink':
            p.last_blink = w.now - 0.05
        elif state == 'rewind':
            p.rewind = {'pts': [(p.x, p.y)], 'cum': [0.0], 't': 0.0, 'oldest': (p.x, p.y, 0.0, 150.0, 40)}
            p.rewind_started = w.now - 0.2
        elif state == 'dead':
            p.rewind = None
            p.alive = False
        p.draw_overlay(surf, w)
        p.draw_viewmodel(surf, w)
        p.draw_crosshair(surf, w)
        st['drawn'] += 1
    p.alive = True
    sheet = pygame.Surface((5 * 104 + 8, 170))
    sheet.fill((10, 10, 20))
    for k, slot in enumerate(('portrait', 'ab1', 'ab2', 'ult', 'secondary')):
        for size, y in ((96, 8), (52, 112)):
            s = pygame.Surface((size, size))
            hf.Flicker.draw_icon(slot, s, s.get_rect())
            sheet.blit(s, (8 + k * 104, y))
            bg = s.get_at((size // 2, 4))[:3]
            marks = sum(1 for gx in range(8, size - 8, 4) for gy in range(8, size - 8, 4)
                        if s.get_at((gx, gy))[:3] != bg)
            assert marks >= 8, 'icon %s at %d looks empty (%d marks)' % (slot, size, marks)
    h.save(sheet, 'flicker_icons')
    return 'big surfaces 0 over 170 frames; %d draw states; icon sheet ok' % st['drawn']


def check_flicker_stage_restore(h):
    """3.0: stage clear refills health and ammo and resets Blink charges and the Rewind cooldown; ult kept."""
    st = {}

    def setup(w):
        w.player.ult_charge = 500.0

    def clear(w):
        w.bus.emit('stage_clear', stage=1)

    def on_frame(w, i, s):
        p = w.player
        if i == 30:
            p.pool.health = 60.0
            st['pre'] = (p.ammo, p.abilities['ab1'].charges, p.abilities['ab2'].charges)
        if i == 32:
            st['post'] = (p.pool.health, p.ammo, p.abilities['ab1'].charges, p.abilities['ab2'].charges,
                          p.ult_charge)

    tl = [('hold', 3, 'fire', 10), ('tap', 15, 'ab1'), ('tap', 17, 'ab1'), ('tap', 19, 'ab2'), ('call', 31, clear)]
    h.run('flicker', 34, timeline=tl, setup=setup, on_frame=on_frame, name='fl_restore')
    assert st['pre'][0] < 40 and st['pre'][1] < 3 and st['pre'][2] == 0, 'setup %r' % (st['pre'],)
    hp, ammo, c1, c2, ult = st['post']
    assert hp == 150.0 and ammo == 40 and c1 == 3 and c2 == 1, 'after stage clear %r' % (st['post'],)
    assert ult >= 500.0, 'ult charge lost on stage clear (%.1f)' % ult
