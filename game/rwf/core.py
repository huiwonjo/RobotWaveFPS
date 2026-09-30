"""SimClock, EventBus, InputState, text cache, math helpers, registries, mouse lock (spec 7.4)."""
import math
import sys
from collections import OrderedDict

import pygame

from . import config as C
from . import theme


# ============================ clock ==========================================
class SimClock:
    """Simulation time. Everything in gameplay reads world.now / world.dt from this."""

    def __init__(self):
        self.now = 0.0
        self.dt = 0.0
        self.timescale = 1.0
        self.paused = False
        self._slowmo_left = 0.0

    def tick(self, real_dt):
        if self.paused:
            self.dt = 0.0
            return 0.0
        if self._slowmo_left > 0.0:
            self._slowmo_left -= real_dt
            if self._slowmo_left <= 0.0:
                self._slowmo_left = 0.0
                self.timescale = 1.0
        self.dt = min(max(real_dt, 0.0), 0.05) * self.timescale
        self.now += self.dt
        return self.dt

    def slowmo(self, scale, real_seconds):
        self.timescale = scale
        self._slowmo_left = real_seconds


def real_time():
    """Real seconds since pygame.init(); for UI animation only (never gameplay)."""
    return pygame.time.get_ticks() / 1000.0


# ============================ events =========================================
class EventBus:
    """Synchronous pub/sub. Handlers get one dict.

    data always has 'event' (the event name) and 't' (sim now). It also has 'name':
    the event name, unless the payload defines its own 'name' key (kill,
    ability_used, ult_used and sfx do, see 7.5), which then wins.
    Subscribing to '*' receives every event.
    """

    def __init__(self, clock=None):
        self.clock = clock
        self._subs = {}

    def on(self, name, fn):
        lst = self._subs.get(name, ())
        if fn not in lst:
            self._subs[name] = tuple(lst) + (fn,)     # copy-on-write: emit iterates safely

    def off(self, name, fn):
        lst = self._subs.get(name)
        if lst and fn in lst:
            self._subs[name] = tuple(f for f in lst if f is not fn)

    def emit(self, name, /, **data):
        data['event'] = name
        if 'name' not in data:
            data['name'] = name
        data['t'] = self.clock.now if self.clock is not None else 0.0
        subs = self._subs
        lst = subs.get(name)
        if lst:
            for fn in lst:
                fn(data)
        lst = subs.get('*')
        if lst:
            for fn in lst:
                fn(data)

    def clear(self):
        self._subs = {}


# ============================ settings =======================================
# Session settings any module may READ (screens show them on the pause panel). app changes them:
# 'sens' = look-sensitivity multiplier ([ and ], 0.4-2.5). The mute state lives in sfx.muted.
SETTINGS = {'sens': 1.0}


# ============================ input ==========================================
_KEY_ITEMS = tuple(C.KEYMAP.items())
_KEY_ACTIONS = frozenset(C.KEYMAP.values())


class InputState:
    """Actions (not keys). Events and key.get_pressed() are OR'd (spec 2.1).

    Mouse buttons come from events only. `sens` (the look-sensitivity multiplier) reads and writes
    core.SETTINGS['sens'], so screens can show it without an InputState.
    """

    def __init__(self):
        self.held = set()
        self.pressed = set()
        self.released = set()
        self.mouse_dx = 0.0
        self.mouse_dy = 0.0
        self.mouse_pos = (C.W // 2, C.H // 2)
        self._ev_keys = set()       # key codes held according to events
        self._mouse_held = set()    # actions held by mouse buttons
        self._prev = set()          # held snapshot after the last poll

    @property
    def sens(self):
        return SETTINGS['sens']

    @sens.setter
    def sens(self, v):
        SETTINGS['sens'] = float(v)

    def _held_by_events(self, action):
        if action in self._mouse_held:
            return True
        for k in self._ev_keys:
            if C.KEYMAP.get(k) == action:
                return True
        return False

    def _down(self, action):
        if action not in self.held:
            self.pressed.add(action)
        self.held.add(action)

    def _up(self, action):
        if not self._held_by_events(action) and action in self.held:
            self.held.discard(action)
            self.released.add(action)

    def feed(self, ev):
        t = ev.type
        if t == pygame.KEYDOWN:
            a = C.KEYMAP.get(ev.key)
            if a is not None:
                self._ev_keys.add(ev.key)
                self._down(a)
        elif t == pygame.KEYUP:
            a = C.KEYMAP.get(ev.key)
            if a is not None:
                self._ev_keys.discard(ev.key)
                self._up(a)
        elif t == pygame.MOUSEBUTTONDOWN:
            a = C.MOUSEMAP.get(getattr(ev, 'button', 0))
            if a is not None:
                self._mouse_held.add(a)
                self._down(a)
            self.mouse_pos = getattr(ev, 'pos', self.mouse_pos)
        elif t == pygame.MOUSEBUTTONUP:
            a = C.MOUSEMAP.get(getattr(ev, 'button', 0))
            if a is not None:
                self._mouse_held.discard(a)
                self._up(a)
            self.mouse_pos = getattr(ev, 'pos', self.mouse_pos)
        elif t == pygame.MOUSEMOTION:
            rel = getattr(ev, 'rel', (0, 0))
            self.mouse_dx += rel[0]
            self.mouse_dy += rel[1]
            self.mouse_pos = getattr(ev, 'pos', self.mouse_pos)

    def poll_keyboard(self):
        polled = set()
        try:
            kp = pygame.key.get_pressed()
            for k, a in _KEY_ITEMS:
                if kp[k]:
                    polled.add(a)
        except Exception:
            pass
        new = set(self._mouse_held)
        for k in self._ev_keys:
            a = C.KEYMAP.get(k)
            if a is not None:
                new.add(a)
        new |= polled
        prev = self._prev
        for a in new - prev:
            self.pressed.add(a)
        for a in prev - new:
            self.released.add(a)
        self.held = new
        self._prev = set(new)

    def end_frame(self):
        self.pressed.clear()
        self.released.clear()
        self.mouse_dx = 0.0
        self.mouse_dy = 0.0

    def clear(self):
        self.held.clear()
        self.pressed.clear()
        self.released.clear()
        self._ev_keys.clear()
        self._mouse_held.clear()
        self._prev.clear()
        self.mouse_dx = 0.0
        self.mouse_dy = 0.0

    def down(self, action):
        return action in self.held

    def hit(self, action):
        return action in self.pressed

    def up(self, action):
        return action in self.released

    def axes(self):
        h = self.held
        fwd = (1 if 'fwd' in h else 0) - (1 if 'back' in h else 0)
        right = (1 if 'right' in h else 0) - (1 if 'left' in h else 0)
        return fwd, right


# ============================ text ===========================================
_DEFAULT_SIZES = {'xs': 18, 's': 22, 'm': 28, 'l': 46, 'xl': 74}
_TTF_SIZES = {'xs': 12, 's': 15, 'm': 20, 'l': 33, 'xl': 53}
_fonts = {}
_text_cache = OrderedDict()
TEXT_CACHE_SIZE = 512


def font(size_key):
    f = _fonts.get(size_key)
    if f is None:
        if not pygame.font.get_init():
            pygame.font.init()
        path = theme.font_path()
        f = None
        if path:
            try:
                f = pygame.font.Font(path, _TTF_SIZES.get(size_key, 20))
            except Exception:
                f = None
        if f is None:
            f = pygame.font.Font(None, _DEFAULT_SIZES.get(size_key, 28))
        try:
            f.italic = True
        except Exception:
            pass
        _fonts[size_key] = f
    return f


def text(s, size_key='m', color=(255, 255, 255)):
    """Rendered text surface from an LRU cache (512 entries). Treat it as read-only."""
    key = (s, size_key, color)
    surf = _text_cache.get(key)
    if surf is not None:
        _text_cache.move_to_end(key)
        return surf
    surf = font(size_key).render(str(s), True, color)
    _text_cache[key] = surf
    if len(_text_cache) > TEXT_CACHE_SIZE:
        _text_cache.popitem(last=False)
    return surf


# ============================ math ===========================================
TAU = 2.0 * math.pi


def wrap_angle(a):
    """Wrap to (-pi, pi]."""
    a = (a + math.pi) % TAU - math.pi
    if a <= -math.pi:
        a += TAU
    return a


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def dist(ax, ay, bx, by):
    return math.hypot(bx - ax, by - ay)


# ============================ mouse lock =====================================
IS_WEB = sys.platform == 'emscripten'


def lock_mouse(on):
    try:
        pygame.event.set_grab(bool(on))
        pygame.mouse.set_visible(not on)
    except Exception:
        pass


def pointer_locked():
    """True/False when known; None when the state can't be read.

    Browser: document.pointerLockElement. Desktop: pygame's grab state.
    """
    if IS_WEB:
        try:
            import platform as _web_platform     # pygbag's browser bridge module
            return bool(_web_platform.window.document.pointerLockElement)
        except Exception:
            return None
    try:
        return bool(pygame.event.get_grab())
    except Exception:
        return None


_web_failed = [False]


def web_set(name, value):
    """Browser only: window[name] = value (a test hook: app publishes RWF_STATE for tools/webtest.py).
    A no-op on desktop; the first failure disables it for the session."""
    if not IS_WEB or _web_failed[0]:
        return
    try:
        import platform as _web_platform     # pygbag's browser bridge module
        setattr(_web_platform.window, name, value)
    except Exception:
        _web_failed[0] = True


# ============================ registries =====================================
HEROES = {}
HERO_ORDER = ['vector', 'flicker', 'rampart']
ENEMY_TYPES = {}


def register_hero(cls):
    HEROES[cls.KEY] = cls
    return cls


def register_enemy(cls):
    ENEMY_TYPES[cls.KIND] = cls
    return cls
