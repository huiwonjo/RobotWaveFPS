"""Play of the Game recorder (spec 6.2, decision 24). HUD_UX owns this file.

record(world, scene) is called by app every frame after render_frame; it keeps Scene REFERENCES (never
copies) at 20 Hz of sim time in an 8 s ring (160). Replaying a Scene costs one normal render and needs no
re-simulation (render.draw_scene). Scenes are immutable once built, so sharing the references is safe.

Scoring comes from 'kill' events credited to the player, over a rolling 8 s window: 100 per kill,
+50 for each kill within 3 s of the previous one, +150 ult kill, +200 boss kill, +25 crit kill.
When the window score beats the best so far, the clip is captured 1.0 s later (pending_until): the last
6 s of the ring (120 scene refs) plus meta. best() also captures a pending clip early (match ended).
"""
from collections import deque

# ============================ tuning ==========================================
TUNING = {
    'rate': 20.0,           # Hz of sim time
    'ring': 160,            # 8 s
    'window': 8.0,          # rolling scoring window (s)
    'clip': 6.0,            # seconds kept for the highlight
    'clip_frames': 120,
    'pending': 1.0,         # capture this long after the best score was reached
    'kill': 100, 'multi': 50, 'multi_gap': 3.0, 'ult': 150, 'boss': 200, 'crit': 25,
}
RATE = TUNING['rate']
RING = TUNING['ring']

_latest = {'obj': None}


def recorder_for(world):
    """The PotgRecorder of `world` (the most recent match only), or None."""
    r = _latest['obj']
    return r if r is not None and r.world is world else None


def score_kills(kills, now):
    """Window score for kills [(t, ult, boss, crit)] (sorted by t) within TUNING['window'] of now."""
    lo = now - TUNING['window']
    score = 0
    prev = None
    for t, ult, boss, crit in kills:
        if t < lo - 1e-9 or t > now + 1e-9:
            continue
        score += TUNING['kill']
        if prev is not None and t - prev <= TUNING['multi_gap'] + 1e-9:
            score += TUNING['multi']
        if ult:
            score += TUNING['ult']
        if boss:
            score += TUNING['boss']
        if crit:
            score += TUNING['crit']
        prev = t
    return score


class PotgRecorder:
    def __init__(self, world):
        self.world = world
        self.ring = deque(maxlen=RING)
        self._step = 1.0 / RATE
        self._next = 0.0
        self.kills = deque()            # (t, ult, boss, crit), player-credited, pruned to the window
        self.best_score = 0
        self.pending_until = None
        self._best = None
        world.bus.on('kill', self._on_kill)
        _latest['obj'] = self

    # --- bus ------------------------------------------------------------------------
    def _on_kill(self, d):
        w = self.world
        if d['target'] is w.player or d['source'] is not w.player:
            return
        t = float(d.get('t', w.now))
        ks = self.kills
        ks.append((t, bool(d.get('ult')), bool(d.get('boss')), bool(d.get('crit'))))
        lo = t - TUNING['window']
        while ks and ks[0][0] < lo:
            ks.popleft()
        s = score_kills(ks, t)
        if s > self.best_score:
            self.best_score = s
            self.pending_until = t + TUNING['pending']

    # --- per frame ----------------------------------------------------------------------
    def record(self, world, scene):
        now = world.now
        if now + 1e-9 >= self._next:
            self._next += self._step
            if self._next < now:                # slow frames: don't try to catch up
                self._next = now + self._step
            self.ring.append(scene)
        if self.pending_until is not None and now + 1e-9 >= self.pending_until:
            self._capture(now)

    def _capture(self, now):
        self.pending_until = None
        lo = now - TUNING['clip'] - 1e-6
        frames = [s for s in self.ring if s.now >= lo][-TUNING['clip_frames']:]
        if not frames:
            return
        t0 = frames[0].now
        t1 = frames[-1].now
        ks = [k for k in self.kills if t0 - self._step <= k[0] <= t1 + 1e-6]
        kill_frames = []
        for k in ks:
            idx = len(frames) - 1
            for i, s in enumerate(frames):
                if s.now >= k[0] - 1e-6:
                    idx = i
                    break
            kill_frames.append(idx)
        p = self.world.player
        self._best = {'frames': frames, 'hero': p.KEY, 'name': p.NAME, 'kills': len(ks),
                      'span': (ks[-1][0] - ks[0][0]) if ks else 0.0, 'kill_frames': kill_frames,
                      'score': self.best_score, 'ult': any(k[1] for k in ks)}

    def best(self):
        """{'frames': [Scene], 'hero': key, 'kills': n, 'span': s, 'kill_frames': [i], ...} or None."""
        if self.pending_until is not None:
            self._capture(self.world.now)
        return self._best
