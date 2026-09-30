"""RAMPART acceptance (spec 9.3; HERO_C owns this file).

    python -X utf8 tools/smoke.py --suite rampart [--shots] [--no-assets]

Step 1 is the generic hero contract; the rest are the 9.3 RAMPART rows (hammer, barrier, charge, flame
strike, quake) with the exact numbers of spec 3.3, plus the extra rules of 3.0/5.6 (ult from absorbed
damage, x0.7 speed, melee redirect, lockout, cooldown start, steering limit, brush, boss), the drawing
contract (viewmodel/overlay/crosshair/icons, PNGs with --shots) and the no-large-surface rule (8.1/8.12).
Layouts use dummies with a 1000-health pool and no_director (the harness default).
"""
import math

DT = 1.0 / 30.0
EPS = 1e-6
NORTH = -math.pi / 2


def _pool(n=1000.0):
    from rwf.combat import HealthPool
    return HealthPool(n)


def _dmg(r, target, **match):
    return r.where('damage', target=lambda t, e=target: t is e, **match)


# ============================ 1. generic contract ============================
def check_contract(h):
    """9.3 step 1: every slot emits ability_used, alt raises the barrier, damage, ult, draws."""
    return h.hero_contract('rampart')


# ============================ 2. hero-specific ===============================
def check_hammer(h):
    """3 dummies at 2 cells within +-40 deg all take 80 per swing; a dummy behind takes 0; at most one swing
    per 0.9 s. Enemy barriers in the arc take 80 and don't block (ult +1/HP + 0.5/HP barrier). No swing
    while the barrier is raised."""
    st = {}
    home = (10.0, 10.5, NORTH)

    def setup(w):
        h.place(w, *home)
        st['front'] = []
        st['pos'] = {}
        for deg in (-40.0, 0.0, 40.0):
            a = math.radians(deg)
            e = h.spawn(w, 'dummy', 2.0 * math.cos(a), 2.0 * math.sin(a), pool=_pool())
            st['front'].append(e)
            st['pos'][e.id] = (e.x, e.y)
        e = h.spawn(w, 'dummy', -2.0, 0.0, pool=_pool())
        st['back'] = e
        st['pos'][e.id] = (e.x, e.y)

    def on_frame(w, i, state):
        for e in w.enemies:                       # undo the 0.6 knockback so every swing meets the layout
            if e.id in st['pos']:
                e.x, e.y = st['pos'][e.id]

    r = h.run('rampart', 100, timeline=[('hold', 5, 'fire', 85)], setup=setup, on_frame=on_frame, name='hammer')
    swings = [d['t'] for d in r.where('ability_used', hero='rampart', slot='primary')]
    n = len(swings)
    assert 3 <= n <= 4, 'hammer swings in 2.83 s of held fire: %d (want 4 at 0.9 s)' % n
    gaps = [b - a for a, b in zip(swings, swings[1:])]
    assert min(gaps) >= 0.9 - EPS, 'two swings %.3f s apart (< 0.9)' % min(gaps)
    assert max(gaps) <= 0.9 + 1.5 * DT, 'held fire swings as soon as ready (gap %.3f)' % max(gaps)
    for e in st['front']:
        ev = _dmg(r, e)
        assert len(ev) == n, 'front dummy hit %d times in %d swings' % (len(ev), n)
        assert all(abs(d['amount'] - 80.0) < EPS and d['ability'] == 'primary' and not d['crit'] for d in ev), \
            'hammer damage %r' % [(d['amount'], d['ability']) for d in ev]
    assert not _dmg(r, st['back']), 'the dummy behind (180 deg) was hit'

    # enemy barrier in the arc: takes 80 and doesn't shield the dummy behind it
    st2 = {}

    def setup2(w):
        from rwf.combat import Barrier
        from rwf.config import TEAM_ENEMY
        p = w.player
        b = Barrier(TEAM_ENEMY, 400, 1.0)
        b.set_pose(p.x + 1.5, p.y, math.pi)
        w.add_barrier(b)
        st2['b'] = b
        st2['d'] = h.spawn(w, 'dummy', 2.2, pool=_pool())

    r2 = h.run('rampart', 20, timeline=[('tap', 5, 'fire')], setup=setup2, name='hammer_barrier')
    b, d = st2['b'], st2['d']
    assert abs(b.hp - 320.0) < EPS, 'enemy barrier in the arc: hp %.1f (want 400 - 80)' % b.hp
    assert abs(1000.0 - d.pool.health - 80.0) < EPS, 'dummy behind the enemy barrier took %.1f' % (
        1000.0 - d.pool.health)
    ult = r2.world.player.ult_charge
    assert abs(ult - 120.0) < EPS, 'ult after 80 to a dummy + 80 to a barrier: %.2f (want 80 + 40)' % ult

    # no swings while the barrier is raised
    r3 = h.run('rampart', 70, timeline=[('hold', 5, 'alt', 45), ('hold', 5, 'fire', 60)], name='hammer_shield')
    fr = r3.frames_of('ability_used', hero='rampart', slot='primary')
    assert fr and min(fr) >= 50, 'swung with the barrier raised (frames %r)' % fr[:3]
    return '%d swings, gaps %.3f-%.3f s, 80 x 3 per swing, barrier 400 -> 320' % (n, min(gaps), max(gaps))


def check_barrier(h):
    """Dummy fire_every 0.5 at 5 cells, alt held 3 s: barrier_damage events, player health unchanged, ult +0.5
    per HP absorbed. Lowered: no regen for 2.0 s, then 150 HP/s (checked at 2.5 s)."""
    st = {'hp': [], 'up': []}

    def setup(w):
        st['d'] = h.spawn(w, 'dummy', 5.0, fire_every=0.5, bolt_damage=40.0, pool=_pool())
        st['hp0'] = w.player.pool.total

    def on_frame(w, i, state):
        p = w.player
        b = p.barrier
        if i == 50:
            st['up'] = w.player_barrier() is b
        if i == 90:
            st['hp90'] = p.pool.total
            st['ult90'] = p.ult_charge
            st['speed_up'] = p.speed_mult
        if i == 91:
            st['t_low'] = w.now
            st['hp_low'] = b.hp
            st['d'].fire_every = None
            st['down'] = w.player_barrier() is None
        if i > 91:
            st['hp'].append((w.now - st['t_low'], b.hp))

    r = h.run('rampart', 91 + 90, timeline=[('hold', 1, 'alt', 90)], setup=setup, on_frame=on_frame,
              debug={'god': False}, name='barrier')
    p = r.world.player
    mine = r.where('barrier_damage', barrier=lambda b: b is p.barrier)
    assert st['up'], 'barrier not raised while alt is held'
    assert len(mine) >= 4, 'only %d barrier_damage events in 3 s (dummy fires every 0.5 s)' % len(mine)
    hurt = [f for f in r.frames_of('player_hurt') if f <= 90]
    assert not hurt and abs(st['hp90'] - st['hp0']) < EPS, 'player hurt behind the barrier (frames %r)' % hurt[:3]
    absorbed = sum(d['amount'] for d, f in zip(mine, r.frames_of('barrier_damage')) if f <= 90)
    assert abs(st['ult90'] - 0.5 * absorbed) < 1e-3, 'ult %.2f, want 0.5 x %.0f absorbed' % (st['ult90'], absorbed)
    assert abs(st['speed_up'] - 0.7) < EPS, 'speed_mult with the barrier up %.2f (want 0.7)' % st['speed_up']
    assert st['down'], 'barrier still in the world after alt was released'
    hp_low = st['hp_low']
    assert hp_low <= 600.0 - 160.0, 'barrier took too little damage (%.0f left)' % hp_low
    at19 = [hp for t, hp in st['hp'] if t <= 1.9 + EPS]
    assert at19 and max(at19) <= hp_low + EPS, 'regen started before 2.0 s lowered (%.1f -> %.1f)' % (
        hp_low, max(at19))
    at25 = [hp for t, hp in st['hp'] if abs(t - 2.5) < DT * 0.5]
    assert at25, 'no sample at 2.5 s'
    gain = at25[0] - hp_low
    assert 60.0 <= gain <= 90.0, 'regen after 2.5 s lowered: +%.1f (want 150/s x 0.5 s = 75)' % gain
    return '%d hits absorbed (%.0f HP), ult %.0f, lowered hp %.0f -> +%.1f at 2.5 s' % (
        len(mine), absorbed, st['ult90'], hp_low, gain)


def check_barrier_break_lockout(h):
    """Broken (hp set to 1, one bolt): forced down, 5.0 s lockout even with alt held, then regen from 0 and
    it comes back up by itself."""
    st = {'trace': []}

    def setup(w):
        st['d'] = h.spawn(w, 'dummy', 5.0, fire_every=0.5, bolt_damage=10.0, pool=_pool())

    def on_frame(w, i, state):
        p = w.player
        if i == 30:
            assert w.player_barrier() is p.barrier, 'barrier not up at frame 30'
            p.barrier.hp = 1.0
        st['trace'].append((w.now, w.player_barrier() is not None, p.abilities['secondary'].charges, p.barrier.hp))

    r = h.run('rampart', 30 + 30 * 7, timeline=[('hold', 1, 'alt', 238)], setup=setup, on_frame=on_frame,
              debug={'god': False}, name='barrier_break')
    br = r.first('barrier_broken')
    assert br is not None, 'no barrier_broken after setting hp to 1'
    tb = br['t']
    during = [(t, up, ch, hp) for t, up, ch, hp in st['trace'] if tb < t < tb + 4.95]
    assert during, 'no frames in the lockout window'
    assert not any(up for _, up, _, _ in during), 'barrier re-raised during the 5 s lockout'
    assert all(ch == 0 for _, _, ch, _ in during[1:]), 'secondary tile not on cooldown during the lockout'
    assert all(hp == 0.0 for _, _, _, hp in during), 'barrier regenerated during the lockout'
    back = [(t, hp) for t, up, _, hp in st['trace'] if t > tb and up]
    assert back, 'barrier never came back with alt held'
    dt_back, hp_back = back[0][0] - tb, back[0][1]
    assert 5.0 - EPS <= dt_back <= 5.25, 'back up %.2f s after the break (want 5.0 lockout)' % dt_back
    assert hp_back < 40.0, 'regen after a break starts from 0 (hp %.1f when raised)' % hp_back
    return 'raised again %.2f s after the break with %.1f HP' % (dt_back, hp_back)


def check_barrier_redirect(h):
    """5.6: enemy melee/area damage whose source-to-player segment crosses the raised barrier hits the barrier;
    from behind it hits the player. x0.7 move speed while raised."""
    from rwf import combat
    st = {}

    def call(w):
        p = w.player
        front = h.spawn(w, 'dummy', 2.5, pool=_pool())
        back = h.spawn(w, 'dummy', -1.0, pool=_pool())
        hp = p.barrier.hp
        st['front'] = combat.enemy_hits_player(w, front, 40.0, (front.x, front.y), 'melee')
        st['bar'] = hp - p.barrier.hp
        st['back'] = combat.enemy_hits_player(w, back, 40.0, (back.x, back.y), 'melee')

    r = h.run('rampart', 40, timeline=[('hold', 2, 'alt', 30), ('call', 20, call)], debug={'god': False},
              name='barrier_redirect')
    assert st['front'] == 0.0 and abs(st['bar'] - 40.0) < EPS, 'front hit not redirected: %r' % st
    assert st['back'] > 0.0, 'a hit from behind should reach the player (%r)' % st
    assert r.count('player_hurt') == 1

    def walk(alt):
        tl = [('hold', 5, 'fwd', 30)] + ([('hold', 4, 'alt', 32)] if alt else [])
        rr = h.run('rampart', 40, timeline=tl, name='barrier_walk_%d' % alt)
        return rr.world.player.x - 2.5
    d_up, d_free = walk(True), walk(False)
    assert abs(d_free - 3.9) < 0.15, 'walk 1 s: %.2f (want 3.9)' % d_free
    assert abs(d_up - 3.9 * 0.7) < 0.15, 'walk 1 s behind the barrier: %.2f (want 2.73)' % d_up
    return 'front 40 -> barrier, back -> player; 1 s walk %.2f / %.2f' % (d_free, d_up)


def check_charge(h):
    """Player at (8.5, 7.5) facing east, dummy at (11.5, 7.5), tap ab1: 225 on the dummy within 1.5 s and the
    charge has ended; open space: ends within 1.5 s (13.5 cells), never in a wall; a wall ends it."""
    st = {'trace': []}

    def setup(w):
        h.place(w, 8.5, 7.5, 0.0)
        st['d'] = h.spawn(w, 'dummy', 3.0, pool=_pool())

    def on_frame(w, i, state):
        p = w.player
        st['trace'].append((w.now, p.charging, p.knockback_immune, p.x, p.y))

    r = h.run('rampart', 70, timeline=[('tap', 5, 'ab1')], setup=setup, on_frame=on_frame, name='charge_pin')
    p = r.world.player
    t0 = r.first('ability_used', hero='rampart', slot='ab1')['t']
    ev = _dmg(r, st['d'])
    assert len(ev) == 1, 'pinned dummy damage events %r' % [(d['amount'], d['ability']) for d in ev]
    d0 = ev[0]
    assert abs(d0['amount'] - 225.0) < EPS and d0['ability'] == 'ab1', 'pin impact %r' % d0['amount']
    assert d0['t'] - t0 <= 1.5 + EPS, 'pin impact %.2f s after the charge started' % (d0['t'] - t0)
    assert not p.charging and p.charge_end_reason == 'slam', 'charge still on / ended by %r' % p.charge_end_reason
    mid = [k for t, c, k, x, y in st['trace'] if c]
    assert mid and all(mid), 'not knockback-immune while charging'
    assert not p.knockback_immune, 'still knockback-immune after the charge'
    assert st['d'].x >= 18.0 and p.x <= 18.75, 'carried to the east wall: dummy x %.2f, player x %.2f' % (
        st['d'].x, p.x)
    assert not st['d'].status.has('pinned', r.world.now), 'dummy still pinned after the slam'
    pin_note = 'slam 225 after %.2f s at x %.2f' % (d0['t'] - t0, p.x)

    def run_open(name, start, frames=70, extra=()):
        tr = []

        def su(w):
            h.place(w, *start)

        def of(w, i, state):
            tr.append((i, w.now, w.player.charging, w.player.x, w.player.y, w.player.angle))
        rr = h.run('rampart', frames, timeline=[('tap', 5, 'ab1')] + list(extra), setup=su, on_frame=of,
                   name=name)
        on = [x for x in tr if x[2]]
        end = [x for x in tr if not x[2] and x[0] > 5]
        return rr, tr, on, end

    # open space, no target, fire held during the charge: ends on time, 13.5 cells, no swings meanwhile
    rr, tr, on, end = run_open('charge_open', (2.5, 7.5, 0.0), extra=[('hold', 8, 'fire', 30)])
    t0 = rr.first('ability_used', slot='ab1')['t']
    assert end, 'charge never ended in open space'
    dur = end[0][1] - t0
    moved = end[0][3] - 2.5
    assert dur <= 1.5 + DT + EPS and rr.world.player.charge_end_reason == 'time', \
        'open charge ended after %.2f s by %r' % (dur, rr.world.player.charge_end_reason)
    assert abs(moved - 13.5) < 0.35, 'open charge moved %.2f (want 9 x 1.5 = 13.5)' % moved
    sw = [f for f in rr.frames_of('ability_used', slot='primary') if f <= end[0][0]]
    assert not sw, 'hammer swung while charging (frames %r)' % sw[:3]
    ab = rr.world.player.abilities['ab1']
    assert ab.charges == 0 and ab.recharge_left > 7.0 - (70 - end[0][0]) * DT - 0.05, \
        'cooldown must start when the charge ends (recharge_left %.2f)' % ab.recharge_left

    # into the east wall from (15.5, 7.5): ends at the wall, not inside it
    rr, tr, on, end = run_open('charge_wall', (15.5, 7.5, 0.0), frames=40)
    pw = rr.world.player
    assert pw.charge_end_reason == 'wall' and 18.5 <= pw.x <= 18.75 + EPS, \
        'wall charge ended by %r at x %.3f' % (pw.charge_end_reason, pw.x)

    # steering is limited to 90 deg/s while charging, free again afterwards
    rr, tr, on, end = run_open('charge_steer', (2.5, 7.5, 0.0), frames=90,
                               extra=[('look', 10, 2000, 0), ('look', 80, 400, 0)])
    turns = [abs(b[5] - a[5]) for a, b in zip(tr, tr[1:]) if b[0] == 10]
    assert turns and turns[0] <= math.radians(90.0) * DT + 1e-6, 'turned %.4f rad in one charge frame' % turns[0]
    after = [abs(b[5] - a[5]) for a, b in zip(tr, tr[1:]) if b[0] == 80]
    assert after and after[0] > 0.5, 'look after the charge still limited (%.3f)' % after[0]
    return pin_note + '; open %.2f cells in %.2f s; wall stop x %.2f' % (moved, dur, pw.x)


def check_charge_cancel_brush_boss(h):
    """Shift again after 0.2 s cancels (not before); cooldown 7.0 s from the end. A dummy 0.65 beside the path
    takes 50 once and is knocked 1.5 sideways. The boss takes 100 and ends the charge."""
    tr = []

    def of(w, i, state):
        tr.append((i, w.now, w.player.charging))
    r = h.run('rampart', 260, timeline=[('tap', 5, 'ab1'), ('tap', 8, 'ab1'), ('tap', 14, 'ab1'),
                                        ('tap', 120, 'ab1'), ('tap', 240, 'ab1')], on_frame=of, name='charge_cancel')
    p = r.world.player
    uses = r.where('ability_used', slot='ab1')
    assert len(uses) == 2, 'ab1 uses %d (want the first charge, none on cooldown, one after it)' % len(uses)
    assert r.frames_of('ability_used', slot='ab1')[1] == 240, 'charge used during its cooldown'
    on = [x for x in tr if x[2]]
    assert on[0][0] == 5 and max(x[0] for x in on if x[0] < 100) == 13, \
        'cancel timing: charging frames %d-%d (tap at +0.1 s must be ignored, +0.3 s cancels)' % (
            on[0][0], max(x[0] for x in on if x[0] < 100))
    t_end = tr[14][1]
    rdy = [d['t'] for d in r.where('ability_ready', slot='ab1')]
    assert rdy and abs(rdy[0] - t_end - 7.0) < 0.05, 'ab1 ready %.2f s after the cancel (want 7.0)' % (
        (rdy[0] - t_end) if rdy else -1)
    assert uses[1]['t'] >= rdy[0] - EPS and p.charge_end_reason in ('time', 'wall', 'cancel', '')

    # brush: row 12 is open from x 1 to 18; the dummy stands 0.65 north of the path
    st = {}

    def su(w):
        h.place(w, 8.5, 12.5, 0.0)
        st['d'] = h.spawn(w, 'dummy', 2.5, -0.65, pool=_pool())
        st['y0'] = st['d'].y
        st['x0'] = st['d'].x
    r = h.run('rampart', 60, timeline=[('tap', 5, 'ab1')], setup=su, name='charge_brush')
    d = st['d']
    ev = _dmg(r, d)
    assert len(ev) == 1 and abs(ev[0]['amount'] - 50.0) < EPS and ev[0]['ability'] == 'ab1', \
        'brush damage %r' % [d_['amount'] for d_ in ev]
    assert st['y0'] - d.y >= 1.4 and abs(d.x - st['x0']) < 0.2, \
        'brush knockback: moved (%.2f, %.2f), want 1.5 sideways' % (d.x - st['x0'], d.y - st['y0'])
    assert not d.status.has('pinned', r.world.now), 'the brushed dummy got pinned'

    # the boss: 100 and the charge ends there
    sb = {}

    def sub(w):
        sb['b'] = h.spawn(w, 'warden', 4.0)
    r = h.run('rampart', 40, timeline=[('tap', 2, 'ab1')], setup=sub, name='charge_boss')
    p = r.world.player
    ev = _dmg(r, sb['b'])
    assert len(ev) == 1 and abs(ev[0]['raw'] - 100.0) < EPS and ev[0]['ability'] == 'ab1', \
        'boss charge damage %r' % [(d_['raw'], d_['ability']) for d_ in ev]
    assert p.charge_end_reason == 'boss' and not p.charging, 'charge vs boss ended by %r' % p.charge_end_reason
    assert not sb['b'].status.has('pinned', r.world.now), 'the boss was pinned'
    return 'cancel at +0.3 s, ready +%.2f s; brush 50 and %.2f sideways; boss raw 100' % (
        rdy[0] - t_end, st['y0'] - d.y)


def check_flame_strike(h):
    """2 dummies in a line behind an enemy barrier: both take 90 (barrier untouched). 2 charges, 6.0 s each,
    one after another; a third tap does nothing. Range 12; stops at walls."""
    from rwf.combat import Barrier
    from rwf.config import TEAM_ENEMY
    st = {'ch': []}

    def setup(w):
        p = w.player
        b = Barrier(TEAM_ENEMY, 400, 1.0)
        b.set_pose(p.x + 2.0, p.y, math.pi)
        w.add_barrier(b)
        st['b'] = b
        st['near'] = h.spawn(w, 'dummy', 4.0, pool=_pool())
        st['mid'] = h.spawn(w, 'dummy', 5.5, pool=_pool())
        st['far'] = h.spawn(w, 'dummy', 13.5, pool=_pool())

    def on_frame(w, i, state):
        st['ch'].append((w.now, w.player.abilities['ab2'].charges))

    r = h.run('rampart', 5 + 12 * 30 + 20, timeline=[('tap', 5, 'ab2'), ('tap', 10, 'ab2'), ('tap', 15, 'ab2')],
              setup=setup, on_frame=on_frame, name='flame')
    uses = r.where('ability_used', slot='ab2')
    assert len(uses) == 2, 'flame strikes cast %d (2 charges, third tap must fail)' % len(uses)
    for key in ('near', 'mid'):
        ev = _dmg(r, st[key])
        assert len(ev) == 2 and all(abs(d['amount'] - 90.0) < EPS and d['ability'] == 'ab2' for d in ev), \
            '%s dummy flame damage %r' % (key, [d['amount'] for d in ev])
    assert not _dmg(r, st['far']), 'a dummy 13.5 cells away was hit (range 12)'
    assert abs(st['b'].hp - 400.0) < EPS and not r.count('barrier_damage'), 'flame strike hit the enemy barrier'
    t1 = uses[0]['t']

    def ch_at(dt):
        c = [n for t, n in st['ch'] if t >= t1 + dt]
        return c[0] if c else None
    got = (ch_at(0.2), ch_at(5.9), ch_at(6.1), ch_at(11.9), ch_at(12.1))
    assert got == (0, 0, 1, 1, 2), 'charges at +0.2/5.9/6.1/11.9/12.1 s: %r (want 0 0 1 1 2)' % (got,)

    # stops at walls: the dummy behind the wall north of the centre room is never hit
    sw = {}

    def su(w):
        sw['d'] = h.spawn_at(w, 'dummy', 9.5, 5.5, pool=_pool())
        h.place(w, 9.5, 12.5, NORTH)

    def of(w, i, state):
        if i == 25:
            sw['flying'] = sum(1 for q in w.projectiles if q.owner is w.player)
    r = h.run('rampart', 40, timeline=[('tap', 3, 'ab2')], setup=su, on_frame=of, name='flame_wall')
    assert r.count('ability_used', slot='ab2') == 1
    assert not _dmg(r, sw['d']) and sw['flying'] == 0, 'flame strike went through a wall'
    return 'pierced 2 dummies behind a barrier (90 each, twice); charges %r' % (got,)


def check_quake(h):
    """3 dummies inside the cone within 8 cells take 120 each and have stun for 2.5 s; a dummy behind a wall and
    one outside the cone aren't hit; the front travels at 20 cells/s; kills are ult kills; RAMPART is rooted
    for 0.6 s."""
    st = {'trace': []}
    home = (10.0, 12.6, NORTH)

    def setup(w):
        st['walled'] = h.spawn_at(w, 'dummy', 10.5, 5.5, pool=_pool())
        h.place(w, *home)
        st['in'] = [h.spawn(w, 'dummy', 2.0, 0.0, pool=_pool()),       # (10.0, 10.6)
                    h.spawn(w, 'dummy', 3.5, -1.2, pool=_pool()),      # (8.8, 9.1), 18.9 deg
                    h.spawn(w, 'dummy', 4.8, 1.3, pool=_pool())]       # (11.3, 7.8), 15.2 deg
        st['kill'] = h.spawn(w, 'dummy', 3.0, 0.4, pool=_pool(100.0))
        st['out'] = h.spawn(w, 'dummy', 2.0, 1.6, pool=_pool())        # 38.7 deg: outside +-30

    def on_frame(w, i, state):
        p = w.player
        st['trace'].append((w.now, p.x, p.y, p.status.has('root', w.now)))
        if i == 5:
            st['shake'] = w.cam.shake_amp

    r = h.run('rampart', 60, timeline=[('tap', 5, 'ult'), ('hold', 6, 'fwd', 40)], setup=setup,
              on_frame=on_frame, debug={'inf_ult': True}, name='quake', shots=(8, 12))
    w = r.world
    tu = r.first('ult_used', hero='rampart')['t']
    hits = []
    for e in st['in']:
        ev = _dmg(r, e)
        assert len(ev) == 1 and abs(ev[0]['amount'] - 120.0) < EPS and ev[0]['ability'] == 'ult', \
            'quake on a dummy in the cone: %r' % [(d['amount'], d['ability']) for d in ev]
        th = ev[0]['t']
        dist = math.hypot(ev[0]['x'] - home[0], ev[0]['y'] - home[1])        # where it stood when hit
        hits.append((th - tu, dist))
        assert e.status.has('stun', th + 2.45) and not e.status.has('stun', th + 2.55), 'stun is not 2.5 s'
    assert not _dmg(r, st['walled']), 'dummy behind a wall was hit'
    assert not _dmg(r, st['out']), 'dummy outside the +-30 deg cone was hit'
    k = r.first('kill', target=lambda t: t is st['kill'])
    assert k is not None and k['ult'] and k['ability'] == 'ult', 'quake kill is not an ult kill: %r' % (k,)
    for dt, dist in hits:
        want = max(0.0, (dist - 0.3) / 20.0)
        assert want - EPS <= dt <= want + DT + EPS, 'front reached a dummy %.2f away after %.3f s (want %.3f)' % (
            dist, dt, want)
    root_at = {round(t - tu, 3): (x, y, rt) for t, x, y, rt in st['trace']}
    x0, y0 = home[0], home[1]
    for dt, (x, y, rt) in root_at.items():
        if 0.0 <= dt <= 0.55:
            assert rt and abs(x - x0) < EPS and abs(y - y0) < EPS, 'moved or not rooted %.2f s after the ult' % dt
        if dt >= 0.65:
            assert not rt, 'still rooted %.2f s after the ult' % dt
    assert w.player.y < y0 - 0.5, 'never moved after the root ended'
    assert st['shake'] >= 12.0, 'quake shake %.1f px' % st['shake']
    assert not [e for e in w.effects if type(e).__name__ == 'QuakeWave'], 'quake effect never expired'
    return 'hit at +%s s' % ', +'.join('%.3f' % dt for dt, _ in sorted(hits))


def check_quake_blocked_range_boss(h):
    """An enemy barrier across the origin-to-enemy line blocks the quake (and takes no damage); nothing beyond
    8 cells is hit; the boss is stunned for 2.5 x 0.4 = 1.0 s. Casting drops a raised barrier for 0.6 s."""
    from rwf.combat import Barrier
    from rwf.config import TEAM_ENEMY
    st = {'up': []}

    def setup(w):
        p = w.player
        b = Barrier(TEAM_ENEMY, 400, 1.0)
        b.set_pose(p.x + 2.0, p.y, math.pi)
        w.add_barrier(b)
        st['b'] = b
        st['d'] = h.spawn(w, 'dummy', 3.0, pool=_pool())

    def on_frame(w, i, state):
        st['up'].append((i, w.player_barrier() is not None))

    r = h.run('rampart', 50, timeline=[('hold', 2, 'alt', 45), ('tap', 10, 'ult')], setup=setup,
              on_frame=on_frame, debug={'inf_ult': True}, name='quake_blocked')
    assert not _dmg(r, st['d']), 'quake went through an enemy barrier'
    assert abs(st['b'].hp - 400.0) < EPS, 'the blocking barrier took quake damage'
    up = dict(st['up'])
    assert up[9] and not any(up[i] for i in range(10, 27)), 'barrier not dropped for the quake'
    assert any(up[i] for i in range(28, 45)), 'barrier did not come back after the quake with alt held'

    sb = {}

    def setup2(w):
        sb['boss'] = h.spawn(w, 'warden', 3.0)
        sb['near'] = h.spawn(w, 'dummy', 7.5, pool=_pool())
        sb['far'] = h.spawn(w, 'dummy', 9.0, pool=_pool())
    r = h.run('rampart', 30, timeline=[('tap', 3, 'ult')], setup=setup2, debug={'inf_ult': True},
              name='quake_boss')
    boss = sb['boss']
    ev = _dmg(r, boss)
    assert len(ev) == 1 and abs(ev[0]['raw'] - 120.0) < EPS, 'boss quake damage %r' % [d['raw'] for d in ev]
    th = ev[0]['t']
    assert boss.status.has('stun', th + 0.95) and not boss.status.has('stun', th + 1.05), 'boss stun is not 1.0 s'
    assert len(_dmg(r, sb['near'])) == 1, 'dummy 7.5 cells ahead not hit'
    assert not _dmg(r, sb['far']), 'dummy 9 cells ahead hit (length 8)'
    return 'barrier-blocked, boss stun 1.0 s, 7.5 hit / 9.0 missed'


# ============================ 3. drawing / HUD / budget ======================
def check_hud_and_drawing(h):
    """HUD contract (tile order, MELEE, 2 flame pips, barrier meter), every draw path in every pose, icons at
    52/72/96 px; with --shots the poses and an icon sheet are saved to tools/out/."""
    import pygame
    from rwf import core
    cls = core.HEROES['rampart']
    sheet = pygame.Surface((5 * 104 + 8, 3 * 104 + 8))
    sheet.fill((24, 28, 38))
    for i, slot in enumerate(('portrait', 'secondary', 'ab1', 'ab2', 'ult')):
        for j, size in enumerate((96, 72, 52)):
            cls.draw_icon(slot, sheet, pygame.Rect(8 + i * 104, 8 + j * 104, size, size))
    h.save(sheet, 'rampart_icons')

    st = {}

    def setup(w):
        st['d'] = h.spawn(w, 'dummy', 5.0, fire_every=0.4, bolt_damage=40.0, pool=_pool())
        st['near'] = h.spawn(w, 'dummy', 1.8, pool=_pool())

    def on_frame(w, i, state):
        p = w.player
        if i == 2:
            hs = p.hud_state(w)
            st['hud'] = hs
        if i == 70:
            st['meter70'] = p.hud_state(w).abilities[2].meter
            st['low'] = p.barrier.hp / p.barrier.max_hp
        if i == 140:
            st['charge_hud'] = p.hud_state(w).abilities[0]

    # 0-9 idle; 10 swing (shots 11/14: mid-sweep); 25-95 barrier up under fire (shots 40, 88: orange/low);
    # 110 flame strike (shot 113); 130 charge east, pins the near dummy (shot 136); 170 quake (shots 172, 178)
    tl = [('tap', 10, 'fire'), ('hold', 25, 'alt', 70), ('call', 26, lambda w: setattr(w.player.barrier, 'hp', 300.0)),
          ('tap', 110, 'ab2'), ('tap', 130, 'ab1'), ('aim', 168, math.pi, 0.0), ('tap', 170, 'ult')]
    r = h.run('rampart', 190, timeline=tl, setup=setup, on_frame=on_frame, debug={'inf_ult': True},
              name='rampart_vis', shots=(5, 11, 14, 40, 88, 113, 136, 172, 178))
    hs = st['hud']
    assert [a.slot for a in hs.abilities] == ['ab1', 'ab2', 'secondary'], [a.slot for a in hs.abilities]
    assert hs.max_ammo == 0 and hs.ammo == 0 and hs.abilities[1].max_charges == 2
    assert hs.abilities[2].meter == 1.0 and abs(st['meter70'] - st['low']) < EPS and st['low'] < 1.0
    assert st['charge_hud'].active and st['charge_hud'].cd_left == 0.0, 'charge tile while charging %r' % (
        st['charge_hud'],)
    w = r.world
    p = w.player
    surf = pygame.Surface((1024, 768))
    for fn in (p.draw_viewmodel, p.draw_overlay, p.draw_crosshair):
        fn(surf, w)
    return 'icons 5 x 3 sizes; poses drawn%s' % (' (PNGs in tools/out)' if h.shots else '')


def check_no_big_surfaces(h):
    """8.1 / 8.12: after warm-up, no surface of 256x256 or larger is allocated by RAMPART's draw and update
    paths (barrier overlay both colours, hits, charge, flame strikes, quake) over 240 frames."""
    import time
    st = {}

    def setup(w):
        h.spawn(w, 'dummy', 5.0, fire_every=0.3, bolt_damage=40.0, pool=_pool(100000.0))

    def on_frame(w, i, state):
        if i == 20:
            h.count_surfaces(True)
        if i == 60:
            p = w.player
            t0 = time.perf_counter()
            import pygame
            s = h.screen
            for _ in range(50):
                p.draw_overlay(s, w)
            st['ov_ms'] = (time.perf_counter() - t0) * 1000.0 / 50
            t0 = time.perf_counter()
            for _ in range(50):
                p.draw_viewmodel(s, w)
            st['vm_ms'] = (time.perf_counter() - t0) * 1000.0 / 50
            del pygame
        if i == 259:
            st['big'] = h.big_surfaces
            h.count_surfaces(False)

    tl = [('hold', 2, 'alt', 12), ('hold', 30, 'alt', 60), ('tap', 100, 'ab2'), ('tap', 110, 'ab1'),
          ('hold', 160, 'fire', 30), ('tap', 200, 'ult'), ('tap', 210, 'ab2'), ('hold', 220, 'alt', 30)]
    try:
        h.run('rampart', 262, timeline=tl, setup=setup, on_frame=on_frame, debug={'inf_ult': True,
                                                                                  'no_cooldowns': True},
              name='rampart_surfaces')
    finally:
        h.count_surfaces(False)
    assert st.get('big', 99) == 0, '%d surfaces >= 256x256 allocated after warm-up' % st.get('big', 99)
    assert st['ov_ms'] < 6.0, 'barrier overlay %.2f ms per frame' % st['ov_ms']
    return 'big surfaces 0; barrier overlay %.2f ms, viewmodel %.2f ms per draw (desktop)' % (
        st['ov_ms'], st['vm_ms'])
