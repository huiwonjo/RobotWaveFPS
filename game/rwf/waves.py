"""WaveDirector, the wave table, the capture Objective and spawning (spec 4.6, 4.7, 7.8). ENEMIES owns this file.

Flow: start() (after COUNTDOWN; honours debug 'no_director' and 'start_wave') -> wave 'active' -> 'cleared'
(3 s) -> next wave; after wave 5 of a stage: 'stage_clear' (+ 'victory' once after stage 3) and an 8 s
'intermission' -> 'intermission_end' -> the next stage's wave 1. Endless after stage 3.

Spawning (4.6): at wave start up to CAP_ALIVE regular enemies (Eradicators first, the rest shuffled with
world.rng), then one every 1.5 s while fewer than 10 are alive. Capture waves add a trickle (45% T / 35% S
/ 20% D, one every 2.5 s while fewer than 8 are alive). Spawn cells are open, reachable cells >= 7 from
the player (fallback 5, then 3). The boss spawns at the reachable open cell farthest along the flow field.
Warden summons (summon=True) never count toward the cap. Elite chance min(0.15k, 0.45), non-boss only.

Capture (4.7): wave 3 of every stage has an Objective at (10, 10), r 1.8. It fills 1/12 per second (x10
with debug 'auto_capture') while the player is inside and no alive enemy is; it never decays. 90 s limit,
then OVERTIME while the player stays inside (leaving for > 0.5 s fails it); outside at 0 s fails it.
A capture wave clears only once the objective is captured (every enemy self-destructs, no score; reward
+100 x stage score and +20% of ULT_COST ult charge, past the ult-active lock) or failed (the trickle stops;
the rest must be killed). 'objective' is emitted on every state change and once a second while capturing.
"""
from . import config as C
from . import theme
from .world import OPEN_CELLS, UNREACHABLE, open_cells_far

TUNING = {
    'refill_every': 1.5, 'trickle_every': 2.5, 'trickle_alive_cap': 8,
    'trickle_mix': (('trooper', 0.45), ('slicer', 0.35), ('detonator', 0.20)),
    'elite_per_stage': 0.15, 'elite_max': 0.45,
    'point': (10.0, 10.0), 'point_radius': 1.8, 'capture_rate': 1.0 / 12.0, 'auto_capture_mult': 10.0,
    'capture_time': 90.0, 'overtime_grace': 0.5, 'capture_score': 100, 'capture_ult': 0.20,
    'objective_tick': 1.0, 'self_destruct_particles': 8,
}

WAVE_KINDS = ('assault', 'assault', 'capture', 'assault', 'boss')
_ROWS = {
    1: ('T4 S2', 'T4 S3 D2', ('E1', 12), 'T4 S3 D2 E2', 'T3 D2'),
    2: ('T5 S3 E1', 'T5 S4 D2 E1', ('E2', 14), 'T5 S4 D3 E3', 'T4 D2 E1'),
    3: ('T6 S4 E1', 'T6 S5 D2 E1', ('E3', 16), 'T6 S5 D3 E3', 'T5 D2 E1'),
}
_LETTER = {'T': 'trooper', 'S': 'slicer', 'D': 'detonator', 'E': 'eradicator'}
# floor ring colour per objective state (4.7); captured / failed draw nothing
OBJ_COLORS = {'neutral': (235, 241, 237), 'capturing': (80, 170, 255), 'contested': (255, 150, 40),
              'overtime': (255, 70, 60)}


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
    """The capture point of a CAPTURE wave (4.7). The HUD reads it; the director updates it.

    state: 'neutral' | 'capturing' | 'contested' | 'overtime' | 'captured' | 'failed'.
    During overtime the state stays 'overtime' and `contested` tells whether progress is blocked.
    """
    x = 10.0
    y = 10.0
    radius = 1.8

    def __init__(self):
        self.x, self.y = TUNING['point']
        self.radius = TUNING['point_radius']
        self.progress = 0.0
        self.state = 'neutral'
        self.time_left = TUNING['capture_time']
        self.player_inside = False
        self.contested = False
        self.enemies_inside = 0
        self._out_t = 0.0

    @property
    def done(self):
        return self.state in ('captured', 'failed')

    @property
    def color(self):
        return OBJ_COLORS.get(self.state, OBJ_COLORS['neutral'])

    def update(self, world, dt):
        """Advance progress / timer; returns the new state (== self.state when unchanged)."""
        if self.done:
            return self.state
        p = world.player
        ox, oy = self.x, self.y
        r2 = self.radius * self.radius
        inside = p.alive and (p.x - ox) ** 2 + (p.y - oy) ** 2 <= r2
        n_in = 0
        for e in world.enemies:
            if e.alive and (e.x - ox) ** 2 + (e.y - oy) ** 2 <= r2:
                n_in += 1
        self.player_inside = inside
        self.enemies_inside = n_in
        self.contested = inside and n_in > 0
        if inside and not n_in:
            rate = TUNING['capture_rate']
            if world.debug.get('auto_capture'):
                rate *= TUNING['auto_capture_mult']
            self.progress = min(1.0, self.progress + rate * dt)
        if self.progress >= 1.0 - 1e-9:
            self.progress = 1.0
            return 'captured'
        if self.state == 'overtime':
            self._out_t = 0.0 if inside else self._out_t + dt
            return 'failed' if self._out_t > TUNING['overtime_grace'] else 'overtime'
        self.time_left = max(0.0, self.time_left - dt)
        if self.time_left <= 0.0:
            return 'overtime' if inside else 'failed'
        if not inside:
            return 'neutral'
        return 'contested' if n_in else 'capturing'


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
        self._obj_tick = 0.0

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
        """Kills every alive enemy and empties the queue and the trickle; no score, no kill events."""
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
        self.objective = Objective() if kind == 'capture' else None
        self._wave_t0 = w.now
        self._autokilled = False
        self._refill_left = TUNING['refill_every']
        self._trickle_left_t = TUNING['trickle_every']
        self._obj_tick = TUNING['objective_tick']
        w.bus.emit('wave_start', stage=self.stage, wave=n, wave_in_stage=self.wave_in_stage, kind=kind,
                   label=self.label)
        if kind == 'boss':
            self._spawn_boss()
        while self.queue and self._alive_regular() < C.CAP_ALIVE:
            self._spawn(self.queue.pop(0))
        ob = self.objective
        if ob is not None:
            ob.state = ob.update(w, 0.0)
            self._emit_objective(w)
        self.remaining = self._count_remaining(w)

    def _alive_regular(self):
        return sum(1 for e in self.world.enemies if e.alive and not e.summoned)

    def _count_remaining(self, world):
        return sum(1 for e in world.enemies if e.alive) + len(self.queue) + self.trickle_left

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

    # --- objective -------------------------------------------------------------------
    def _emit_objective(self, world):
        ob = self.objective
        world.bus.emit('objective', state=ob.state, progress=ob.progress, time_left=ob.time_left)

    def _update_objective(self, world, dt):
        ob = self.objective
        if ob.done:
            return
        old = ob.state
        new = ob.update(world, dt)
        if new != old:
            ob.state = new
            self._obj_tick = TUNING['objective_tick']
            if ob.done:                             # objective time (stats) stops counting once resolved
                ob.player_inside = False
                ob.contested = False
            if new == 'captured':
                self._captured(world)
            elif new == 'failed':
                self.trickle_left = 0               # 4.7: the trickle stops; the rest must be killed
            self._emit_objective(world)
        elif new in ('capturing', 'overtime') and ob.player_inside and not ob.contested:
            self._obj_tick -= dt
            if self._obj_tick <= 0.0:               # the capture tick (sfx) once a second while progressing
                self._obj_tick += TUNING['objective_tick']
                self._emit_objective(world)

    def _captured(self, world):
        n = TUNING['self_destruct_particles']
        for e in world.enemies:
            if e.alive:
                e.remove_silently(world, n)
        self.queue = []
        self.trickle_left = 0
        world.score += TUNING['capture_score'] * self.stage
        p = world.player
        if p is not None and p.alive:
            p.add_ult(TUNING['capture_ult'] * p.ULT_COST, ignore_lock=True)
        world.bus.emit('sfx', name='capture', vol=1.0)

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
            ob = self.objective
            if ob is not None:
                self._update_objective(world, dt)
            self.remaining = self._count_remaining(world)
            if self.remaining == 0 and (ob is None or ob.done):
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
        """Capture point floor ring (width 3, colour by state) plus an inner progress ring."""
        ob = self.objective
        if ob is None or ob.done or self.state != 'active':
            return
        scene.ring(ob.x, ob.y, ob.radius, ob.color, 3, 28)
        if ob.progress > 0.02:
            scene.ring(ob.x, ob.y, max(0.15, ob.radius * ob.progress), OBJ_COLORS['capturing'], 2, 20)
