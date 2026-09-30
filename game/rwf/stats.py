"""MatchStats, medals and rank (HUD_UX owns this file). Phase 0 STUB by FOUNDATION.

All numbers come from bus events only (spec 5.10). The stub counts elims,
damage, shots, hits and the rest of the fields; medals follow the 6.2 table.
"""
from . import config as C

MEDALS = (  # (medal, stat key, gold, silver, bronze, min sample key, min sample)
    ('ELIMINATIONS', 'elims_pm', 10, 6, 3, None, 0),
    ('DAMAGE', 'damage_pm', 1500, 900, 500, None, 0),
    ('CRIT ACCURACY', 'crit_pct', 30, 20, 12, 'hits', 30),
    ('WEAPON ACCURACY', 'acc_pct', 55, 40, 25, 'shots', 50),
    ('OBJECTIVE TIME', 'obj_time', 30, 20, 10, None, 0),
    ('SUPPORT', 'support_pm', 600, 300, 120, None, 0),
)


class MatchStats:
    def __init__(self, world):
        self.world = world
        self.elims = 0
        self.damage = 0.0
        self.barrier_damage = 0.0
        self.crit_hits = 0
        self.hits = 0
        self.shots = 0
        self.healing = 0.0
        self.blocked = 0.0
        self.obj_time = 0.0
        self.ult_elims = 0
        self.time_played = 0.0
        self.waves_cleared = 0
        self.stage_reached = 1
        self.deaths = 0
        b = world.bus
        b.on('damage', self._on_damage)
        b.on('kill', self._on_kill)
        b.on('shot', self._on_shot)
        b.on('heal', self._on_heal)
        b.on('barrier_damage', self._on_barrier)
        b.on('wave_clear', self._on_wave_clear)
        b.on('wave_start', self._on_wave_start)
        b.on('player_death', self._on_death)

    def _is_player(self, ent):
        return ent is not None and ent is self.world.player

    def _on_damage(self, d):
        if self._is_player(d['source']) and not d['to_player']:
            self.damage += d['amount']

    def _on_kill(self, d):
        if self._is_player(d['source']) and d['target'] is not self.world.player:
            self.elims += 1
            if d['ult']:
                self.ult_elims += 1

    def _on_shot(self, d):
        self.shots += 1
        if d['hit']:
            self.hits += 1
            if d['crit']:
                self.crit_hits += 1

    def _on_heal(self, d):
        if self._is_player(d['source']) and d['ability'] != 'pack':
            self.healing += d['amount']

    def _on_barrier(self, d):
        b = d['barrier']
        if b.owner is self.world.player:
            self.blocked += d['amount']
        elif self._is_player(d['source']):
            self.barrier_damage += d['amount']

    def _on_wave_clear(self, d):
        self.waves_cleared += 1

    def _on_wave_start(self, d):
        self.stage_reached = max(self.stage_reached, d['stage'])

    def _on_death(self, d):
        self.deaths += 1

    def update(self, world, dt):
        self.time_played += dt
        ob = world.director.objective
        if ob is not None and getattr(ob, 'player_inside', False):
            self.obj_time += dt

    def _values(self):
        mins = max(1.0, self.time_played / 60.0)
        return {
            'elims_pm': self.elims / mins, 'damage_pm': self.damage / mins,
            'crit_pct': 100.0 * self.crit_hits / self.hits if self.hits else 0.0,
            'acc_pct': 100.0 * self.hits / self.shots if self.shots else 0.0,
            'obj_time': self.obj_time, 'support_pm': (self.healing + self.blocked) / mins,
            'hits': self.hits, 'shots': self.shots,
        }

    def medals(self):
        v = self._values()
        out = []
        for name, key, g, s, b, sample_key, sample in MEDALS:
            if sample_key is not None and v[sample_key] < sample:
                continue
            x = v[key]
            tier = 'gold' if x >= g else 'silver' if x >= s else 'bronze' if x >= b else None
            if tier:
                out.append((name, tier, '%d' % round(x)))
        return out[:6]

    def rank(self, score):
        for letter, thr, col in C.RANKS:
            if score >= thr:
                return letter, col
        return C.RANKS[-1][0], C.RANKS[-1][2]
