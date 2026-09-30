"""MatchStats, medals and rank (spec 6.2, 5.10). HUD_UX owns this file.

Every counter comes from bus events (7.5); update() only accumulates time (time_played, and objective
time while the player stands on an active capture point). No other module keeps kill counters.
The screens read the formatted rows from rows() so the pause and summary panels stay consistent.
"""
from . import config as C

# ============================ tuning (spec 6.2 medal table) ==================
# (medal, value key, gold, silver, bronze, minimum-sample key, minimum sample)
MEDALS = (
    ('ELIMINATIONS', 'elims_pm', 10, 6, 3, None, 0),
    ('DAMAGE', 'damage_pm', 1500, 900, 500, None, 0),
    ('CRIT ACCURACY', 'crit_pct', 30, 20, 12, 'hits', 30),
    ('WEAPON ACCURACY', 'acc_pct', 55, 40, 25, 'shots', 50),
    ('OBJECTIVE TIME', 'obj_time', 30, 20, 10, None, 0),
    ('SUPPORT', 'support_pm', 600, 300, 120, None, 0),
)
MAX_MEDALS = 6
TIER_COLORS = {'gold': (236, 193, 119), 'silver': (190, 200, 210), 'bronze': (190, 120, 70)}
_VALUE_FMT = {'elims_pm': '%.1f / MIN', 'damage_pm': '%d / MIN', 'crit_pct': '%d%%', 'acc_pct': '%d%%',
              'obj_time': '%ds', 'support_pm': '%d / MIN'}
OBJ_ACTIVE_STATES = ('neutral', 'capturing', 'contested', 'overtime')

_latest = {'obj': None}


def stats_for(world):
    """The MatchStats of `world` (the most recent match only), or None. Screens without a stats
    argument (the intermission panel) use it."""
    s = _latest['obj']
    return s if s is not None and s.world is world else None


def fmt_time(sec):
    sec = int(max(0.0, sec))
    return '%d:%02d' % (sec // 60, sec % 60)


class MatchStats:
    def __init__(self, world):
        self.world = world
        self.elims = 0
        self.damage = 0.0               # dealt to enemies (all pools, no overkill)
        self.barrier_damage = 0.0       # dealt to enemy barriers
        self.crit_hits = 0
        self.hits = 0
        self.shots = 0
        self.healing = 0.0              # own abilities only (packs excluded)
        self.blocked = 0.0              # absorbed by the player's barrier
        self.obj_time = 0.0
        self.ult_elims = 0
        self.time_played = 0.0
        self.waves_cleared = 0
        self.stage_reached = 1
        self.deaths = 0
        self.crit_elims = 0
        self.boss_elims = 0
        self.ults_used = 0
        b = world.bus
        b.on('damage', self._on_damage)
        b.on('kill', self._on_kill)
        b.on('shot', self._on_shot)
        b.on('heal', self._on_heal)
        b.on('barrier_damage', self._on_barrier)
        b.on('wave_clear', self._on_wave_clear)
        b.on('wave_start', self._on_wave_start)
        b.on('player_death', self._on_death)
        b.on('ult_used', self._on_ult_used)
        _latest['obj'] = self

    # --- bus ------------------------------------------------------------------------
    def _is_player(self, ent):
        return ent is not None and ent is self.world.player

    def _on_damage(self, d):
        if self._is_player(d['source']) and not d['to_player']:
            self.damage += d['amount']

    def _on_kill(self, d):
        if self._is_player(d['source']) and d['target'] is not self.world.player:
            self.elims += 1
            if d.get('ult'):
                self.ult_elims += 1
            if d.get('crit'):
                self.crit_elims += 1
            if d.get('boss'):
                self.boss_elims += 1

    def _on_shot(self, d):
        self.shots += 1
        if d['hit']:
            self.hits += 1
            if d['crit']:
                self.crit_hits += 1

    def _on_heal(self, d):
        if self._is_player(d['source']) and d.get('ability') != 'pack':
            self.healing += d['amount']

    def _on_barrier(self, d):
        b = d['barrier']
        if getattr(b, 'owner', None) is self.world.player:
            self.blocked += d['amount']
        elif self._is_player(d.get('source')):
            self.barrier_damage += d['amount']

    def _on_wave_clear(self, d):
        self.waves_cleared += 1

    def _on_wave_start(self, d):
        self.stage_reached = max(self.stage_reached, int(d.get('stage', 1)))

    def _on_death(self, d):
        self.deaths += 1

    def _on_ult_used(self, d):
        self.ults_used += 1

    # --- per frame ----------------------------------------------------------------------
    def update(self, world, dt):
        self.time_played += dt
        d = world.director
        ob = getattr(d, 'objective', None)
        if (ob is not None and getattr(ob, 'player_inside', False) and getattr(d, 'state', '') == 'active'
                and getattr(ob, 'state', 'neutral') in OBJ_ACTIVE_STATES):
            self.obj_time += dt

    # --- derived values ---------------------------------------------------------------------
    @property
    def total_damage(self):
        return self.damage + self.barrier_damage

    @property
    def accuracy(self):
        return 100.0 * self.hits / self.shots if self.shots else 0.0

    @property
    def crit_accuracy(self):
        return 100.0 * self.crit_hits / self.hits if self.hits else 0.0

    def _values(self):
        mins = max(1.0, self.time_played / 60.0)
        return {
            'elims_pm': self.elims / mins, 'damage_pm': self.total_damage / mins,
            'crit_pct': self.crit_accuracy, 'acc_pct': self.accuracy,
            'obj_time': self.obj_time, 'support_pm': (self.healing + self.blocked) / mins,
            'hits': self.hits, 'shots': self.shots,
        }

    def medals(self):
        """[(medal, tier, value text)] in table order, at most 6 (spec 6.2)."""
        v = self._values()
        out = []
        for name, key, g, s, b, sample_key, sample in MEDALS:
            if sample_key is not None and v[sample_key] < sample:
                continue
            x = v[key]
            tier = 'gold' if x >= g else 'silver' if x >= s else 'bronze' if x >= b else None
            if tier:
                out.append((name, tier, _VALUE_FMT[key] % x))
        return out[:MAX_MEDALS]

    def rank(self, score):
        """('A', colour) from the score thresholds in config.RANKS (S 5000, A 2000, B 800, C 300, D)."""
        for letter, thr, col in C.RANKS:
            if score >= thr:
                return letter, col
        return C.RANKS[-1][0], C.RANKS[-1][2]

    def rows(self):
        """[(label, value text)] for the summary's left column (spec 6.2, in order)."""
        acc = '%d%%' % round(self.accuracy) if self.shots else '-'
        cacc = '%d%%' % round(self.crit_accuracy) if self.hits else '-'
        return [('ELIMINATIONS', '%d' % self.elims),
                ('DAMAGE DONE', '%d' % round(self.total_damage)),
                ('CRIT ACCURACY', cacc),
                ('WEAPON ACCURACY', acc),
                ('HEALING', '%d' % round(self.healing)),
                ('DAMAGE BLOCKED', '%d' % round(self.blocked)),
                ('OBJECTIVE TIME', fmt_time(self.obj_time)),
                ('ULT KILLS', '%d' % self.ult_elims),
                ('TIME PLAYED', fmt_time(self.time_played)),
                ('WAVES CLEARED', '%d' % self.waves_cleared)]

    def live_rows(self):
        """[(label, value text)] for the pause panel: ELIMS, DAMAGE, ACCURACY, TIME (spec 6.2)."""
        acc = '%d%%' % round(self.accuracy) if self.shots else '-'
        return [('ELIMS', '%d' % self.elims), ('DAMAGE', '%d' % round(self.total_damage)),
                ('ACCURACY', acc), ('TIME', fmt_time(self.time_played))]
