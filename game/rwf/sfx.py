"""Synthesised sound effects (spec 6.5). HUD_UX owns this file.

Contract (7.4): init() after the first input (never raises), attach(bus) maps bus events to sounds,
play(name, vol) is a no-op for unknown names or while disabled / muted, update() synthesises at most
ONE sound per call (the app calls it once per frame), set_muted(on) toggles M.

Sounds are built with array('h') at the mixer's own frequency and channel count, then handed to
pygame.mixer.Sound(buffer=...). Only 16-bit signed mixers (size -16) are used; anything else, or any
exception, leaves `enabled` False and every call silent. Each sound is at most 0.35 s long.
No numpy, no threads: plain Python loops over at most ~8k samples (see SYNTH_MAX_RATE).
"""
import math
import random
from array import array

import pygame

from . import core

# ============================ tuning ==========================================
TUNING = {
    'mixer': (22050, -16, 2, 512),      # used only when the mixer is not initialised yet
    'channels': 12,
    'master': 0.55,                     # overall volume (per-play vol is multiplied in)
    'max_len': 0.35,                    # seconds, hard cap per sound
    'ability_ready_min_cd': 4.0,        # the HUD plays 'ability_ready' only for cooldowns >= this
}

# Minimum real seconds between two plays of the same sound (spec 6.5 lists the first four).
THROTTLE = {
    'hit': 0.05, 'shot_rifle': 0.04, 'shot_pistol': 0.04, 'enemy_shot': 0.08, 'beep': 0.10,
    'crit': 0.04, 'hurt': 0.07, 'barrier_hit': 0.06, 'explosion': 0.05, 'capture': 0.9,
    'rocket': 0.10, 'blink': 0.08, 'hammer': 0.08, 'melee': 0.10, 'ability_ready': 0.10, 'ui': 0.04,
    'hammer_low': 0.10, 'rewind': 0.20, 'heal': 0.30,
}

enabled = False
muted = False

_st = {'freq': 22050, 'ch': 2, 'sounds': {}, 'queue': [], 'last': {}}
_rng = random.Random(4242)


# ============================ synthesis helpers ==============================
# Recipes run at an internal rate of at most SYNTH_MAX_RATE; a 44.1/48 kHz mixer gets every sample
# repeated (zero-order hold), which halves the Python work. Envelopes are running multipliers (no exp()
# per sample) and every loop keeps its callables in locals: about 1-3 ms per sound on desktop.
SYNTH_MAX_RATE = 24000


def _n(sec, sr):
    return max(1, int(min(sec, TUNING['max_len']) * sr))


def _edges(out, sr):
    """In-place 4 ms fade-in and 64-sample fade-out (no clicks at the ends)."""
    n = len(out)
    a = min(n, max(1, int(0.004 * sr)))
    for i in range(a):
        out[i] *= i / a
    b = min(n, 64)
    for j in range(b):
        out[n - 1 - j] *= j / b


def _tone(sr, sec, f0, f1=None, shape='sine', decay=None, gain=1.0):
    """A (possibly swept) tone. shape: sine | square | saw. decay: e-folding time in s or None."""
    n = _n(sec, sr)
    f1 = f0 if f1 is None else f1
    k2 = 2.0 * math.pi / sr
    w0 = f0 * k2
    dw = (f1 - f0) * k2 / n
    mul = math.exp(-1.0 / (decay * sr)) if decay else 1.0
    env = float(gain)
    out = [0.0] * n
    ph = 0.0
    sin = math.sin
    if shape == 'square':
        for i in range(n):
            ph += w0 + dw * i
            out[i] = (0.55 if sin(ph) >= 0.0 else -0.55) * env
            env *= mul
    elif shape == 'saw':
        inv = 1.0 / (2.0 * math.pi)
        for i in range(n):
            ph += w0 + dw * i
            out[i] = (((ph * inv) % 1.0) * 1.2 - 0.6) * env
            env *= mul
    else:
        for i in range(n):
            ph += w0 + dw * i
            out[i] = sin(ph) * env
            env *= mul
    _edges(out, sr)
    return out


def _shaped_noise(sr, sec, alpha, decay, gain=1.0, highpass=False):
    """One-pole low-passed white noise (alpha 0..1: smaller = darker) with an exponential decay."""
    n = _n(sec, sr)
    mul = math.exp(-1.0 / (decay * sr))
    env = float(gain)
    out = [0.0] * n
    y = 0.0
    prev = 0.0
    rnd = _rng.random
    for i in range(n):
        y += alpha * (rnd() * 2.0 - 1.0 - y)
        if highpass:
            out[i] = (y - prev) * env
            prev = y
        else:
            out[i] = y * env
        env *= mul
    _edges(out, sr)
    return out


def _mix(*parts):
    n = max(len(q) for q in parts)
    out = list(parts[0]) + [0.0] * (n - len(parts[0]))
    for q in parts[1:]:
        for i, v in enumerate(q):
            out[i] += v
    return out


def _notes(sr, freqs, each, decay=0.08, gain=0.8):
    out = []
    for f in freqs:
        out += _mix(_tone(sr, each, f, decay=decay, gain=gain), _tone(sr, each, f * 2.0, decay=decay * 0.6,
                                                                      gain=gain * 0.25))
    return out[:_n(TUNING['max_len'], sr)]


# ============================ recipes (spec 6.5 table) =======================
def _r_shot_rifle(sr):
    return _mix(_shaped_noise(sr, 0.06, 0.55, 0.018, 0.55), _tone(sr, 0.06, 180, 120, decay=0.03, gain=0.8))


def _r_shot_pistol(sr):
    return _mix(_shaped_noise(sr, 0.035, 0.9, 0.008, 0.8, highpass=True),
                _tone(sr, 0.035, 2200, 1500, decay=0.01, gain=0.35))


def _r_hammer(sr):
    return _mix(_shaped_noise(sr, 0.12, 0.08, 0.05, 1.2), _tone(sr, 0.12, 95, 60, decay=0.06, gain=0.7))


def _r_hammer_low(sr):
    return _mix(_shaped_noise(sr, 0.2, 0.05, 0.08, 1.3), _tone(sr, 0.2, 70, 38, decay=0.1, gain=0.9))


def _r_melee(sr):
    return _mix(_shaped_noise(sr, 0.08, 0.15, 0.03, 1.0), _tone(sr, 0.08, 140, 80, decay=0.04, gain=0.6))


def _r_hit(sr):
    return _tone(sr, 0.03, 1800, decay=0.012, gain=0.7)


def _r_crit(sr):
    return _mix(_tone(sr, 0.09, 2400, decay=0.035, gain=0.55), _tone(sr, 0.09, 3600, decay=0.03, gain=0.4))


def _r_elim(sr):
    return _tone(sr, 0.15, 700, 200, shape='square', decay=0.1, gain=0.7)


def _r_hurt(sr):
    return _mix(_tone(sr, 0.08, 120, 100, shape='saw', decay=0.05, gain=0.9),
                _shaped_noise(sr, 0.08, 0.3, 0.03, 0.25))


def _r_ult_ready(sr):
    return _notes(sr, (660, 880, 1320), 0.1, decay=0.07)


def _r_ult(sr):
    return _mix(_tone(sr, 0.3, 300, 900, decay=0.2, gain=0.7), _tone(sr, 0.3, 450, 1350, decay=0.15, gain=0.25))


def _r_ability_ready(sr):
    return _tone(sr, 0.06, 1200, decay=0.03, gain=0.6)


def _r_explosion(sr):
    return _mix(_shaped_noise(sr, 0.3, 0.05, 0.1, 1.4), _tone(sr, 0.3, 70, 40, decay=0.08, gain=0.7))


def _r_barrier_hit(sr):
    return _mix(_tone(sr, 0.04, 400, 300, decay=0.012, gain=0.8), _shaped_noise(sr, 0.04, 0.4, 0.01, 0.2))


def _r_enemy_shot(sr):
    return _tone(sr, 0.05, 900, 500, shape='square', decay=0.03, gain=0.45)


def _r_blink(sr):
    return _tone(sr, 0.12, 400, 1600, decay=0.08, gain=0.6)


def _r_rewind(sr):
    return _mix(_tone(sr, 0.3, 1400, 300, decay=0.2, gain=0.5), _tone(sr, 0.3, 700, 150, decay=0.2, gain=0.3))


def _r_heal(sr):
    return _mix(_tone(sr, 0.25, 520, 780, decay=0.12, gain=0.5), _tone(sr, 0.25, 1040, 1560, decay=0.08, gain=0.15))


def _r_rocket(sr):
    return _mix(_shaped_noise(sr, 0.2, 0.2, 0.08, 0.8), _tone(sr, 0.2, 220, 330, decay=0.08, gain=0.4))


def _r_beep(sr):
    return _tone(sr, 0.06, 1000, shape='square', decay=0.05, gain=0.45)


def _r_warn(sr):
    return _tone(sr, 0.125, 440, shape='square', gain=0.4) + _tone(sr, 0.125, 330, shape='square', gain=0.4)


def _r_capture(sr):
    return _mix(_tone(sr, 0.08, 880, decay=0.04, gain=0.5), _tone(sr, 0.08, 1760, decay=0.03, gain=0.2))


def _r_ui(sr):
    return _tone(sr, 0.04, 1500, 1200, decay=0.015, gain=0.5)


def _r_pickup(sr):
    return _notes(sr, (700, 1050), 0.07, decay=0.05, gain=0.6)


def _r_wave(sr):
    return _notes(sr, (440, 660), 0.14, decay=0.12, gain=0.6)


RECIPES = {
    'shot_rifle': _r_shot_rifle, 'shot_pistol': _r_shot_pistol, 'hammer': _r_hammer, 'melee': _r_melee,
    'hit': _r_hit, 'crit': _r_crit, 'elim': _r_elim, 'hurt': _r_hurt, 'ult_ready': _r_ult_ready,
    'ult': _r_ult, 'ability_ready': _r_ability_ready, 'explosion': _r_explosion, 'barrier_hit': _r_barrier_hit,
    'enemy_shot': _r_enemy_shot, 'blink': _r_blink, 'rewind': _r_rewind, 'rocket': _r_rocket, 'beep': _r_beep,
    'warn': _r_warn, 'capture': _r_capture, 'ui': _r_ui, 'pickup': _r_pickup, 'wave': _r_wave,
    'hammer_low': _r_hammer_low, 'heal': _r_heal,
}
# Synthesis order after init: the sounds heard most often first.
ORDER = ('ui', 'shot_rifle', 'shot_pistol', 'hit', 'crit', 'elim', 'hurt', 'enemy_shot', 'hammer', 'blink',
         'explosion', 'ability_ready', 'ult_ready', 'ult', 'barrier_hit', 'rocket', 'beep', 'warn', 'melee',
         'capture', 'pickup', 'wave', 'rewind', 'hammer_low', 'heal')


def synth(name, sr=22050):
    """Mono float samples (about [-1, 1]) for a recipe at sample rate sr, at most max_len long."""
    return RECIPES[name](sr)[:_n(TUNING['max_len'], sr)]


def _to_sound(samples, up=1):
    """int16 buffer at the mixer's channel count; each sample repeated `up` times (rate conversion)."""
    ch = _st['ch']
    peak = max(max(samples), -min(samples), 1.0)
    k = 30000.0 / peak
    mono = array('h', [int(v * k) for v in samples])
    step = ch * up
    if step == 1:
        buf = mono
    else:
        buf = array('h', bytes(2 * len(mono) * step))
        for j in range(step):
            buf[j::step] = mono
    return pygame.mixer.Sound(buffer=buf)


def _rates(freq):
    """(internal synthesis rate, repeat factor) for a mixer frequency."""
    up = 1
    while freq // up > SYNTH_MAX_RATE and up < 4:
        up *= 2
    return freq // up, up


# ============================ public API =====================================
def init():
    """Called by app on the first KEYDOWN / MOUSEBUTTONDOWN. Never raises."""
    global enabled
    enabled = False
    try:
        mx = pygame.mixer
        info = mx.get_init()
        if info is None:
            mx.init(*TUNING['mixer'])
            info = mx.get_init()
        if not info or int(info[1]) != -16:
            return
        mx.set_num_channels(TUNING['channels'])
        _st['freq'] = int(info[0])
        _st['ch'] = max(1, int(info[2]))
        _st['sounds'] = {}
        _st['queue'] = list(ORDER)
        _st['last'] = {}
        enabled = True
    except Exception:
        enabled = False


def update():
    """Synthesise at most one pending sound (spec 8 rule 9). Cheap when there is nothing to do."""
    global enabled
    if not enabled:
        return
    q = _st['queue']
    if not q:
        return
    name = q.pop(0)
    if name in _st['sounds']:
        return
    try:
        sr, up = _rates(_st['freq'])
        _st['sounds'][name] = _to_sound(synth(name, sr), up)
    except Exception:
        enabled = False


def play(name, vol=1.0):
    """Play a synthesised sound. Unknown names, a disabled mixer and mute are silent no-ops."""
    if not enabled or muted or name not in RECIPES:
        return
    thr = THROTTLE.get(name)
    if thr:
        now = core.real_time()
        last = _st['last']
        if now - last.get(name, -9.0) < thr:
            return
        last[name] = now
    snd = _st['sounds'].get(name)
    if snd is None:
        q = _st['queue']            # not built yet: build it next, skip this play
        if name in q:
            q.remove(name)
        q.insert(0, name)
        return
    try:
        chan = snd.play()
        if chan is not None:
            chan.set_volume(max(0.0, min(1.0, float(vol) * TUNING['master'])))
    except Exception:
        pass


def set_muted(on):
    global muted
    muted = bool(on)
    if muted:
        try:
            pygame.mixer.stop()
        except Exception:
            pass


def ready_count():
    """How many sounds are synthesised (for tests / the debug overlay)."""
    return len(_st['sounds'])


# ============================ bus mapping ====================================
def _is_hero(ent):
    return ent is not None and hasattr(ent, 'ult_active_left')


def _on_shot(d):
    play('shot_pistol' if d.get('hero') == 'flicker' else 'shot_rifle', 0.5)


def _on_ability_used(d):
    slot = d.get('slot')
    if slot == 'primary' and d.get('hero') == 'rampart':
        play('hammer', 0.8)
    elif slot == 'melee':
        play('melee', 0.7)
    elif slot == 'secondary' and d.get('hero') == 'vector':
        play('rocket', 0.6)


def _on_damage(d):
    if d.get('to_player') or not _is_hero(d.get('source')) or d.get('killed'):
        return
    if d.get('crit'):
        play('crit', 0.8)
    else:
        play('hit', 0.5)


def _on_kill(d):
    if _is_hero(d.get('source')) and not _is_hero(d.get('target')):
        play('elim', 0.8)


def _on_player_hurt(d):
    play('hurt', 0.6)


def _on_ult_ready(d):
    play('ult_ready', 0.8)


def _on_ult_used(d):
    play('ult', 0.9)


def _on_explosion(d):
    play('explosion', 0.8)


def _on_barrier_damage(d):
    play('barrier_hit', 0.4)


def _on_sfx(d):
    """'sfx' events. An optional 'variant' picks a variant sound when one exists: the variant's own
    name (FLICKER Rewind sends name 'blink', variant 'rewind') or '<name>_<variant>' (RAMPART's charge
    impact sends 'hammer' + 'low' -> 'hammer_low'); otherwise the plain name plays."""
    name = d.get('name', '')
    v = d.get('variant')
    if v:
        if v in RECIPES:
            name = v
        elif name + '_' + str(v) in RECIPES:
            name = name + '_' + str(v)
    play(name, d.get('vol', 1.0) or 1.0)


def _on_objective(d):
    st = d.get('state')
    if st == _st.get('obj'):
        return                          # transitions only (the HUD ticks once per second while capturing)
    _st['obj'] = st
    if st in ('captured', 'capturing'):
        play('capture', 0.7)
    elif st in ('contested', 'overtime', 'failed'):
        play('warn', 0.5)


def _on_wave_start(d):
    _st['obj'] = None
    play('wave', 0.6)


def _on_warn(d):
    play('warn', 0.7)


def _on_pack(d):
    play('pickup', 0.6)


_MAP = (('shot', _on_shot), ('ability_used', _on_ability_used), ('damage', _on_damage), ('kill', _on_kill),
        ('player_hurt', _on_player_hurt), ('ult_ready', _on_ult_ready), ('ult_used', _on_ult_used),
        ('explosion', _on_explosion), ('barrier_damage', _on_barrier_damage), ('sfx', _on_sfx),
        ('objective', _on_objective), ('wave_start', _on_wave_start), ('boss_spawn', _on_warn),
        ('boss_phase', _on_warn), ('pack_pickup', _on_pack))


def attach(bus):
    """Subscribe the event -> sound mapping on a match's bus (called once per match by app).
    'ability_ready' is played by the HUD, which knows the ability's cooldown (spec 6.4: >= 4 s only)."""
    _st['obj'] = None
    for name, fn in _MAP:
        bus.on(name, fn)
