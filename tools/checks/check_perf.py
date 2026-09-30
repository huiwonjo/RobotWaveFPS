"""Perf scenario (spec 8 / 9.2 item 12). Reports p50/p95 per system; fails above 12 ms p95 total."""
import math

WARMUP = 60
MEASURED = 300
WARN_MS = 9.0
FAIL_MS = 12.0


def _pct(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * q))]


def check_perf(h):
    from rwf import combat
    from rwf.config import TEAM_ENEMY, TEAM_PLAYER
    samples = {'update': [], 'render': [], 'hud': [], 'total': []}
    st = {}

    def feed_kills(w):
        for i in range(5):
            e = w.enemies[i % len(w.enemies)]
            w.bus.emit('kill', target=e, name=e.NAME, source=w.player, killer=w.player.NAME, ability='primary',
                       label=w.player.label_for('primary'), crit=bool(i % 2), score=10, boss=False, ult=False,
                       x=e.x, y=e.y)

    def top_up(w):
        n = sum(1 for p in w.projectiles if p.team == TEAM_ENEMY)
        k = 0
        while n < 30 and k < 40:
            y = 7.5 + ((n * 7) % 5 - 2) * 0.08
            p = combat.Projectile(17.0 - (n % 6) * 0.9, y, math.pi, 8.0, team=TEAM_ENEMY, damage=10,
                                  owner=None, ttl=3.0)
            if not w.add_projectile(p):
                break
            n += 1
            k += 1
        if len(w.particles) < 40:
            w.burst(6.0 + (w.frame % 5), 7.5, 0.5, 40 - len(w.particles), (255, 200, 80), 1.5, 0.8, 2)

    def setup(w):
        for i in range(10):
            h.spawn(w, 'dummy', 3.0 + i * 0.55, 0.2 if i % 2 else -0.2)
        for fwd in (9.0, 11.0):
            b = combat.Barrier(TEAM_ENEMY, 400, 1.0)
            b.set_pose(w.player.x + fwd, w.player.y, math.pi)
            w.add_barrier(b)
        top_up(w)
        feed_kills(w)

    def on_frame(w, i, state):
        top_up(w)
        if i % 90 == 0:
            feed_kills(w)
        if i == WARMUP:
            h.count_surfaces(True)
        if i >= WARMUP:
            for k in samples:
                samples[k].append(w.perf.get(k, 0.0))
        if i == WARMUP + MEASURED - 1:
            st['big'] = h.big_surfaces
            h.count_surfaces(False)
            return 'stop'
        return None

    r = h.run('vector', WARMUP + MEASURED + 5, debug={'perf': True}, setup=setup, on_frame=on_frame, name='perf',
              shots=(WARMUP + 10,))
    h.count_surfaces(False)
    assert len(samples['total']) >= MEASURED - 1, 'only %d measured frames' % len(samples['total'])
    parts = []
    for k in ('update', 'render', 'hud', 'total'):
        parts.append('%s p50 %.2f p95 %.2f' % (k, _pct(samples[k], 0.5), _pct(samples[k], 0.95)))
    line = '; '.join(parts) + ' ms'
    h.log(line)
    p95 = _pct(samples['total'], 0.95)
    assert p95 <= FAIL_MS, 'p95 total %.2f ms > %.1f ms (%s)' % (p95, FAIL_MS, line)
    if p95 > WARN_MS:
        h.log('WARN: p95 total %.2f ms above the %.1f ms target' % (p95, WARN_MS))
    assert st.get('big', 0) <= 5, '%d surfaces >= 256x256 allocated in 300 frames' % st.get('big', 0)
    vis = sum(1 for b in r.world.projection.values() if b.visible)
    assert vis >= 5, 'only %d dummies visible in the perf view' % vis
    return 'total p50 %.2f p95 %.2f ms, big surfaces %d, visible %d' % (
        _pct(samples['total'], 0.5), p95, st.get('big', 0), vis)


def check_perf_close(h):
    """Melee-range case: 6 dummies weaving 0.6-1.6 cells in front of the player. Their sprites are
    taller than the screen and change size every frame, so every frame re-scales them (the scaled-sprite
    cache can't help): the worst case for render. Same thresholds as check_perf."""
    samples = {'update': [], 'render': [], 'hud': [], 'total': []}
    st = {'tall': 0}
    lat = (-0.45, 0.45, -0.15, 0.15, 0.0, 0.3)

    def setup(w):
        h.place(w, *h.ROOMY)
        for k in range(6):
            h.spawn(w, 'dummy', 1.0 + 0.1 * k, lat[k])

    def on_frame(w, i, state):
        p = w.player
        ca, sa = math.cos(p.angle), math.sin(p.angle)
        for k, e in enumerate(w.enemies):
            d = 0.9 + 0.1 * k + 0.35 * math.sin(i * 0.23 + k * 1.3)
            s = lat[k]
            e.x = p.x + ca * d - sa * s
            e.y = p.y + sa * d + ca * s
        if i >= WARMUP:
            for k in samples:
                samples[k].append(w.perf.get(k, 0.0))
            st['tall'] = max(st['tall'], sum(1 for b in w.projection.values() if b.visible and b.y1 - b.y0 > 768))
        if i == WARMUP + MEASURED - 1:
            return 'stop'
        return None

    h.run('vector', WARMUP + MEASURED + 5, debug={'perf': True}, setup=setup, on_frame=on_frame, name='perf_close',
          shots=(WARMUP + 10,))
    assert len(samples['total']) >= MEASURED - 1, 'only %d measured frames' % len(samples['total'])
    line = '; '.join('%s p50 %.2f p95 %.2f' % (k, _pct(samples[k], 0.5), _pct(samples[k], 0.95))
                     for k in ('update', 'render', 'hud', 'total')) + ' ms'
    h.log(line)
    p95 = _pct(samples['total'], 0.95)
    assert p95 <= FAIL_MS, 'close range: p95 total %.2f ms > %.1f ms (%s)' % (p95, FAIL_MS, line)
    if p95 > WARN_MS:
        h.log('WARN: close range p95 total %.2f ms above the %.1f ms target' % (p95, WARN_MS))
    assert st['tall'] >= 2, 'close-range scenario lost its taller-than-screen sprites (%d)' % st['tall']
    return 'total p50 %.2f p95 %.2f ms, up to %d taller-than-screen sprites' % (
        _pct(samples['total'], 0.5), p95, st['tall'])
