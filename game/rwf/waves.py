"""WaveDirector, the wave table, the Objective, spawning (ENEMIES owns this file).

Phase 0 STUB by FOUNDATION: the full state machine, events, debug keys and the
real 4.6 table. Capture waves run as E-at-start + trickle WITHOUT the objective
(objective stays None); boss waves spawn the warden plus the escort.
"""
from . import config as C
from . import core
from . import theme
from .world import OPEN_CELLS, UNREACHABLE, open_cells_far

TUNING = {
    'refill_every': 1.5, 'trickle_every': 2.5, 'trickle_alive_cap': 8,
    'trickle_mix': (('trooper', 0.45), ('slicer', 0.35), ('detonator', 0.20)),
    'elite_per_stage': 0.15, 'elite_max': 0.45, 'capture_time': 90.0,
}

WAVE_KINDS = ('assault', 'assault', 'capture', 'assault', 'boss')
_ROWS = {
    1: ('T4 S2', 'T4 S3 D2', ('E1', 12), 'T4 S3 D2 E2', 'T3 D2'),
    2: ('T5 S3 E1', 'T5 S4 D2 E1', ('E2', 14), 'T5 S4 D3 E3', 'T4 D2 E1'),
    3: ('T6 S4 E1', 'T6 S5 D2 E1', ('E3', 16), 'T6 S5 D3 E3', 'T5 D2 E1'),
}
_LETTER = {'T': 'trooper', 'S': 'slicer', 'D': 'detonator', 'E': 'eradicator'}


def _parse(s):
    out = {}
    for tok in s.split():
        k = _LETTER[tok[0]]
        out[k] = out.get(k, 0) + int(tok[1:])
    return out


def wave_plan(stage, wave_in_stage):
    """(kind, {enemy kind: count}, trickle count) for stage >= 1 and wave_in_stage 1..5 (spec 4.6).

    Boss waves list only the escort; the warden itself is added by the director.
    """
    kind = WAVE_KINDS[wave_in_stage - 1]
    entry = _ROWS[min(stage, 3)][wave_in_stage - 1]
    extra = max(0, stage - 3)
    if kind == 'capture':
        counts = _parse(entry[0])
        trickle = entry[1] + 2 * extra
    else:
        counts = _parse(entry)
        trickle = 0
        if extra:
            counts['trooper'] = counts.get('trooper', 0) + extra
            if kind == 'assault':
                counts['slicer'] = counts.get('slicer', 0) + extra
    return kind, counts, trickle


class Objective:
    x = 10.0
    y = 10.0
    radius = 1.8

    def __init__(self):
        self.progress = 0.0
        self.state = 'neutral'
        self.time_left = TUNING['capture_time']
        self.player_inside = False
        self.contested = False


class WaveDirector:
    def __init__(self, world):
        self.world = world
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
        self.queue = []
        self.trickle_left = 0
        self._refill_left = 0.0
        self._trickle_left_t = 0.0
        self._clear_left = 0.0
        self._wave_t0 = 0.0
        self._autokilled = False

    # --- control -------------------------------------------------------------------
    def start(self):
        w = self.world
        if w.debug.get('no_director') or self.state != 'idle':
            return
        self._begin(max(1, int(w.debug.get('start_wave') or 1)))

    def skip_intermission(self):
        if self.state == 'intermission':
            self.intermission_left = 0.0

    def debug_kill_all(self, world):
        for e in world.enemies:
            if e.alive:
                e.remove_silently(world, 4)
        self.queue = []
        self.trickle_left = 0

    # --- waves -----------------------------------------------------------------------
    def _begin(self, n):
        w = self.world
        self.wave = n
        self.stage = (n - 1) // C.WAVES_PER_STAGE + 1
        self.wave_in_stage = (n - 1) % C.WAVES_PER_STAGE + 1
        kind, counts, trickle = wave_plan(self.stage, self.wave_in_stage)
        self.kind = kind
        self.label = {'assault': 'ASSAULT', 'capture': theme.WORDS['capture'], 'boss': 'BOSS'}[kind]
        q = []
        for k in sorted(counts):
            q += [k] * counts[k]
        w.rng.shuffle(q)
        self.queue = [k for k in q if k == 'eradicator'] + [k for k in q if k != 'eradicator']
        self.trickle_left = trickle
        self.state = 'active'
        self.in_combat = True
        self.boss = None
        self._wave_t0 = w.now
        self._autokilled = False
        self._refill_left = TUNING['refill_every']
        self._trickle_left_t = TUNING['trickle_every']
        w.bus.emit('wave_start', stage=self.stage, wave=n, wave_in_stage=self.wave_in_stage, kind=kind,
                   label=self.label)
        if kind == 'boss':
            self._spawn_boss()
        while self.queue and self._alive_regular() < C.CAP_ALIVE:
            self._spawn(self.queue.pop(0))

    def _alive_regular(self):
        return sum(1 for e in self.world.enemies if e.alive and not e.summoned)

    def _spawn_pos(self):
        w = self.world
        p = w.player
        flow = w.flow
        taken = [(e.x, e.y) for e in w.enemies if e.alive]
        for md in C.SPAWN_MIN_DIST:
            cands = [c for c in open_cells_far(p.x, p.y, md)
                     if flow.dist(c[0], c[1]) < UNREACHABLE
                     and all((c[0] - x) ** 2 + (c[1] - y) ** 2 >= 0.36 for x, y in taken)]
            if cands:
                return w.rng.choice(cands)
        return w.rng.choice(OPEN_CELLS)

    def _spawn(self, kind):
        w = self.world
        k = self.stage - 1
        chance = min(TUNING['elite_per_stage'] * k, TUNING['elite_max'])
        elite = chance > 0 and w.rng.random() < chance
        x, y = self._spawn_pos()
        return w.spawn_enemy(kind, x, y, elite=elite)

    def _spawn_boss(self):
        w = self.world
        flow = w.flow
        best = None
        best_d = -1
        for c in OPEN_CELLS:
            d = flow.dist(c[0], c[1])
            if d < UNREACHABLE and d > best_d:
                best_d = d
                best = c
        if best is None:
            best = self._spawn_pos()
        self.boss = w.spawn_enemy('warden', best[0], best[1])
        w.bus.emit('boss_spawn', enemy=self.boss)

    def _trickle_kind(self):
        r = self.world.rng.random()
        acc = 0.0
        for k, p in TUNING['trickle_mix']:
            acc += p
            if r < acc:
                return k
        return TUNING['trickle_mix'][-1][0]

    # --- per frame -------------------------------------------------------------------
    def update(self, world, dt):
        st = self.state
        if st == 'active':
            now = world.now
            ak = world.debug.get('autokill')
            if ak is not None and not self._autokilled and now - self._wave_t0 >= ak:
                self._autokilled = True
                self.debug_kill_all(world)
            if self.queue:
                self._refill_left -= dt
                if self._refill_left <= 0.0:
                    self._refill_left = TUNING['refill_every']
                    if self._alive_regular() < C.CAP_ALIVE:
                        self._spawn(self.queue.pop(0))
            if self.trickle_left > 0:
                self._trickle_left_t -= dt
                if self._trickle_left_t <= 0.0:
                    self._trickle_left_t = TUNING['trickle_every']
                    if self._alive_regular() < TUNING['trickle_alive_cap']:
                        self._spawn(self._trickle_kind())
                        self.trickle_left -= 1
            alive = sum(1 for e in world.enemies if e.alive)
            self.remaining = alive + len(self.queue) + self.trickle_left
            if self.remaining == 0:
                self.state = 'cleared'
                self.in_combat = False
                self._clear_left = C.WAVE_CLEAR_DELAY
                world.bus.emit('wave_clear', stage=self.stage, wave=self.wave)
        elif st == 'cleared':
            self._clear_left -= dt
            if self._clear_left <= 0.0:
                if self.wave_in_stage >= C.WAVES_PER_STAGE:
                    world.bus.emit('stage_clear', stage=self.stage)
                    if self.stage == C.VICTORY_STAGE and not world.victory:
                        world.victory = True
                        world.bus.emit('victory', stage=self.stage)
                    self.state = 'intermission'
                    self.intermission_left = C.INTERMISSION
                else:
                    self._begin(self.wave + 1)
        elif st == 'intermission':
            self.intermission_left -= dt
            if self.intermission_left <= 0.0:
                self.intermission_left = 0.0
                world.bus.emit('intermission_end', stage=self.stage)
                self._begin(self.wave + 1)

    def emit_visuals(self, scene):
        pass
