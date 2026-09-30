"""ENEMIES acceptance (spec 9.4): the 5 kinds, elites, stage scaling, the director and the capture objective.

Per-kind setup (9.4): no_director, god, the player at (2.5, 7.5) facing east, one enemy at (7.5, 7.5)
(h.spawn fwd 5.0), 600 frames at 30 fps with a passive player. Other checks drive the real WaveDirector
through the debug hooks (start_wave, autokill, auto_capture). Every run also gets the harness invariants
(no NaN, never inside a wall, caps incl. alive <= 12, LOS budget). --shots saves a painter gallery and
in-world screenshots to tools/out/.
"""
import math

FPS = 30
DT = 1.0 / FPS
HOME = (2.5, 7.5, 0.0)
POINT = (10.0, 10.0)
STATES = {
    'trooper': ('idle', 'move', 'windup', 'attack', 'stun'),
    'slicer': ('idle', 'move', 'windup', 'lunge', 'stun'),
    'detonator': ('idle', 'move', 'armed_a', 'armed_b', 'stun'),
    'eradicator': ('idle', 'move', 'attack', 'stun'),
    'warden': ('recon', 'recon_attack', 'sentry_windup', 'sentry', 'stomp_windup', 'stun'),
}
KINDS = tuple(STATES)


def _rwf():
    from rwf import combat, config, core, enemies, render, theme, waves
    return combat, config, core, enemies, render, theme, waves


def _single(h, kind, frames=600, *, fwd=5.0, on_frame=None, timeline=(), debug=None, setup=None, name=None,
            shots=()):
    """One enemy of `kind` spawned fwd cells ahead of the default start; returns (Result, enemy, trace).
    trace[i] = (vstate, x, y, dist to player) after frame i; trace['bolts'] = [(frame, projectile)]."""
    rec = {'e': None}
    trace = {'bolts': [], 'seen': set()}

    def _setup(w):
        rec['e'] = h.spawn(w, kind, fwd)
        if setup is not None:
            setup(w, rec['e'])

    def _on_frame(w, i, st):
        e = rec['e']
        p = w.player
        trace[i] = (e.vstate, e.x, e.y, math.hypot(e.x - p.x, e.y - p.y))
        for pr in w.projectiles:
            if pr.owner is e and id(pr) not in trace['seen']:
                trace['seen'].add(id(pr))
                trace['bolts'].append((i, pr))
        if on_frame is not None:
            return on_frame(w, i, st, e)
        return None

    r = h.run('vector', frames, timeline=timeline, debug=debug, setup=_setup, on_frame=_on_frame,
              name=name or kind, shots=shots)
    return r, rec['e'], trace


def _runs(trace, frames, state):
    """[(start, length)] runs of consecutive frames with vstate == state."""
    out = []
    start = None
    for i in range(frames):
        v = trace.get(i, (None,))[0]
        if v == state and start is None:
            start = i
        elif v != state and start is not None:
            out.append((start, i - start))
            start = None
    if start is not None:
        out.append((start, frames - start))
    return out


def _pds():
    """The integration balance lever on enemy damage to the player (enemies.TUNING, spec 9.6 +-15%)."""
    from rwf import enemies
    return enemies.TUNING['player_damage_scale']


def _kill(w, e, amount=100000.0):
    from rwf import combat
    return combat.apply_damage(w, e, amount, w.player, ability='primary')


# ============================ per kind (9.4 table) ===========================
def check_trooper(h):
    """>= 1 bolt; player_hurt within 10 s; mean distance over the last 5 s in 3-8; 0.4 s windup per shot."""
    r, e, tr = _single(h, 'trooper', 600, shots=(45,), name='trooper')
    bolts = tr['bolts']
    assert bolts, 'the trooper never fired'
    hurt = r.frames_of('player_hurt')
    assert hurt and hurt[0] <= 10 * FPS, 'no player_hurt within 10 s (first at frame %r)' % (hurt[:1],)
    dists = [tr[i][3] for i in range(450, 600)]
    mean = sum(dists) / len(dists)
    assert 3.0 <= mean <= 8.0, 'mean distance over the last 5 s %.2f (want 3-8)' % mean
    wind = _runs(tr, 600, 'windup')
    for f, pr in bolts:
        before = [ln for s, ln in wind if s <= f < s + ln]
        assert before and before[0] >= int(0.4 * FPS), 'bolt at frame %d without a 0.4 s windup (%r)' % (f, before)
        assert pr.ability == 'bolt' and abs(pr.damage - 10.0 * _pds()) < 1e-6 and pr.radius == 0.12, \
            'trooper bolt damage %.1f radius %.2f' % (pr.damage, pr.radius)
    gaps = [b[0] - a[0] for a, b in zip(bolts, bolts[1:])]
    assert all(g >= int(2.0 * FPS) - 1 for g in gaps), 'fire cycle faster than 2.0 s: gaps %r' % gaps
    raw = [d['amount'] for d in r.where('player_hurt', ability='bolt')]
    assert raw and all(abs(a - 10.0 * _pds()) < 1e-6 for a in raw), 'bolt damage %r' % raw[:4]
    assert 'attack' in {tr[i][0] for i in range(600)}, 'no attack state after firing'
    return 'bolts %d, first hurt at %.1f s, mean dist %.2f, windup runs %s' % (
        len(bolts), hurt[0] / FPS, mean, sorted({ln for _, ln in wind}))


def check_slicer(h):
    """windup -> lunge; lunge displacement >= 2.0 within 0.4 s; player_hurt >= 1."""
    r, e, tr = _single(h, 'slicer', 600, shots=(20,), name='slicer')
    lunges = []
    for i in range(1, 600):
        if tr[i][0] == 'lunge' and tr[i - 1][0] == 'windup':
            x0, y0 = tr[i - 1][1], tr[i - 1][2]
            best = 0.0
            for j in range(i, min(600, i + int(0.4 * FPS) + 1)):
                best = max(best, math.hypot(tr[j][1] - x0, tr[j][2] - y0))
            lunges.append((i, best))
    assert lunges, 'never went windup -> lunge (states %r)' % sorted({tr[i][0] for i in range(600)})
    wind = _runs(tr, 600, 'windup')
    assert all(ln >= int(0.35 * FPS) for s, ln in wind if any(s + ln == f for f, _ in lunges)), \
        'windup shorter than 0.35 s: %r' % wind
    assert lunges[0][1] >= 2.0, 'first lunge displacement %.2f in 0.4 s (want >= 2.0)' % lunges[0][1]
    assert r.count('player_hurt') >= 1, 'the slicer never hurt the player'
    hits = r.where('player_hurt', ability='lunge')
    assert hits and all(abs(d['amount'] - 20.0 * _pds()) < 1e-6 for d in hits),         'lunge damage %r' % [d['amount'] for d in hits]
    return 'lunges %d, first displacement %.2f, lunge hits %d, player_hurt %d' % (
        len(lunges), lunges[0][1], len(hits), r.count('player_hurt'))


def check_detonator(h):
    """Walk/rush, arm at 1.5 (blinking armed_a/armed_b + beeps), explode: explosion + player_hurt, no score."""
    r, e, tr = _single(h, 'detonator', 300, name='detonator', shots=(60,))
    seen = {tr[i][0] for i in range(300) if i in tr}
    assert {'armed_a', 'armed_b'} <= seen, 'no blinking fuse (states %r)' % sorted(seen)
    assert r.count('explosion', team=1) >= 1, 'no explosion'
    hurt = r.where('player_hurt', ability='blast')
    assert hurt and 30.0 * _pds() - 1e-6 <= hurt[0]['amount'] <= 60.0 * _pds() + 1e-6, 'blast player_hurt %r' % hurt[:1]
    assert not e.alive and r.world.score == 0 and r.count('kill') == 0, 'self-destruct must give no kill/score'
    arm = _runs(tr, 300, 'armed_a')[0][0]
    boom = r.frames_of('explosion')[0]
    assert abs((boom - arm) / FPS - 0.8) <= 0.1, 'fuse %.2f s (want 0.8)' % ((boom - arm) / FPS)
    beeps = [f for f in r.frames_of('sfx', name='beep') if arm <= f <= boom]
    assert len(beeps) >= 3, 'fuse beeps %d' % len(beeps)
    return 'armed at %.2f s, exploded at %.2f s, player took %.1f, beeps %d' % (
        arm / FPS, boom / FPS, hurt[0]['amount'], len(beeps))


def check_detonator_chain(h):
    """Killed by the player at 5 cells with a trooper 1.0 away: 0.25 s later the trooper takes >= 100 and any
    resulting kill has the player as source (ability 'chain')."""
    st = {}

    def setup(w, det):
        st['t'] = h.spawn(w, 'trooper', 6.0)

    def kill(w):
        st['det'] = [e for e in w.enemies if e.KIND == 'detonator'][0]
        st['kill_t'] = w.now
        _kill(w, st['det'], 10000)
    r, det, tr = _single(h, 'detonator', 60, setup=setup, timeline=[('call', 3, kill)], name='det_chain')
    tro = st['t']
    dmg = r.where('damage', target=tro)
    total = sum(d['raw'] for d in dmg)
    assert total >= 100.0 - 1e-6, 'trooper took %.1f (raw) from the chain' % total
    assert all(d['ability'] == 'chain' and d['source'] is r.world.player for d in dmg), \
        'chain damage not credited to the player: %r' % [(d['ability'], d['source']) for d in dmg]
    kills = r.where('kill', target=tro)
    assert all(d['source'] is r.world.player for d in kills), 'chain kill source %r' % [d['source'] for d in kills]
    first = r.first('damage', target=tro)
    delay = first['t'] - st['kill_t']
    assert 0.2 <= delay <= 0.3 + DT, 'chain delay %.2f s (want 0.25)' % delay
    assert r.count('player_hurt') == 0, 'the chain hurt a player 5 cells away'
    assert r.world.score == 15 + (10 if kills else 0), 'score %d' % r.world.score
    return 'trooper took %.0f %.2f s later, kills %d (player-credited), score %d' % (
        total, delay, len(kills), r.world.score)


def check_detonator_stun_cancels_fuse(h):
    """A stun during the fuse cancels it (4.4): no blast at the old fuse time; it re-arms after the stun."""
    st = {}

    def stun(w):
        e = [x for x in w.enemies if x.KIND == 'detonator'][0]
        st['armed'] = e.vstate in ('armed_a', 'armed_b')
        e.status.add('stun', 1.0, w.now)
    r, e, tr = _single(h, 'detonator', 120, fwd=1.4, timeline=[('call', 6, stun)], name='det_stun')
    assert st['armed'], 'not armed when stunned'
    boom = r.frames_of('explosion')
    assert boom and boom[0] >= 6 + FPS + int(0.8 * FPS) - 2, 'exploded at frame %r despite the stun' % boom[:1]
    return 'stunned at frame 6 while armed; exploded at frame %d (after re-arming)' % boom[0]


def check_eradicator(h):
    """Enemy barrier within 3 s of LOS; hitscan from the front hits the barrier, from behind the enemy;
    turn rate <= 90 deg/s; 8 s up / 8 s cooldown; bursts of 3 bolts 0.15 s apart."""
    from rwf import combat
    from rwf.config import TEAM_ENEMY
    st = {'up': [], 'angles': {}}

    def on_frame(w, i, s, e):
        b = [x for x in w.barriers if x.team == TEAM_ENEMY and x.owner is e and x.active]
        st['up'].append(bool(b))
        st['angles'][i] = e.angle
        if b and 'hp' not in st:
            st['hp'] = b[0].max_hp

    def probe(w):
        e = [x for x in w.enemies if x.KIND == 'eradicator'][0]
        p = w.player
        st['front'] = combat.hitscan(w, p, 0.0, 0.0).kind
        h.place(w, e.x + 2.0, e.y, math.pi)
        hit = combat.hitscan(w, p, math.pi, 0.0)
        st['behind'] = (hit.kind, hit.target is e)
        st['probe_angle'] = e.angle
    r, e, tr = _single(h, 'eradicator', 600, on_frame=on_frame, timeline=[('call', 100, probe)],
                       name='eradicator', shots=(40, 110))
    ups = st['up']
    first = ups.index(True) if True in ups else None
    assert first is not None and first <= 3 * FPS, 'no enemy barrier within 3 s (first at %r)' % first
    assert abs(st['hp'] - 400.0) < 1e-6, 'barrier max hp %.0f' % st['hp']
    assert st['front'] == 'barrier', 'hitscan from the front gave %r' % st['front']
    assert st['behind'] == ('enemy', True), 'hitscan from behind gave %r' % (st['behind'],)
    lim = math.radians(90.0) * DT + 1e-6
    turns = [abs(math.remainder(st['angles'][i] - st['angles'][i - 1], 2 * math.pi)) for i in range(101, 170)]
    assert max(turns) <= lim, 'turned %.1f deg in one frame (limit 3 deg)' % math.degrees(max(turns))
    assert sum(turns) > math.radians(90), 'never turned toward the player behind it'
    runs = []
    cur = None
    for i, u in enumerate(ups):
        if u and cur is None:
            cur = i
        elif not u and cur is not None:
            runs.append((cur, i - cur))
            cur = None
    assert runs, 'the barrier never came down'
    s0, ln = runs[0]
    assert abs(ln / FPS - 8.0) <= 0.25, 'barrier stayed up %.2f s (want 8)' % (ln / FPS)
    nxt = ups.index(True, s0 + ln)
    assert abs((nxt - (s0 + ln)) / FPS - 8.0) <= 0.35, 'cooldown %.2f s (want 8)' % ((nxt - s0 - ln) / FPS)
    frames = [f for f, _ in tr['bolts']]
    assert len(frames) >= 3, 'bolts %r' % frames
    a, b, c = frames[:3]
    assert 3 <= b - a <= 6 and 3 <= c - b <= 6, 'burst spacing %r (want 0.15 s)' % frames[:3]
    starts = [f for k, f in enumerate(frames) if k == 0 or f - frames[k - 1] > 15]
    assert all(y - x >= int(3.0 * FPS) - 1 for x, y in zip(starts, starts[1:])), 'bursts closer than 3 s %r' % starts
    return 'barrier at frame %d (hp %.0f), up %.1f s, down %.1f s; bolts %d in %d bursts' % (
        first, st['hp'], ln / FPS, (nxt - s0 - ln) / FPS, len(frames), len(starts))


def check_warden(h):
    """Recon bolts; sentry_windup >= 0.8 s before the first sentry bolt, within 13 s; 10 bolts/s for 4 s."""
    r, e, tr = _single(h, 'warden', 12 * FPS + 150, name='warden', shots=(200, 12 * FPS + 30))
    recon = [f for f, pr in tr['bolts'] if pr.ability == 'recon']
    sentry = [f for f, pr in tr['bolts'] if pr.ability == 'sentry']
    assert recon, 'no recon bolts'
    assert sentry, 'no sentry bolts'
    first = sentry[0]
    assert first <= 13 * FPS, 'first sentry bolt at %.1f s (want within 13 s)' % (first / FPS)
    wind = [s for s, ln in _runs(tr, first + 1, 'sentry_windup')]
    assert wind and (first - wind[-1]) >= int(0.8 * FPS), 'sentry_windup only %d frames before the first sentry bolt' % (
        (first - wind[-1]) if wind else -1)
    burst = [f for f in sentry if f < first + 4 * FPS + 2]
    assert 36 <= len(burst) <= 42, 'sentry fired %d bolts in 4 s (want ~40)' % len(burst)
    pr = [p for f, p in tr['bolts'] if p.ability == 'sentry'][0]
    assert abs(pr.damage - 6.0 * _pds()) < 1e-6 and pr.color == (255, 220, 60), 'sentry bolt %r %r' % (
        pr.damage, pr.color)
    gaps = [b - a for a, b in zip(recon, recon[1:]) if b < first - FPS]
    assert gaps and min(gaps) >= int(0.6 * FPS) - 1, 'recon cadence %r (want 0.6 s)' % gaps[:6]
    assert r.count('sfx', name='warn') >= 1, 'no warn sfx on the windup'
    return 'recon bolts %d, windup at %.2f s, first sentry bolt at %.2f s, sentry burst %d bolts' % (
        len(recon), wind[-1] / FPS, first / FPS, len(burst))


def check_warden_phase2(h):
    """Damage to 49% of health+armor: boss_phase (phase 2), +300 shields, 2 slicers with summon=True."""
    st = {}

    def hurt(w):
        from rwf import combat
        e = [x for x in w.enemies if x.KIND == 'warden'][0]
        pl = e.pool
        mx = pl.max_health + pl.max_armor
        while pl.health + pl.armor > 0.49 * mx:
            combat.apply_damage(w, e, 25.0, w.player)
        st['e'] = e
    r, e, tr = _single(h, 'warden', 90, timeline=[('call', 30, hurt)], name='warden_phase', shots=(40,))
    ph = r.where('boss_phase')
    assert len(ph) == 1 and ph[0]['phase'] == 2 and ph[0]['enemy'] is e, 'boss_phase %r' % ph
    sums = r.where('enemy_spawn', summon=True)
    assert len(sums) == 2 and all(d['kind'] == 'slicer' for d in sums), 'summons %r' % [d['kind'] for d in sums]
    assert r.frames_of('boss_phase')[0] <= 32, 'phase 2 late (frame %d)' % r.frames_of('boss_phase')[0]
    assert abs(e.pool.max_shields - 300.0) < 1e-6, 'phase-2 shields %.0f' % e.pool.max_shields
    for d in sums:
        s = d['enemy']
        dd = math.hypot(s.x - e.x, s.y - e.y)
        assert 0.9 <= dd <= 3.1 + 1.0, 'summon %.2f cells from the warden' % dd
    return 'boss_phase at frame %d, shields %.0f, summons at %s' % (
        r.frames_of('boss_phase')[0], e.pool.max_shields,
        ', '.join('(%.1f, %.1f)' % (d['enemy'].x, d['enemy'].y) for d in sums))


def check_warden_stomp(h):
    """Player within 2 cells: stomp_windup (0.6 s red ring), then 40 damage, knockback and a slow."""
    from rwf import render
    st = {'slow': None, 'ring': False, 'x0': None}

    def on_frame(w, i, s, e):
        if e.vstate == 'stomp_windup' and not st['ring']:
            sc = render.build_scene(w)
            st['ring'] = any(abs(rg[2] - 3.0) < 1e-6 for rg in sc.rings)
            st['x0'] = w.player.x
        if st['slow'] is None and w.player.status.has('slow', w.now):
            st['slow'] = i
            st['x1'] = w.player.x
    r, e, tr = _single(h, 'warden', 60, fwd=2.0, on_frame=on_frame, name='warden_stomp', shots=(8,))
    wind = _runs(tr, 60, 'stomp_windup')
    assert wind, 'no stomp windup with the player 2 cells away'
    assert wind[0][1] >= int(0.6 * FPS) - 1, 'stomp windup %d frames (want 0.6 s)' % wind[0][1]
    assert st['ring'], 'no r 3.0 floor ring during the stomp windup'
    assert st['slow'] is not None, 'no slow status after the stomp'
    hurt = r.where('player_hurt', ability='stomp')
    assert hurt and abs(hurt[0]['amount'] - 40.0 * _pds()) < 1e-6, 'stomp damage %r' % hurt[:1]
    assert abs(st['x0'] - st['x1']) >= 1.0, 'knockback moved the player %.2f' % abs(st['x0'] - st['x1'])
    return 'windup %d frames, slowed at frame %d, knocked back %.2f cells' % (
        wind[0][1], st['slow'], abs(st['x0'] - st['x1']))


# ============================ every kind =====================================
def check_all_kinds_die_and_score(h):
    """10000 damage kills each kind (kill event, score += SCORE x stage)."""
    notes = []
    for kind in KINDS:
        st = {}

        def kill(w, kind=kind):
            e = [x for x in w.enemies if x.KIND == kind][0]
            st['score0'] = w.score
            st['e'] = e
            _kill(w, e, 10000.0)
        r, e, tr = _single(h, kind, 20, timeline=[('call', 5, kill)], name='die_' + kind)
        ks = r.where('kill', target=st['e'])
        assert len(ks) == 1 and ks[0]['source'] is r.world.player, '%s: kill events %r' % (kind, ks)
        cls = type(st['e'])
        assert r.world.score - st['score0'] == cls.SCORE * 1, '%s: score +%d (want %d)' % (
            kind, r.world.score - st['score0'], cls.SCORE)
        assert ks[0]['boss'] == (kind == 'warden')
        notes.append('%s+%d' % (kind, cls.SCORE))
    return ', '.join(notes)


def check_all_kinds_stun_freezes(h):
    """A 2 s stun gives zero displacement and the 'stun' painter state for every kind."""
    notes = []
    for kind in KINDS:
        st = {}

        def stun(w, kind=kind):
            e = [x for x in w.enemies if x.KIND == kind][0]
            e.status.add('stun', 2.0, w.now)
            st['pos'] = (e.x, e.y)
            st['t'] = w.now

        def on_frame(w, i, s, e):
            if 'pos' in st and w.now < st['t'] + 2.0 - 1e-6:
                d = math.hypot(e.x - st['pos'][0], e.y - st['pos'][1])
                st['max'] = max(st.get('max', 0.0), d)
                st.setdefault('states', set()).add(e.vstate)
                st['n'] = st.get('n', 0) + 1
        r, e, tr = _single(h, kind, 90, timeline=[('call', 10, stun)], on_frame=on_frame, name='stun_' + kind)
        assert st.get('n', 0) >= 2 * FPS - 2, '%s: only %d stunned frames' % (kind, st.get('n', 0))
        assert st['max'] <= 1e-9, '%s moved %.3f while stunned' % (kind, st['max'])
        assert st['states'] == {'stun'}, '%s states while stunned %r' % (kind, st['states'])
        notes.append(kind)
    return 'frozen: ' + ', '.join(notes)


def check_painters_every_state(h):
    """Every painter draws every 4.4 state (+ an unknown one), elite or not, code-drawn AND through the PNG
    path (theme.enemy_image patched to return a surface); hot/attack states look different from idle."""
    import pygame
    combat, config, core, enemies, render, theme, waves = _rwf()
    orig = theme.enemy_image
    out = []
    for use_img in (False, True):
        if use_img:
            fake = pygame.Surface((60, 120), pygame.SRCALPHA)
            pygame.draw.rect(fake, (200, 120, 90), (8, 4, 44, 112), border_radius=6)
            theme.enemy_image = lambda kind, base_h, _f=fake: _f
        try:
            for kind, states in STATES.items():
                fn, bw, bh = render.PAINTERS[kind]
                shots = {}
                for s in states + ('no_such_state',):
                    for elite in (False, True):
                        surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
                        fn(surf, s, elite)
                        box = surf.get_bounding_rect()       # a tall PNG fitted into a wide base is narrow
                        need = (0.1 if use_img else 0.3) * bw * bh
                        assert box.w * box.h >= need, '%s/%s drew only %r (img %s)' % (kind, s, box, use_img)
                        shots[(s, elite)] = pygame.image.tobytes(surf, 'RGBA')
                idle = STATES[kind][0]
                for s in states[1:]:
                    if s in ('move',) and use_img:
                        continue
                    assert shots[(s, False)] != shots[(idle, False)], '%s: %s looks like %s (img %s)' % (
                        kind, s, idle, use_img)
                assert shots[(idle, True)] != shots[(idle, False)], '%s: elite looks like non-elite' % kind
                out.append(kind)
        finally:
            theme.enemy_image = orig
    # 'no_such_state' draws like the idle state (7.7) in the code path
    for kind in KINDS:
        fn, bw, bh = render.PAINTERS[kind]
        a = pygame.Surface((bw, bh), pygame.SRCALPHA)
        b = pygame.Surface((bw, bh), pygame.SRCALPHA)
        fn(a, 'no_such_state', False)
        fn(b, STATES[kind][0], False)
        assert pygame.image.tobytes(a, 'RGBA') == pygame.image.tobytes(b, 'RGBA'), '%s: unknown state != idle' % kind
    return '%d painters x states x elite, code-drawn and PNG path' % (len(out) // 2)


def check_stage_scaling_and_elites(h):
    """4.3: pools / damage x(1 + 0.15k), speed x min(1 + 0.05k, 1.3); elites pools x1.6, speed x1.2, score x2;
    barrier and phase-2 shields scale with the pools; the boss is never elite."""
    combat, config, core, enemies, render, theme, waves = _rwf()
    for stage in (1, 3, 8):
        w = h.make_world()
        w.director.stage = stage
        k = stage - 1
        pm = 1 + 0.15 * k
        sm = min(1 + 0.05 * k, 1.3)
        for kind in KINDS:
            cls = core.ENEMY_TYPES[kind]
            for elite in (False, True):
                e = w.spawn_enemy(kind, 10.5, 7.5, elite=elite)
                el = elite and kind != 'warden'
                want = (cls.BASE_HEALTH + cls.BASE_ARMOR + cls.BASE_SHIELDS) * pm * (1.6 if el else 1.0)
                assert abs(e.pool.max_total - want) < 1e-6, '%s st%d elite %s pools %.1f want %.1f' % (
                    kind, stage, elite, e.pool.max_total, want)
                assert abs(e.speed - cls.BASE_SPEED * sm * (1.2 if el else 1.0)) < 1e-9
                assert abs(e.dmg_mult - pm) < 1e-9 and e.elite == el
                if kind == 'eradicator':
                    assert abs(e.barrier.max_hp - 400 * pm * (1.6 if el else 1.0)) < 1e-6, 'barrier hp %.1f' % e.barrier.max_hp
                e.remove_silently(w, 0)
    # bolt damage and elite score, in a run at stage 3
    st = {}

    def pre(w):
        w.director.stage = 3
        st['e'] = w.spawn_enemy('trooper', 7.5, 7.5, elite=True)
    r = h.run('vector', 120, timeline=[('call', 0, pre), ('call', 110, lambda w: _kill(w, st['e']))], name='scaling')
    raw = [d['amount'] for d in r.where('player_hurt', ability='bolt')]
    assert raw and all(abs(a - 13.0 * _pds()) < 1e-6 for a in raw), 'stage-3 trooper bolt %r (want 13 x lever)' % raw
    ks = r.where('kill', target=st['e'])
    assert ks and ks[0]['score'] == 10 * 2 * 3, 'elite stage-3 trooper score %r (want 60)' % [d['score'] for d in ks]
    # phase-2 shields at stage 3
    w = h.make_world()
    w.director.stage = 3
    b = w.spawn_enemy('warden', 10.5, 7.5)
    pl = b.pool
    pl.armor = 0.0
    pl.health = 0.45 * (pl.max_health + pl.max_armor)
    b._check_phase(w)
    assert abs(pl.max_shields - 390.0) < 1e-6, 'stage-3 phase-2 shields %.0f (want 390)' % pl.max_shields
    return 'pools/speed/damage/barrier/shields scale; elite x1.6/x1.2/x2 score; stage-3 bolt 13'


# ============================ director / waves ================================
def _director_run(h, frames, *, start_wave=1, debug=None, setup=None, on_frame=None, timeline=(), name='waves',
                  shots=(), seed=1):
    dbg = {'no_director': False, 'start_wave': start_wave}
    dbg.update(debug or {})
    return h.run('vector', frames, debug=dbg, setup=setup, on_frame=on_frame, timeline=timeline, name=name,
                 shots=shots, seed=seed)


def check_capture_captured(h):
    """Capture wave with auto_capture and the player on the point: captured; everyone self-destructs with no
    score or kill event; +100 x stage score and +20% ult; the wave then clears."""
    st = {'u0': None}

    def setup(w):
        h.place(w, POINT[0], POINT[1], 0.0)

    def on_frame(w, i, s):
        if st['u0'] is None:
            st['u0'] = w.player.ult_charge
        if r_obj(w) and 'alive_before' not in st and w.director.objective.progress > 0.8:
            st['alive_before'] = len(w.alive_enemies())
        return None

    def r_obj(w):
        return w.director.objective is not None
    r = _director_run(h, 120, start_wave=3, debug={'auto_capture': True}, setup=setup, on_frame=on_frame,
                      name='capture', shots=(20,))
    states = [d['state'] for d in r.where('objective')]
    assert 'captured' in states, 'objective never captured: %r' % states
    assert states.index('capturing') < states.index('captured'), 'order %r' % states
    fcap = r.frames_of('objective', state='captured')[0]
    assert fcap <= int(1.3 * FPS) + 2, 'captured at frame %d (x10 = 1.2 s)' % fcap
    assert st.get('alive_before', 0) >= 1, 'no enemy alive to self-destruct'
    assert r.count('kill') == 0, 'self-destruct produced kill events'
    assert r.world.score == 100, 'score %d (want the +100 capture reward only)' % r.world.score
    gain = r.world.player.ult_charge - st['u0']
    assert gain >= 0.20 * r.world.player.ULT_COST - 1e-6, 'ult +%.0f (want +20%% of cost)' % gain
    wc = r.frames_of('wave_clear')
    assert wc and wc[0] == fcap, 'wave_clear %r vs captured frame %d' % (wc, fcap)
    assert not r.world.alive_enemies(), 'enemies left after the capture'
    ob = r.world.director.objective
    assert ob.state == 'captured' and not ob.player_inside, 'player_inside must drop once resolved (stats obj_time)'
    return 'captured at %.2f s, %d self-destructed, score %d, ult +%.0f, states %s' % (
        fcap / FPS, st['alive_before'], r.world.score, gain, '>'.join(dict.fromkeys(states)))


def check_capture_failed(h):
    """Timer expiring with the player outside gives 'failed'; the trickle stops; the wave clears only once the
    remaining enemies are killed; no reward."""
    st = {}

    def shorten(w):
        st['tl5'] = w.director.objective.time_left      # 90 s limit, 5 frames in (then cut to 1 s for speed)
        w.director.objective.time_left = 1.0

    def on_frame(w, i, s):
        d = w.director
        ob = d.objective
        if ob is not None and ob.state == 'failed' and 'f' not in st:
            st['f'] = i
            st['trickle'] = d.trickle_left
        if 'f' in st and i == st['f'] + 20:
            st['state_after'] = d.state
            st['alive_after'] = len(w.alive_enemies())
            for e in w.alive_enemies():
                _kill(w, e)
        return None
    r = _director_run(h, 150, start_wave=3, timeline=[('call', 5, shorten)], on_frame=on_frame, name='capture_fail')
    assert abs(st['tl5'] - (90.0 - 5 * DT)) < 1e-6, 'time limit %.3f after 5 frames (want 90 s)' % st['tl5']
    assert 'f' in st, 'objective never failed: %r' % [d['state'] for d in r.where('objective')]
    assert abs(st['f'] - (5 + FPS)) <= 2, 'failed at frame %d (want ~%d)' % (st['f'], 5 + FPS)
    assert st['trickle'] == 0, 'trickle still %d after failing' % st['trickle']
    assert st['alive_after'] >= 1 and st['state_after'] == 'active', 'wave %s with %d alive after failing' % (
        st['state_after'], st['alive_after'])
    wc = r.frames_of('wave_clear')
    assert wc and st['f'] + 20 <= wc[0] <= st['f'] + 21, 'wave_clear %r (want right after the last kill)' % wc
    kills = r.total('kill', 'score')
    assert r.world.score == kills, 'score %d includes a reward (kills %d)' % (r.world.score, kills)
    return 'failed at %.2f s, %d left to kill, cleared after the kills, score %d' % (
        st['f'] / FPS, st['alive_after'], r.world.score)


def check_capture_contested_overtime(h):
    """contested (no progress) -> capturing (a tick a second) -> overtime at 0 s with the player inside ->
    failed 0.5 s after leaving."""
    st = {}

    def setup(w):
        h.place(w, POINT[0], POINT[1], 0.0)

    def add_dummy(w):
        st['d'] = w.spawn_enemy('dummy', POINT[0] + 0.8, POINT[1])
        w.director.trickle_left = 0         # keep trickle enemies off the point: only the dummy contests

    def drop_dummy(w):
        st['p_contested'] = w.director.objective.progress
        st['d'].remove_silently(w, 0)

    def expire(w):
        w.director.objective.time_left = 0.5

    def leave(w):
        h.place(w, 10.5, 12.5, 0.0)
    tl = [('call', 2, add_dummy), ('call', 30, drop_dummy), ('call', 110, expire), ('call', 150, leave)]
    r = _director_run(h, 190, start_wave=3, setup=setup, timeline=tl, name='capture_ot', shots=(20, 60, 130))
    ev = r.where('objective')
    seq = [d['state'] for d in ev]
    order = [x for k, x in enumerate(seq) if k == 0 or seq[k - 1] != x]
    assert order == ['capturing', 'contested', 'capturing', 'overtime', 'failed'], 'objective states %r' % seq
    assert st['p_contested'] < 0.05, 'progress %.3f while contested' % st['p_contested']
    ticks = [d for d in ev if d['state'] == 'capturing']
    assert len(ticks) >= 3, 'capturing ticks %d (want one a second)' % len(ticks)
    fo = r.frames_of('objective', state='overtime')[0]
    ff = r.frames_of('objective', state='failed')[0]
    assert 110 <= fo <= 128, 'overtime at frame %d' % fo
    assert 150 + int(0.5 * FPS) <= ff <= 150 + int(0.5 * FPS) + 3, 'failed at frame %d (left at 150)' % ff
    return 'states %s; capturing events %d; overtime at %.2f s, failed %.2f s after leaving' % (
        '>'.join(order), len(ticks), fo / FPS, (ff - 150) / FPS)


def check_alive_cap_and_batches(h):
    """Stage-2 W4 (T5 S4 D3 E3): first batch of 10 with every eradicator; one refill per 1.5 s while < 10;
    alive regular enemies never exceed 10 (12 with summons); spawns >= 7 cells from the player."""
    st = {'max_reg': 0, 'max_all': 0, 'at': {}}

    def setup(w):
        def on_spawn(d):
            p = w.player
            st['at'][d['enemy'].id] = math.hypot(d['enemy'].x - p.x, d['enemy'].y - p.y)
        w.bus.on('enemy_spawn', on_spawn)

    def on_frame(w, i, s):
        al = w.alive_enemies()
        st['max_reg'] = max(st['max_reg'], sum(1 for e in al if not e.summoned))
        st['max_all'] = max(st['max_all'], len(al))
        if i > 0 and i % 40 == 0 and al:
            p = w.player
            _kill(w, min(al, key=lambda e: (e.x - p.x) ** 2 + (e.y - p.y) ** 2))
        return None
    r = _director_run(h, 400, start_wave=9, setup=setup, on_frame=on_frame, name='cap', shots=(90,))
    sp = r.where('enemy_spawn')
    first = [d for f, n, d in r.events if n == 'enemy_spawn' and f == 0]
    assert len(first) == 10, 'first batch %d (want 10)' % len(first)
    assert sum(1 for d in first if d['kind'] == 'eradicator') == 3, 'eradicators not all in the first batch'
    assert len(sp) == 15, 'spawned %d of 15' % len(sp)
    assert st['max_reg'] <= 10 and st['max_all'] <= 12, 'alive %d regular / %d total' % (st['max_reg'], st['max_all'])
    later = [f for f, n, d in r.events if n == 'enemy_spawn' and f > 0]
    gaps = [b - a for a, b in zip(later, later[1:])]
    assert all(g >= int(1.5 * FPS) - 1 for g in gaps), 'refills closer than 1.5 s: %r' % gaps
    far = [st['at'][d['enemy'].id] for d in sp]
    assert min(far) >= 7.0 - 1e-6, 'a spawn %.2f cells from the player' % min(far)
    assert all(abs(d['enemy'].dmg_mult - 1.15) < 1e-9 for d in sp), 'stage-2 scaling missing'
    return 'batch 10 (E3 first), refills at frames %s, max alive %d/%d, nearest spawn %.1f' % (
        later, st['max_reg'], st['max_all'], min(far))


def check_elites_stage2(h):
    """Seed 1: at least one elite across waves 6-9 (stage 2), none in stage 1, the warden never elite."""
    st = {'by_wave': {}, 'on_point': False}

    def setup(w):
        def on_spawn(d):
            st['by_wave'].setdefault(w.director.wave, []).append((d['kind'], d['elite']))

        def on_wave(d):
            if d['kind'] == 'capture':
                h.place(w, POINT[0], POINT[1], w.player.angle)
                st['on_point'] = True
            elif st['on_point']:
                h.place(w, *HOME)
                st['on_point'] = False
        w.bus.on('enemy_spawn', on_spawn)
        w.bus.on('wave_start', on_wave)

    def on_frame(w, i, s):
        return 'stop' if w.director.wave >= 10 else None
    r = _director_run(h, 1200, start_wave=6, debug={'autokill': 2.0, 'auto_capture': True}, setup=setup,
                      on_frame=on_frame, name='elites', seed=1)
    assert r.world.director.wave >= 10, 'stopped at wave %d' % r.world.director.wave
    elites = [(wv, k) for wv in range(6, 10) for k, el in st['by_wave'].get(wv, []) if el]
    assert elites, 'no elite in waves 6-9 with seed 1: %r' % st['by_wave']
    assert not any(el for k, el in st['by_wave'].get(10, []) if k == 'warden'), 'elite warden'
    w = h.make_world()
    w.director.stage = 1
    stage1 = [w.director._spawn('trooper').elite for _ in range(40)]
    assert not any(stage1), 'elite in stage 1'
    return 'elites in waves 6-9: %s' % ', '.join('w%d %s' % t for t in elites)


def check_boss_wave(h):
    """Wave 5: boss_spawn once at the farthest reachable cell + T3 D2; director.boss; the wave waits for the
    escort after the boss dies; the boss kill scores 150 x stage."""
    st = {}

    from rwf.world import OPEN_CELLS, UNREACHABLE

    def on_frame(w, i, s):
        d = w.director
        if i == 1:
            b = d.boss
            best = max(w.flow.dist(c[0], c[1]) for c in OPEN_CELLS if w.flow.dist(c[0], c[1]) < UNREACHABLE)
            st['boss_d'] = w.flow.dist(b.x, b.y)
            st['best'] = best
        if i == 60:
            st['score0'] = w.score
            _kill(w, d.boss)
        if i == 62:
            st['state'] = d.state
            st['remaining'] = d.remaining
        return None
    r = _director_run(h, 90, start_wave=5, on_frame=on_frame, name='boss', shots=(30,))
    assert r.count('boss_spawn') == 1, 'boss_spawn x%d' % r.count('boss_spawn')
    d = r.world.director
    assert d.boss is not None and d.boss.KIND == 'warden' and d.boss.BOSS
    kinds = sorted(x['kind'] for x in r.where('enemy_spawn', summon=False))
    assert kinds == ['detonator'] * 2 + ['trooper'] * 3 + ['warden'], 'boss wave spawns %r' % kinds
    assert st['boss_d'] == st['best'], 'boss at flow dist %d, farthest %d' % (st['boss_d'], st['best'])
    ks = r.where('kill', target=d.boss)
    assert ks and ks[0]['boss'] and ks[0]['score'] == 150, 'boss kill %r' % [(x['boss'], x['score']) for x in ks]
    assert st['state'] == 'active' and st['remaining'] >= 1, 'wave %s / %d left after the boss died' % (
        st['state'], st['remaining'])
    return 'boss at flow dist %d; escort %s; wave still active with %d left after the boss kill' % (
        st['boss_d'], kinds, st['remaining'])


def check_victory_and_endless(h):
    """Stage 3 clear: stage_clear + victory once, world.victory; after the intermission stage 4 starts with the
    stage-3 row + 1 T + 1 S."""
    r = _director_run(h, 3 * FPS + 3 * FPS + 9 * FPS, start_wave=15, debug={'autokill': 1.0},
                      timeline=[('tap', 3 * FPS + 3 * FPS + 30, 'confirm')], name='victory')
    assert r.count('victory') == 1 and r.world.victory, 'victory x%d' % r.count('victory')
    assert r.first('stage_clear')['stage'] == 3
    from rwf import waves
    starts = r.where('wave_start')
    assert [d['wave'] for d in starts][:2] == [15, 16], 'waves %r' % [d['wave'] for d in starts]
    s16 = r.first('wave_start', wave=16)
    assert s16['stage'] == 4 and s16['kind'] == 'assault', s16
    plan = waves.wave_plan(4, 1)
    assert plan == ('assault', {'trooper': 7, 'slicer': 5, 'eradicator': 1}, 0), 'stage 4 W1 plan %r' % (plan,)
    f16 = r.frames_of('wave_start', wave=16)[0]
    w16 = [d['kind'] for f, n, d in r.events if n == 'enemy_spawn' and f == f16]
    assert len(w16) == 10 and 'eradicator' in w16, 'wave 16 first batch %r' % w16
    assert waves.wave_plan(5, 3) == ('capture', {'eradicator': 3}, 20)
    assert waves.wave_plan(5, 5) == ('boss', {'trooper': 7, 'detonator': 2, 'eradicator': 1}, 0)
    return 'victory once; stage 4 W1 plan %r; endless rows ok' % (plan[1],)


def check_director_debug_hooks(h):
    """no_director keeps the director idle; start_wave picks the wave; in_combat only while a wave is active."""
    r = h.run('vector', 30, debug={'no_director': True}, name='dir_idle')
    assert r.count('wave_start') == 0 and r.world.director.state == 'idle'
    st = {'combat': []}

    def on_frame(w, i, s):
        st['combat'].append((w.director.state, w.director.in_combat))
        return None
    r = _director_run(h, 150, start_wave=7, debug={'autokill': 0.5}, on_frame=on_frame, name='dir_hooks')
    s0 = r.first('wave_start')
    assert s0['wave'] == 7 and s0['stage'] == 2 and s0['wave_in_stage'] == 2 and s0['kind'] == 'assault', s0
    assert all(c == (s == 'active') for s, c in st['combat']), 'in_combat mismatch %r' % st['combat'][:5]
    assert 'cleared' in [s for s, c in st['combat']], 'autokill did not clear the wave'
    return 'start_wave 7 -> stage 2 W2; autokill cleared it'


# ============================ perf and pictures ================================
def check_enemy_perf(h):
    """10 real enemies with live AI in view (plus bolts and barriers): update/render/total p50/p95.
    Fails only above the 12 ms p95 line (section 8); the surface rule (<= 5 of 256x256+) applies."""
    samples = {'update': [], 'render': [], 'hud': [], 'total': []}
    st = {}
    mix = ('trooper', 'slicer', 'detonator', 'eradicator', 'trooper', 'slicer', 'trooper', 'eradicator',
           'trooper', 'slicer')

    def setup(w):
        h.place(w, *h.ROOMY)
        for k, kind in enumerate(mix):
            h.spawn(w, kind, 2.5 + 0.3 * k, (-1.0) ** k * 0.6)

    def on_frame(w, i, s):
        if i == 60:
            h.count_surfaces(True)
        if i >= 60:
            for k in samples:
                samples[k].append(w.perf.get(k, 0.0))
        if i == 359:
            st['big'] = h.big_surfaces
            h.count_surfaces(False)
            return 'stop'
        return None
    r = h.run('vector', 365, debug={'perf': True}, setup=setup, on_frame=on_frame, name='enemy_perf', shots=(70,))
    h.count_surfaces(False)

    def pct(v, q):
        s = sorted(v)
        return s[min(len(s) - 1, int(len(s) * q))]
    line = '; '.join('%s p50 %.2f p95 %.2f' % (k, pct(samples[k], 0.5), pct(samples[k], 0.95))
                     for k in ('update', 'render', 'hud', 'total'))
    h.log(line + ' ms')
    assert pct(samples['total'], 0.95) <= 12.0, 'p95 total above 12 ms: ' + line
    assert st.get('big', 0) <= 5, '%d surfaces >= 256x256' % st.get('big', 0)
    return 'update p95 %.2f, render p95 %.2f, total p95 %.2f ms' % (
        pct(samples['update'], 0.95), pct(samples['render'], 0.95), pct(samples['total'], 0.95))


def check_gallery(h):
    """Painter gallery (every kind x state, plain and elite) and in-world pictures; saved with --shots."""
    import pygame
    combat, config, core, enemies, render, theme, waves = _rwf()
    cols = max(len(v) for v in STATES.values())
    cell_w, cell_h = 170, 150
    surf = pygame.Surface((cell_w * cols, cell_h * len(STATES) * 2))
    surf.fill((24, 26, 34))
    row = 0
    for kind, states in STATES.items():
        fn, bw, bh = render.PAINTERS[kind]
        for elite in (False, True):
            for c, s in enumerate(states):
                img = render.paint_base(kind, s, elite)
                k = min((cell_h - 26) / bh, (cell_w - 10) / bw)
                im = pygame.transform.scale(img, (int(bw * k), int(bh * k)))
                x = c * cell_w + (cell_w - im.get_width()) // 2
                surf.blit(im, (x, row * cell_h + 4))
                surf.blit(core.text('%s %s%s' % (kind, s, ' E' if elite else ''), 'xs', (220, 220, 220)),
                          (c * cell_w + 4, row * cell_h + cell_h - 20))
            row += 1
    h.save(surf, 'enemies_gallery')
    lineup = ('trooper', 'slicer', 'detonator', 'eradicator', 'warden')

    def setup(w):
        h.place(w, *h.ROOMY)
        for k, kind in enumerate(lineup):
            h.spawn(w, kind, 3.2 + 0.2 * (k % 2), (k - 2) * 0.62)
    h.run('vector', 3, setup=setup, name='enemies_lineup', shots=(1,))
    return 'gallery %dx%d' % surf.get_size()
