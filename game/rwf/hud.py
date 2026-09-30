"""In-match HUD (spec 6.3 layout, 6.4 feedback). HUD_UX owns this file.

Structure (so the look can be redesigned without touching the logic):
  1. LAYOUT / STYLE constants (1024x768 screen coordinates, colours).
  2. Cached static layers (module level, built once, lazily after set_mode): minimap walls, the
     bottom-left hero plate, tile icons (plain + greyed), ring backgrounds, vignette strips, arc sprites.
  3. The HUD class: bus handlers keep small timed lists (kill feed, pop-ups, arcs, banner, prompt,
     hitmarker); update() advances a UI clock by real_dt; draw() paints elements in a fixed order.

Rules honoured (spec 8): no per-frame surface allocation above 64x64 (rows, pop-ups and chips are built at
event time or once; the tile pie uses preallocated 52x52 scratch surfaces), all text via core.text(),
tints via BLEND_RGB_ADD / BLEND_RGB_MULT fills, caps: feed 5, pop-ups 3, arcs 4.
`drawn` holds the names of the elements drawn in the last frame (tests read it; costs a few set adds).
"""
import math

import pygame

from . import config as C
from . import core
from . import render
from . import sfx
from . import theme
from .world import MAP_H, MAP_W, WALL_GRID

# ============================ 1. layout ======================================
CX, CY = C.W // 2, C.H // 2
MINI_RECT = (12, 12, 140, 140)
MINI_CELL = 7
SCORE_POS = (12, 158)
MULT_POS = (12, 184)
STAGE_Y = 10
WAVE_LABEL_Y = 38
OBJ_CENTER = (512, 86)
OBJ_R = 28
OBJ_W = 5
OBJ_STEPS = 48
OBJ_TIMER_POS = (552, 76)
OBJ_LABEL_Y = 122
OBJ_BOSS_SHIFT = 40                 # never both in a real wave; keeps them apart if a mode ever mixes them
OBJ_POINT_Z = 0.9
MARKER_HALF = 7                     # diamond of 14 px
MARKER_MARGIN = 24
BOSS_RECT = (302, 64, 420, 14)
BOSS_NAME_POS = (302, 44)
FEED_RIGHT = 1012
FEED_Y = 12
FEED_STEP = 28
FEED_MAX = 5
FEED_LIFE = 4.0
FEED_FADE = 0.5
FEED_ROW_H = 24
HIT_GAP = 8
HITMARKS = {'body': (10, 0.12, 2), 'crit': (14, 0.18, 2), 'kill': (18, 0.30, 3)}   # length, life, width
POPUP_Y = 440
POPUP_STEP = 24
POPUP_MAX = 3
POPUP_LIFE = 2.0
PROMPT_Y = 620
ULT_READY_LIFE = 1.5
CALLOUT_LIFE = 1.2
BANNER_Y = 230
BANNER_LIFE = 2.0
CLEAR_LIFE = 1.5
BANNER_WIPE = 0.15
ARC_R = 120
ARC_HALF = math.radians(25)
ARC_W = 6
ARC_LIFE = 0.8
ARC_MAX = 4
ARC_BUCKET_DEG = 5
ARC_MERGE = math.radians(15)
PORTRAIT_RECT = (20, 668, 72, 72)
NAME_POS = (104, 668)
HP_RECT = (104, 694, 280, 18)
HP_UNIT = 25.0
HP_GAP = 2
HP_MIN_SEG = 4
HP_NUM_POS = (104, 716)
CHIP_POS = (392, 694)
CHIP_H = 18
CHIP_STEP = 20
ULT_CENTER = (512, 700)
ULT_R = 38
ULT_W = 6
ARC_STEPS = 64
TILE = 52
TILE_GAP = 8
TILE_RIGHT = 872
TILE_Y = 684
PIP_Y = 676
PIP = 6
PIP_GAP = 3
KEY_Y = 738
TILE_FLASH = 0.25
AMMO_RIGHT = 1004
AMMO_Y = 682
RELOAD_RECT = (884, 742, 120, 6)
RELOAD_HINT_Y = 410
EBAR_W = 40
EBAR_H = 4
EBAR_UP = 8
EBAR_SHOW = 3.0
VIGNETTE_T = 60
VIGNETTE_LEVELS = 4
LOW_HP_FRAC = 0.35
HURT_SHAKE = (2, 0.1)
GHOST_DELAY = 0.35
GHOST_RATE = 160.0                  # HP/s the "recently lost" chunk drains at

# ============================ 1b. style ======================================
WHITE = (255, 255, 255)
SHADOW = (0, 0, 0)
MUTED = (175, 182, 198)
PANEL_INK = theme.PALETTE.get('ink', (12, 16, 26))
TRACK = C.COL_MISSING
GHOST_COL = (255, 120, 100)
FEED_KILLER = (80, 190, 255)
FEED_VICTIM = (255, 90, 80)
ARC_COL = (230, 40, 40)
STAGE_COLORS = ((255, 140, 0), (0, 210, 240), (180, 80, 255), (255, 80, 80), (255, 220, 0))
KIND_COLORS = {'trooper': (230, 70, 60), 'slicer': (255, 120, 120), 'detonator': (255, 170, 40),
               'eradicator': (120, 150, 255), 'warden': (220, 80, 255), 'dummy': (200, 200, 200)}
OBJ_COLORS = {'neutral': (235, 241, 237), 'capturing': (80, 170, 255), 'contested': (255, 150, 40),
              'overtime': (255, 70, 60), 'captured': (90, 220, 130), 'failed': (140, 150, 170)}
OBJ_LABELS = {'neutral': 'HEAD TO POINT A', 'capturing': 'CAPTURING', 'contested': 'CONTESTED',
              'overtime': 'OVERTIME', 'captured': 'POINT CAPTURED', 'failed': 'CAPTURE FAILED'}
STATUS_CHIPS = (('stun', 'STUN', (255, 220, 80)), ('pinned', 'PINNED', (255, 220, 80)),
                ('root', 'ROOT', (255, 170, 60)), ('slow', 'SLOW', (160, 190, 255)),
                ('invuln', 'INVULN', (0, 230, 255)))
MINI_BG = (14, 18, 26)
MINI_WALL = (110, 104, 96)
MINI_EDGE = (70, 84, 110)
PACK_DOT = (60, 220, 90)
TILE_BG = (24, 28, 38)
TILE_EDGE = (70, 80, 100)

# ============================ 2. cached static layers ========================
_cache = {}
_TAU = 2.0 * math.pi


def ring_poly(cx, cy, r_out, r_in, f0, f1, steps=ARC_STEPS):
    """Thick arc from fraction f0 to f1 (0 = top, clockwise) as one polygon (no draw.arc gaps)."""
    n = max(1, int(math.ceil(abs(f1 - f0) * steps)))
    outer = []
    inner = []
    cos = math.cos
    sin = math.sin
    for i in range(n + 1):
        a = -math.pi / 2 + _TAU * (f0 + (f1 - f0) * i / n)
        c = cos(a)
        s = sin(a)
        outer.append((cx + c * r_out, cy + s * r_out))
        inner.append((cx + c * r_in, cy + s * r_in))
    inner.reverse()
    return outer + inner


def _minimap_bg():
    s = _cache.get('mini')
    if s is None:
        s = pygame.Surface((MINI_RECT[2], MINI_RECT[3]))
        s.fill(MINI_BG)
        for y in range(MAP_H):
            for x in range(MAP_W):
                if WALL_GRID[y][x]:
                    s.fill(MINI_WALL, (x * MINI_CELL, y * MINI_CELL, MINI_CELL, MINI_CELL))
        pygame.draw.rect(s, MINI_EDGE, s.get_rect(), 1)
        s = _conv(s)
        _cache['mini'] = s
    return s


def icon(cls, slot, size=TILE, grey=False):
    """Hero icon from cls.draw_icon, cached plain and greyed per (hero, slot, size)."""
    key = ('icon', cls.KEY, slot, size, grey)
    s = _cache.get(key)
    if s is None:
        if grey:
            s = icon(cls, slot, size, False).copy()
            try:
                s = pygame.transform.grayscale(s)
            except Exception:
                pass
            s.fill((120, 120, 120), special_flags=pygame.BLEND_RGB_MULT)
        else:
            s = pygame.Surface((size, size))
            s.fill(TILE_BG)
            try:
                cls.draw_icon(slot, s, s.get_rect())
            except Exception:
                t = core.text(slot[:1].upper(), 'm', cls.COLOR)
                s.blit(t, (size // 2 - t.get_width() // 2, size // 2 - t.get_height() // 2))
            pygame.draw.rect(s, TILE_EDGE, s.get_rect(), 1)
        s = _conv(s)
        _cache[key] = s
    return s


def _hero_plate(cls):
    """Bottom-left static layer: slanted panel, portrait and hero name (spec 6.3)."""
    key = ('plate', cls.KEY)
    s = _cache.get(key)
    if s is None:
        w, h = 392, 108
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.polygon(s, PANEL_INK + (170,), [(18, 0), (w, 0), (w - 18, h), (0, h)])
        pygame.draw.polygon(s, cls.COLOR + (255,), [(18, 0), (w, 0), (w - 1, 3), (17, 3)])
        px, py = PORTRAIT_RECT[0] - 8, PORTRAIT_RECT[1] - 656
        pr = pygame.Rect(px, py, PORTRAIT_RECT[2], PORTRAIT_RECT[3])
        s.blit(icon(cls, 'portrait', PORTRAIT_RECT[2]), pr)
        pygame.draw.rect(s, cls.COLOR, pr.inflate(4, 4), 2)
        _shadow_text(s, cls.NAME, 'm', cls.COLOR, (NAME_POS[0] - 8, NAME_POS[1] - 656))
        s = _conv(s, True)
        _cache[key] = s
    return s


def _plate(w, h, alpha=150, slant=14):
    key = ('pl', w, h, alpha, slant)
    s = _cache.get(key)
    if s is None:
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.polygon(s, PANEL_INK + (alpha,), [(slant, 0), (w, 0), (w - slant, h), (0, h)])
        s = _conv(s, True)
        _cache[key] = s
    return s


def _ult_bg():
    s = _cache.get('ultbg')
    if s is None:
        d = (ULT_R + 10) * 2
        s = pygame.Surface((d, d), pygame.SRCALPHA)
        c = d // 2
        pygame.draw.circle(s, PANEL_INK + (190,), (c, c), ULT_R + 4)
        pygame.draw.polygon(s, TRACK, ring_poly(c, c, ULT_R, ULT_R - ULT_W, 0.0, 0.999))
        s = _conv(s, True)
        _cache['ultbg'] = s
    return s


def _obj_bg():
    s = _cache.get('objbg')
    if s is None:
        d = (OBJ_R + 8) * 2
        s = pygame.Surface((d, d), pygame.SRCALPHA)
        c = d // 2
        pygame.draw.circle(s, PANEL_INK + (190,), (c, c), OBJ_R + 3)
        pygame.draw.polygon(s, TRACK, ring_poly(c, c, OBJ_R, OBJ_R - OBJ_W, 0.0, 0.999, OBJ_STEPS))
        s = _conv(s, True)
        _cache['objbg'] = s
    return s


def _vignette(level):
    """4 edge strips (dark red at the edge to black inside), added with BLEND_RGB_ADD."""
    key = ('vig', level)
    v = _cache.get(key)
    if v is None:
        k = (level + 1) / VIGNETTE_LEVELS
        T = VIGNETTE_T
        top = pygame.Surface((C.W, T))
        side = pygame.Surface((T, C.H - 2 * T))
        top.fill((0, 0, 0))
        side.fill((0, 0, 0))
        for i in range(T):
            f = (1.0 - i / T) ** 1.6
            col = (int(150 * k * f), int(8 * k * f), int(8 * k * f))
            top.fill(col, (0, i, C.W, 1))
            side.fill(col, (i, 0, 1, C.H - 2 * T))
        bottom = pygame.transform.flip(top, False, True)
        right = pygame.transform.flip(side, True, False)
        v = ((_conv(top), (0, 0)), (_conv(bottom), (0, C.H - T)), (_conv(side), (0, T)),
             (_conv(right), (C.W - T, T)))
        _cache[key] = v
    return v


def _arc_sprite(bucket):
    """Damage arc for a view-relative direction bucket (5 deg steps), drawn at radius ARC_R around the
    screen centre; returns (surface, top-left). Built once per bucket, then faded with set_alpha."""
    key = ('arc', bucket)
    v = _cache.get(key)
    if v is None:
        rel = math.radians(bucket * ARC_BUCKET_DEG)
        f_mid = rel / _TAU
        f0 = f_mid - ARC_HALF / _TAU
        f1 = f_mid + ARC_HALF / _TAU
        glow = ring_poly(CX, CY, ARC_R + ARC_W // 2 + 4, ARC_R - ARC_W // 2 - 4, f0, f1, 72)
        core_pts = ring_poly(CX, CY, ARC_R + ARC_W // 2, ARC_R - ARC_W // 2, f0, f1, 72)
        xs = [p[0] for p in glow]
        ys = [p[1] for p in glow]
        x0, y0 = int(min(xs)) - 1, int(min(ys)) - 1
        w, h = int(max(xs)) - x0 + 2, int(max(ys)) - y0 + 2
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.polygon(s, ARC_COL + (80,), [(x - x0, y - y0) for x, y in glow])
        pygame.draw.polygon(s, ARC_COL + (255,), [(x - x0, y - y0) for x, y in core_pts])
        v = (_conv(s, True), (x0, y0))
        _cache[key] = v
    return v


def _chip(label, color):
    key = ('chip', label, color)
    s = _cache.get(key)
    if s is None:
        t = core.text(label, 'xs', color)
        s = pygame.Surface((t.get_width() + 12, CHIP_H), pygame.SRCALPHA)
        s.fill(PANEL_INK + (210,))
        pygame.draw.rect(s, color, s.get_rect(), 1)
        s.blit(t, (6, CHIP_H // 2 - t.get_height() // 2))
        s = _conv(s, True)
        _cache[key] = s
    return s


def _scratch(i):
    key = ('scratch', i)
    s = _cache.get(key)
    if s is None:
        s = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        _cache[key] = s
    return s


def _shadow_text(surf, s, size, color, pos):
    """Text with a 2 px drop shadow (both surfaces from the core.text cache). Returns the text surface."""
    t = core.text(s, size, color)
    surf.blit(core.text(s, size, SHADOW), (pos[0] + 2, pos[1] + 2))
    surf.blit(t, pos)
    return t


def _shadow_center(surf, s, size, color, y, x=CX):
    t = core.text(s, size, color)
    x0 = x - t.get_width() // 2
    surf.blit(core.text(s, size, SHADOW), (x0 + 2, y + 2))
    surf.blit(t, (x0, y))
    return t


def seg_layout(maxes, width, unit=HP_UNIT, gap=HP_GAP, min_w=HP_MIN_SEG):
    """Segments for a pool bar: [(x, w, kind, lo, hi)], one per `unit` HP of each pool (health, armor,
    shields in that order). Width per segment = floor(width / n) - gap (at least min_w); when that does
    not fit, the unit doubles (boss bars). Cached per (maxes, width, unit)."""
    key = ('seg', maxes, width, unit, gap, min_w)
    lay = _cache.get(key)
    if lay is not None:
        return lay
    u = unit
    while True:
        n = sum(int(math.ceil(m / u - 1e-9)) for m in maxes if m > 0)
        n = max(1, n)
        sw = width // n - gap
        if sw >= min_w or u > 10000:
            break
        u *= 2.0
    sw = max(min_w, sw)
    lay = []
    x = 0
    for kind, m in zip(('health', 'armor', 'shields'), maxes):
        if m <= 0:
            continue
        k = int(math.ceil(m / u - 1e-9))
        for i in range(k):
            lo = i * u
            lay.append((x, sw, kind, lo, min(m, lo + u)))
            x += sw + gap
    _cache[key] = lay
    return lay


_bars = {}
_BAR_CACHE_MAX = 96
_KEY_COL = (255, 0, 255)


def _keyed(w, h):
    s = pygame.Surface((w, h))
    s.fill(_KEY_COL)
    return s


def _finish_keyed(s):
    s = _conv(s)
    s.set_colorkey(_KEY_COL)
    return s


def bar_images(maxes, width, h, unit=HP_UNIT, gap=HP_GAP, min_w=HP_MIN_SEG):
    """Cached strip images for a segmented pool bar: (empty, full, ghost, pools). empty / full / ghost are
    colour-keyed strips (gaps transparent) drawn once; pools maps kind -> [(x, w, lo, hi)] so a value
    converts to a filled x range. Per frame a bar is then 1 blit + 1-3 area blits instead of 2 fills per
    segment."""
    key = (maxes, width, h, unit, gap, min_w)
    v = _bars.get(key)
    if v is not None:
        return v
    if len(_bars) >= _BAR_CACHE_MAX:
        _bars.clear()
    lay = seg_layout(maxes, width, unit, gap, min_w)
    empty = _keyed(width, h)
    full = _keyed(width, h)
    ghost = _keyed(width, h)
    pools = {}
    for sx, sw, kind, lo, hi in lay:
        empty.fill(TRACK, (sx, 0, sw, h))
        full.fill(C.POOL_COLORS[kind], (sx, 0, sw, h))
        ghost.fill(GHOST_COL, (sx, 0, sw, h))
        pools.setdefault(kind, []).append((sx, sw, lo, hi))
    v = (_finish_keyed(empty), _finish_keyed(full), _finish_keyed(ghost), pools)
    _bars[key] = v
    return v


def _span(segs, val):
    """Filled x range [x0, x1) of one pool's segments for value `val` (segments fill from the left)."""
    if val <= 1e-6 or not segs:
        return 0, 0
    x0 = segs[0][0]
    u = segs[0][3] - segs[0][2]
    k = int(val / u) if u > 0 else len(segs) - 1
    if k >= len(segs):
        k = len(segs) - 1
    sx, sw, lo, hi = segs[k]
    if val >= hi - 1e-6:
        return x0, sx + sw
    return x0, sx + int(sw * (val - lo) / (hi - lo) + 0.5)


def draw_bar(surf, x, y, imgs, cur, ghost=None):
    """Draw a segmented pool bar from bar_images(). cur / ghost: {'health': v, 'armor': v, 'shields': v}."""
    empty, full, gh, pools = imgs
    h = empty.get_height()
    surf.blit(empty, (x, y))
    for kind, segs in pools.items():
        c = cur[kind]
        if ghost is not None and ghost[kind] > c + 0.5:
            g0, g1 = _span(segs, ghost[kind])
            if g1 > g0:
                surf.blit(gh, (x + g0, y), (g0, 0, g1 - g0, h))
        a, b = _span(segs, c)
        if b > a:
            surf.blit(full, (x + a, y), (a, 0, b - a, h))


def _conv(s, alpha=False):
    """Match the display format once (fast blits later); a no-op without a display."""
    try:
        return s.convert_alpha() if alpha else s.convert()
    except Exception:
        return s


# ============================ 3. HUD =========================================
_latest = {'obj': None}


def hud_for(world):
    """The HUD of `world` (the most recent match only), or None. For tests and tools."""
    h = _latest['obj']
    return h if h is not None and h.world is world else None


class HUD:
    def __init__(self, world):
        self.world = world
        self.t = 0.0                    # UI clock: real seconds, advanced by update()
        self.feed = []                  # [[surface, t0]] newest last
        self.popups = []                # [[surface, t0]] newest first
        self.arcs = []                  # [[from_x, from_y, t0]]
        self.hit = None                 # (kind, t0)
        self.prompt = None              # (kind, text, t0, life)
        self.banner = None              # ([(text, size, color)], t0, life)
        self.flash = {}                 # ability slot -> t0
        self.ghost = None               # per-pool "recently lost" values
        self._ghost_hold = GHOST_DELAY
        self._obj_tick = -9.0
        self.drawn = set()
        bus = world.bus
        for name, fn in (('damage', self._on_damage), ('kill', self._on_kill),
                         ('player_hurt', self._on_player_hurt), ('ult_ready', self._on_ult_ready),
                         ('ult_used', self._on_ult_used), ('ability_ready', self._on_ability_ready),
                         ('wave_start', self._on_wave_start), ('wave_clear', self._on_wave_clear),
                         ('objective', self._on_objective), ('boss_phase', self._on_boss_phase),
                         ('boss_spawn', self._on_boss_spawn), ('hero_swap', self._on_hero_swap)):
            bus.on(name, fn)
        _latest['obj'] = self

    # --- bus handlers (cheap; row / pop-up surfaces are built here, once per event) -------------
    def _is_player(self, ent):
        return ent is not None and ent is self.world.player

    def _on_damage(self, d):
        if d.get('to_player') or not self._is_player(d.get('source')):
            return
        kind = 'kill' if d.get('killed') else ('crit' if d.get('crit') else 'body')
        if self.hit is not None:
            old, t0 = self.hit
            order = ('body', 'crit', 'kill')
            if order.index(old) > order.index(kind) and self.t - t0 < HITMARKS[old][1]:
                return                  # keep the stronger marker while it lasts
        self.hit = (kind, self.t)

    def _on_kill(self, d):
        w = self.world
        if d['target'] is w.player or not self._is_player(d.get('source')):
            return                      # the player's own death and environment kills are not shown
        self.hit = ('kill', self.t)
        self.feed.append([self._feed_row(d), self.t])
        if len(self.feed) > FEED_MAX:
            del self.feed[:-FEED_MAX]
        self.popups.insert(0, [self._popup(d), self.t])
        del self.popups[POPUP_MAX:]

    def _on_player_hurt(self, d):
        fx, fy = d.get('from_x'), d.get('from_y')
        w = self.world
        w.shake(*HURT_SHAKE)
        if fx is None or fy is None:
            return
        p = w.player
        a_new = math.atan2(fy - p.y, fx - p.x)
        for arc in self.arcs:           # refresh an arc from about the same direction
            if abs(core.wrap_angle(math.atan2(arc[1] - p.y, arc[0] - p.x) - a_new)) < ARC_MERGE:
                arc[0], arc[1], arc[2] = fx, fy, self.t
                return
        self.arcs.append([fx, fy, self.t])
        if len(self.arcs) > ARC_MAX:
            del self.arcs[:-ARC_MAX]

    def _on_ult_ready(self, d):
        self.prompt = ('ready', 'ULTIMATE READY  [Q]', self.t, ULT_READY_LIFE)

    def _on_ult_used(self, d):
        self.prompt = ('callout', str(d.get('callout') or d.get('name') or 'ULT!'), self.t, CALLOUT_LIFE)

    def _on_ability_ready(self, d):
        slot = d.get('slot')
        self.flash[slot] = self.t
        ab = getattr(self.world.player, 'abilities', {}).get(slot)
        if ab is not None and slot in ('ab1', 'ab2', 'secondary') and \
                ab.cooldown >= sfx.TUNING['ability_ready_min_cd']:
            sfx.play('ability_ready', 0.6)

    def _on_wave_start(self, d):
        wi = d.get('wave_in_stage', d.get('wave', 0))
        self.banner = ([('WAVE %d' % wi, 'xl', WHITE), (str(d.get('label', '')), 'l', theme.PALETTE['accent'])],
                       self.t, BANNER_LIFE)

    def _on_wave_clear(self, d):
        self.banner = ([('WAVE CLEAR', 'xl', (120, 230, 140))], self.t, CLEAR_LIFE)

    def _on_objective(self, d):
        st = d.get('state')
        if st == 'captured':
            self.banner = ([(OBJ_LABELS['captured'], 'xl', OBJ_COLORS['captured'])], self.t, BANNER_LIFE)
        elif st == 'failed':
            self.banner = ([(OBJ_LABELS['failed'], 'xl', OBJ_COLORS['overtime'])], self.t, BANNER_LIFE)

    def _on_boss_spawn(self, d):
        e = d.get('enemy')
        name = getattr(e, 'NAME', theme.enemy_name('warden'))
        line = ('%s INCOMING' % name, 's', KIND_COLORS['warden'])
        if self.banner is not None and self.t - self.banner[1] < 0.2:
            lines, t0, life = self.banner            # same frame as wave_start: add a line to "WAVE 5 / BOSS"
            self.banner = (lines + [line], t0, life)
        else:
            self.banner = ([(name, 'xl', KIND_COLORS['warden']), ('BOSS INCOMING', 'l', WHITE)], self.t,
                           BANNER_LIFE)

    def _on_hero_swap(self, d):
        self.ghost = None                            # the new hero has other pools
        self.flash.clear()

    def _on_boss_phase(self, d):
        e = d.get('enemy')
        name = getattr(e, 'NAME', theme.enemy_name('warden'))
        self.banner = ([('%s - PHASE %s' % (name, d.get('phase', 2)), 'l', KIND_COLORS['warden'])],
                       self.t, CLEAR_LIFE)

    # --- event-time surfaces ---------------------------------------------------------------
    def _feed_row(self, d):
        """Kill feed row, pre-rendered once: killer, [TAG] box (skull for a crit), victim."""
        killer = core.text(str(d.get('killer') or self.world.player.NAME), 's', FEED_KILLER)
        tag = core.text('[%s]' % (d.get('label') or str(d.get('ability', '')).upper()), 'xs',
                        C.COL_ULT if d.get('ult') else WHITE)
        victim = core.text(str(d.get('name', '?')), 's', FEED_VICTIM)
        skull = 14 if d.get('crit') else 0
        tag_w = tag.get_width() + 10 + (skull + 4 if skull else 0)
        w = killer.get_width() + tag_w + victim.get_width() + 32
        h = FEED_ROW_H
        s = pygame.Surface((w, h))
        s.fill((14, 18, 28))
        s.fill(FEED_KILLER, (0, 0, 3, h))
        x = 8
        s.blit(killer, (x, h // 2 - killer.get_height() // 2))
        x += killer.get_width() + 8
        box = pygame.Rect(x, 3, tag_w, h - 6)
        s.fill((34, 40, 56), box)
        pygame.draw.rect(s, C.COL_ULT if d.get('ult') else (90, 100, 130), box, 1)
        s.blit(tag, (x + 5, h // 2 - tag.get_height() // 2))
        if skull:
            _draw_skull(s, x + 5 + tag.get_width() + 4, h // 2 - 7, C.COL_CRIT)
        x += tag_w + 8
        s.blit(victim, (x, h // 2 - victim.get_height() // 2))
        return _conv(s)

    def _popup(self, d):
        """Elimination pop-up '{KILL_WORD} {NAME} +{score}', pre-rendered once (faded with set_alpha)."""
        a = core.text(theme.WORDS['kill'], 's', WHITE)
        b = core.text(str(d.get('name', '?')), 's', FEED_VICTIM)
        sc = int(d.get('score', 0) or 0)
        c = core.text('+%d' % sc, 's', C.COL_ULT) if sc else None
        w = a.get_width() + b.get_width() + (c.get_width() + 8 if c else 0) + 28
        h = 22
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        s.fill(PANEL_INK + (150,))
        s.fill(C.COL_CRIT if d.get('crit') else FEED_VICTIM, (0, 0, 3, h))
        x = 10
        for t in (a, b, c):
            if t is None:
                continue
            s.blit(t, (x, h // 2 - t.get_height() // 2))
            x += t.get_width() + 8
        return _conv(s, True)

    # --- per frame ---------------------------------------------------------------------------
    def update(self, world, real_dt):
        self.t += max(0.0, real_dt)
        t = self.t
        if self.feed and t - self.feed[0][1] > FEED_LIFE:
            self.feed = [r for r in self.feed if t - r[1] <= FEED_LIFE]
        if self.popups and t - self.popups[-1][1] > POPUP_LIFE:
            self.popups = [r for r in self.popups if t - r[1] <= POPUP_LIFE]
        if self.arcs and t - self.arcs[0][2] > ARC_LIFE:
            self.arcs = [a for a in self.arcs if t - a[2] <= ARC_LIFE]
        if self.prompt is not None and t - self.prompt[2] > self.prompt[3]:
            self.prompt = None
        if self.banner is not None and t - self.banner[1] > self.banner[2]:
            self.banner = None
        # the "recently lost" chunk of the health bar drains after a short hold
        pool = world.player.pool
        cur = {'health': pool.health, 'armor': pool.armor, 'shields': pool.shields}
        g = self.ghost
        if g is None or real_dt <= 0:
            self.ghost = g = dict(cur) if g is None else g
        else:
            lost = False
            for k, v in cur.items():
                if v >= g[k]:
                    g[k] = v
                else:
                    lost = True
            if lost:
                if self._ghost_hold > 0:
                    self._ghost_hold -= real_dt
                else:
                    step = GHOST_RATE * real_dt
                    for k, v in cur.items():
                        if g[k] > v:
                            g[k] = max(v, g[k] - step)
            else:
                self._ghost_hold = GHOST_DELAY
        # objective capture tick: SFX 'capture' once per second while capturing
        ob = getattr(world.director, 'objective', None)
        if ob is not None and getattr(ob, 'state', '') == 'capturing' and t - self._obj_tick >= 1.0:
            self._obj_tick = t
            sfx.play('capture', 0.5)

    def draw(self, surf, world):
        drawn = self.drawn
        drawn.clear()
        p = world.player
        hs = p.hud_state(world)
        d = world.director
        low = self._draw_vignette(surf, hs)
        if low:
            drawn.add('vignette')
        self._draw_enemy_bars(surf, world)
        self._draw_objective_marker(surf, world, d)
        self._draw_arcs(surf, world)
        p.draw_crosshair(surf, world)
        self._draw_hitmarker(surf)
        self._draw_minimap(surf, world, d)
        self._draw_score(surf, world, d)
        boss_up = self._draw_boss_bar(surf, d)
        self._draw_wave_text(surf, d, boss_up)
        self._draw_objective_widget(surf, d, OBJ_BOSS_SHIFT if boss_up else 0)
        self._draw_feed(surf)
        self._draw_banner(surf)
        self._draw_popups(surf)
        self._draw_prompt(surf, hs)
        self._draw_hero_panel(surf, p, hs, low)
        self._draw_ult_ring(surf, hs)
        self._draw_tiles(surf, p, hs)
        self._draw_ammo(surf, hs)

    # --- elements -----------------------------------------------------------------------------
    def _draw_vignette(self, surf, hs):
        mx = hs.max_health + hs.max_armor + hs.max_shields
        tot = hs.health + hs.armor + hs.shields
        if mx <= 0 or tot <= 0 or tot >= LOW_HP_FRAC * mx:
            return False
        pulse = 0.5 + 0.5 * math.sin(self.t * _TAU)          # 1 Hz
        depth = 1.0 - tot / (LOW_HP_FRAC * mx)                  # stronger when lower
        k = 0.45 + 0.35 * pulse + 0.2 * depth
        level = max(0, min(VIGNETTE_LEVELS - 1, int(k * VIGNETTE_LEVELS)))
        add = pygame.BLEND_RGB_ADD
        for s, pos in _vignette(level):
            surf.blit(s, pos, special_flags=add)
        return True

    def _draw_enemy_bars(self, surf, world):
        now = world.now
        proj = world.projection
        n = 0
        for e in world.enemies:
            if not e.alive or getattr(e, 'BOSS', False) or now - e.last_hit > EBAR_SHOW:
                continue
            b = proj.get(e.id)
            if b is None or not b.visible:
                continue
            pl = e.pool
            imgs = bar_images((pl.max_health, pl.max_armor, pl.max_shields), EBAR_W, EBAR_H, HP_UNIT, 1, 2)
            x = (b.x0 + b.x1) // 2 - EBAR_W // 2
            y = b.y0 - EBAR_UP
            if y < 2:
                y = 2
            if x < 2:
                x = 2
            elif x > C.W - EBAR_W - 2:
                x = C.W - EBAR_W - 2
            surf.fill(SHADOW, (x - 1, y - 1, EBAR_W + 2, EBAR_H + 2))
            draw_bar(surf, x, y, imgs, {'health': pl.health, 'armor': pl.armor, 'shields': pl.shields})
            n += 1
        if n:
            self.drawn.add('enemy_bars')

    def _objective(self, d):
        ob = getattr(d, 'objective', None)
        if ob is None or getattr(d, 'kind', '') != 'capture':
            return None
        return ob

    def _draw_objective_marker(self, surf, world, d):
        ob = self._objective(d)
        if ob is None or ob.state in ('captured', 'failed') or getattr(ob, 'player_inside', False):
            return
        cam = world.cam
        ox, oy = getattr(ob, 'x', 10.0), getattr(ob, 'y', 10.0)
        pr = render.project_point(cam, ox, oy, OBJ_POINT_Z)
        m = MARKER_MARGIN
        if pr is not None and m <= pr[0] <= C.W - m and m <= pr[1] <= C.H - m:
            x, y = pr[0], pr[1]
        else:
            dx, dy = ox - cam.x, oy - cam.y
            ca, sa = math.cos(cam.angle), math.sin(cam.angle)
            depth = dx * ca + dy * sa
            lat = -dx * sa + dy * ca
            if pr is not None and depth > 0:
                x = core.clamp(pr[0], m, C.W - m)
                y = core.clamp(pr[1], m, C.H - m)
            else:                       # behind: pin to the side it is on
                x = C.W - m if lat >= 0 else m
                y = core.clamp(CY + int(cam.pitch), m, C.H - m)
        col = OBJ_COLORS.get(ob.state, OBJ_COLORS['neutral'])
        hh = MARKER_HALF
        pts = [(x, y - hh), (x + hh, y), (x, y + hh), (x - hh, y)]
        pygame.draw.polygon(surf, SHADOW, [(px + 1, py + 2) for px, py in pts])
        pygame.draw.polygon(surf, col, pts)
        pygame.draw.polygon(surf, WHITE, pts, 1)
        dist_m = int(round(math.hypot(ox - world.player.x, oy - world.player.y) * 2))
        t = core.text('A %dm' % dist_m, 'xs', col)
        tx = int(core.clamp(x - t.get_width() // 2, 2, C.W - t.get_width() - 2))
        surf.blit(core.text('A %dm' % dist_m, 'xs', SHADOW), (tx + 1, y + hh + 4))
        surf.blit(t, (tx, y + hh + 3))
        self.drawn.add('marker')

    def _draw_arcs(self, surf, world):
        if not self.arcs:
            return
        p = world.player
        for fx, fy, t0 in self.arcs:
            age = self.t - t0
            if age > ARC_LIFE:
                continue
            rel = core.wrap_angle(math.atan2(fy - p.y, fx - p.x) - p.angle)
            bucket = int(round(math.degrees(rel) / ARC_BUCKET_DEG)) % (360 // ARC_BUCKET_DEG)
            s, pos = _arc_sprite(bucket)
            k = 1.0 - age / ARC_LIFE
            s.set_alpha(int(255 * min(1.0, k * 1.6)))
            surf.blit(s, pos)
        self.drawn.add('arcs')

    def _draw_hitmarker(self, surf):
        if self.hit is None:
            return
        kind, t0 = self.hit
        ln, life, wd = HITMARKS[kind]
        if self.t - t0 > life:
            return
        g = HIT_GAP
        line = pygame.draw.line
        col = C.COL_CRIT if kind == 'kill' else WHITE
        for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            a = (CX + sx * g, CY + sy * g)
            b = (CX + sx * (g + ln), CY + sy * (g + ln))
            line(surf, col, a, b, wd)
            if kind == 'crit':
                line(surf, C.COL_CRIT, (CX + sx * (g + ln - 5), CY + sy * (g + ln - 5)), b, wd)
        self.drawn.add('hit_' + kind)

    def _draw_minimap(self, surf, world, d):
        ox, oy = MINI_RECT[0], MINI_RECT[1]
        c = MINI_CELL
        surf.blit(_minimap_bg(), (ox, oy))
        circle = pygame.draw.circle
        for pk in world.packs:
            if pk.active:
                circle(surf, PACK_DOT, (ox + int(pk.x * c), oy + int(pk.y * c)), 2)
        ob = self._objective(d)
        if ob is not None:
            circle(surf, OBJ_COLORS.get(ob.state, OBJ_COLORS['neutral']),
                   (ox + int(ob.x * c), oy + int(ob.y * c)), max(2, int(ob.radius * c)), 1)
        for ef in world.effects:
            ring = getattr(ef, 'minimap_ring', None)     # (x, y, r, colour) or None (Heal Field)
            if ring:
                rx, ry, rr, rcol = ring
                circle(surf, rcol, (ox + int(rx * c), oy + int(ry * c)), max(2, int(rr * c)), 1)
        for e in world.enemies:
            if not e.alive:
                continue
            col = C.COL_ELITE if getattr(e, 'elite', False) else KIND_COLORS.get(e.KIND, C.COL_ENEMY)
            circle(surf, col, (ox + int(e.x * c), oy + int(e.y * c)), 4 if getattr(e, 'BOSS', False) else 2)
        p = world.player
        px = ox + p.x * c
        py = oy + p.y * c
        a = p.angle
        cos, sin = math.cos, math.sin
        line = pygame.draw.line
        for da in (-C.HALF_FOV, C.HALF_FOV):          # view wedge
            line(surf, (70, 90, 120), (px, py), (px + cos(a + da) * 16, py + sin(a + da) * 16))
        pygame.draw.polygon(surf, WHITE, [(px + cos(a) * 6, py + sin(a) * 6),
                                          (px + cos(a + 2.5) * 4, py + sin(a + 2.5) * 4),
                                          (px + cos(a - 2.5) * 4, py + sin(a - 2.5) * 4)])
        self.drawn.add('minimap')

    def _draw_score(self, surf, world, d):
        _shadow_text(surf, '%s %06d' % (theme.WORDS['score'], world.score), 'm', WHITE, SCORE_POS)
        st = max(1, int(getattr(d, 'stage', 1)))
        _shadow_text(surf, 'x%d MULT' % st, 's', STAGE_COLORS[min(st - 1, len(STAGE_COLORS) - 1)], MULT_POS)

    def _draw_boss_bar(self, surf, d):
        boss = getattr(d, 'boss', None)
        if boss is None or not boss.alive:
            return False
        pl = boss.pool
        x, y, w, h = BOSS_RECT
        _shadow_text(surf, getattr(boss, 'NAME', 'BOSS'), 's', KIND_COLORS['warden'], BOSS_NAME_POS)
        num = core.text('%d / %d' % (math.ceil(pl.total - 1e-9), math.ceil(pl.max_total - 1e-9)), 'xs', MUTED)
        surf.blit(num, (x + w - num.get_width(), BOSS_NAME_POS[1] + 4))
        imgs = bar_images((pl.max_health, pl.max_armor, pl.max_shields), w, h, HP_UNIT, 2, 4)
        surf.fill(SHADOW, (x - 2, y - 2, w + 4, h + 4))
        draw_bar(surf, x, y, imgs, {'health': pl.health, 'armor': pl.armor, 'shields': pl.shields})
        self.drawn.add('boss_bar')
        return True

    def _draw_wave_text(self, surf, d, boss_up):
        if getattr(d, 'wave', 0) <= 0:
            return
        _shadow_center(surf, '%s %d  |  WAVE %d/%d' % (theme.WORDS['stage'], d.stage, d.wave_in_stage,
                                                       C.WAVES_PER_STAGE), 'm', WHITE, STAGE_Y)
        if boss_up or d.state == 'intermission':
            return
        lab = str(d.label or '')
        if d.state == 'active' and d.kind != 'capture':
            lab += ' - %d LEFT' % d.remaining
        elif d.state == 'cleared':
            lab = 'WAVE CLEAR'
        if lab:
            _shadow_center(surf, lab, 's', (220, 225, 235), WAVE_LABEL_Y)

    def _draw_objective_widget(self, surf, d, dy=0):
        ob = self._objective(d)
        if ob is None:
            return
        st = ob.state if ob.state in OBJ_COLORS else 'neutral'
        col = OBJ_COLORS[st]
        cx, cy = OBJ_CENTER[0], OBJ_CENTER[1] + dy
        bg = _obj_bg()
        surf.blit(bg, (cx - bg.get_width() // 2, cy - bg.get_height() // 2))
        prog = 1.0 if st == 'captured' else core.clamp(float(getattr(ob, 'progress', 0.0)), 0.0, 1.0)
        if prog > 0.001:
            if prog >= 0.999:
                pts = ring_poly(cx, cy, OBJ_R, OBJ_R - OBJ_W, 0.0, 0.999, OBJ_STEPS)
            else:
                pts = ring_poly(cx, cy, OBJ_R, OBJ_R - OBJ_W, 0.0, prog, OBJ_STEPS)
            pygame.draw.polygon(surf, col, pts)
        if st == 'contested' and int(self.t * 4) % 2 == 0:
            pygame.draw.circle(surf, col, (cx, cy), OBJ_R + 3, 2)
        a = core.text('A', 'm', col)
        surf.blit(a, (cx - a.get_width() // 2, cy - a.get_height() // 2))
        if st not in ('captured', 'failed'):
            if st == 'overtime':
                if int(self.t * 3) % 2 == 0:
                    _shadow_text(surf, 'OT', 's', col, (OBJ_TIMER_POS[0], OBJ_TIMER_POS[1] + dy))
            else:
                tl = max(0, int(math.ceil(float(getattr(ob, 'time_left', 0.0)) - 1e-9)))
                _shadow_text(surf, '%d:%02d' % (tl // 60, tl % 60), 's', WHITE,
                             (OBJ_TIMER_POS[0], OBJ_TIMER_POS[1] + dy))
        lab = OBJ_LABELS[st]
        if st in ('capturing', 'overtime'):
            lab = '%s %d%%' % (lab, int(prog * 100))
        _shadow_center(surf, lab, 's', col, OBJ_LABEL_Y + dy)
        self.drawn.add('objective')
        self.drawn.add('objective:' + st)

    def _draw_feed(self, surf):
        if not self.feed:
            return
        t = self.t
        n = len(self.feed)
        for i, (s, t0) in enumerate(reversed(self.feed)):     # newest on top
            age = t - t0
            left = FEED_LIFE - age
            if left < 0:
                continue
            s.set_alpha(None if left >= FEED_FADE else int(255 * left / FEED_FADE))
            surf.blit(s, (FEED_RIGHT - s.get_width(), FEED_Y + FEED_STEP * i))
        self.drawn.add('feed')
        self.drawn.add('feed_rows:%d' % n)

    def _draw_banner(self, surf):
        if self.banner is None:
            return
        lines, t0, life = self.banner
        age = self.t - t0
        # wipe in from the centre, wipe out at the end (cached text can't be alpha-faded)
        k = min(1.0, age / BANNER_WIPE, max(0.0, (life - age) / BANNER_WIPE))
        if k <= 0:
            return
        surfs = [core.text(s, size, col) for s, size, col in lines]
        hgt = sum(x.get_height() for x in surfs) + 6 * (len(surfs) - 1)
        wmax = max(x.get_width() for x in surfs)
        half = int((wmax // 2 + 40) * k)
        top = BANNER_Y - surfs[0].get_height() // 2
        band = pygame.Rect(CX - half, top - 8, 2 * half, hgt + 16)
        surf.fill((90, 90, 90), band, pygame.BLEND_RGB_MULT)
        surf.fill(theme.PALETTE['accent'], (band.x, band.y, band.w, 2))
        surf.fill(theme.PALETTE['accent'], (band.x, band.bottom - 2, band.w, 2))
        old = surf.get_clip()
        surf.set_clip(band)
        y = top
        for x in surfs:
            surf.blit(x, (CX - x.get_width() // 2, y))
            y += x.get_height() + 6
        surf.set_clip(old)
        self.drawn.add('banner')

    def _draw_popups(self, surf):
        if not self.popups:
            return
        t = self.t
        for i, (s, t0) in enumerate(self.popups[:POPUP_MAX]):
            age = t - t0
            if age > POPUP_LIFE:
                continue
            left = POPUP_LIFE - age
            s.set_alpha(None if left > 0.4 else int(255 * left / 0.4))
            rise = int(8 * max(0.0, 1.0 - age / 0.12))          # small pop upward on arrival
            surf.blit(s, (CX - s.get_width() // 2, POPUP_Y + POPUP_STEP * i + rise))
        self.drawn.add('popups')
        self.drawn.add('popup_rows:%d' % min(POPUP_MAX, len(self.popups)))

    def _draw_prompt(self, surf, hs):
        if self.prompt is None:
            if hs.max_ammo > 0 and hs.ammo == 0 and not hs.reloading:
                _shadow_center(surf, 'R - RELOAD', 's', (255, 220, 0), RELOAD_HINT_Y)
            return
        kind, text, t0, life = self.prompt
        if kind == 'ready':
            col = C.COL_ULT if int((self.t - t0) * 4) % 2 == 0 else WHITE
        else:
            col = C.COL_ULT
        _shadow_center(surf, text, 'l', col, PROMPT_Y - 17)
        self.drawn.add('prompt_' + kind)

    def _draw_hero_panel(self, surf, p, hs, low):
        cls = type(p)
        surf.blit(_hero_plate(cls), (8, 656))
        x, y, w, h = HP_RECT
        imgs = bar_images((hs.max_health, hs.max_armor, hs.max_shields), w, h)
        cur = {'health': hs.health, 'armor': hs.armor, 'shields': hs.shields}
        draw_bar(surf, x, y, imgs, cur, self.ghost)
        tot = int(math.ceil(hs.health + hs.armor + hs.shields - 1e-9))
        mtot = int(math.ceil(hs.max_health + hs.max_armor + hs.max_shields - 1e-9))
        t1 = _shadow_text(surf, str(max(0, tot)), 'l', C.COL_CRIT if low else WHITE, HP_NUM_POS)
        t2 = core.text(' / %d' % mtot, 's', MUTED)
        surf.blit(t2, (HP_NUM_POS[0] + t1.get_width(), HP_NUM_POS[1] + t1.get_height() - t2.get_height() - 4))
        i = 0
        for key, label, col in STATUS_CHIPS:
            if key in hs.statuses:
                surf.blit(_chip(label, col), (CHIP_POS[0], CHIP_POS[1] + CHIP_STEP * i))
                i += 1
        self.drawn.add('hero_panel')

    def _draw_ult_ring(self, surf, hs):
        cx, cy = ULT_CENTER
        bg = _ult_bg()
        surf.blit(bg, (cx - bg.get_width() // 2, cy - bg.get_height() // 2))
        ro, ri = ULT_R, ULT_R - ULT_W
        if hs.ult_active_frac > 0:
            f = hs.ult_active_frac
            pygame.draw.polygon(surf, WHITE, ring_poly(cx, cy, ro, ri, 0.0, min(0.999, f)))
            t = core.text(hs.name[:1], 'l', WHITE)
            surf.blit(t, (cx - t.get_width() // 2, cy - t.get_height() // 2))
            self.drawn.add('ult_active')
            return
        if hs.ult_ready:
            pulse = 0.5 + 0.5 * math.sin(self.t * _TAU * 2.0)      # 2 Hz
            pygame.draw.polygon(surf, C.COL_ULT, ring_poly(cx, cy, ro, ri, 0.0, 0.999))
            gr = ro + 3 + int(4 * pulse)
            pygame.draw.circle(surf, C.COL_ULT, (cx, cy), gr, 2)
            t = core.text('Q', 'l', C.COL_ULT if pulse > 0.5 else WHITE)
            surf.blit(t, (cx - t.get_width() // 2, cy - t.get_height() // 2))
            self.drawn.add('ult_ready')
            return
        f = hs.ult_frac
        if f > 0.002:
            pygame.draw.polygon(surf, C.COL_ULT, ring_poly(cx, cy, ro, ri, 0.0, f))
        t = core.text('%d%%' % int(f * 100), 'm', C.COL_ULT)
        surf.blit(t, (cx - t.get_width() // 2, cy - t.get_height() // 2))

    def _draw_tiles(self, surf, p, hs):
        abil = hs.abilities
        n = len(abil)
        if not n:
            return
        cls = type(p)
        x0 = TILE_RIGHT - n * TILE - (n - 1) * TILE_GAP
        t = self.t
        for i, a in enumerate(abil):
            x = x0 + i * (TILE + TILE_GAP)
            r = pygame.Rect(x, TILE_Y, TILE, TILE)
            cooling = a.charges <= 0 and a.cd_left > 0
            grey = cooling or not a.usable
            surf.blit(icon(cls, a.slot, TILE, grey), r)
            if cooling:
                f = core.clamp(a.cd_frac, 0.0, 1.0)
                if f > 0.001:
                    sc = _scratch(i)
                    sc.fill((0, 0, 0, 0))
                    h = TILE // 2
                    pts = [(h, h)] + [(h + math.cos(-math.pi / 2 + _TAU * (1.0 - f + f * k / 24)) * 40,
                                       h + math.sin(-math.pi / 2 + _TAU * (1.0 - f + f * k / 24)) * 40)
                                      for k in range(25)]
                    pygame.draw.polygon(sc, (0, 0, 0, 170), pts)
                    surf.blit(sc, r)
                num = core.text(str(int(math.ceil(a.cd_left - 1e-9))), 'm', WHITE)
                surf.blit(num, (r.centerx - num.get_width() // 2, r.centery - num.get_height() // 2))
            if a.meter is not None:
                m = core.clamp(float(a.meter), 0.0, 1.0)
                surf.fill((20, 24, 32), (x + 3, TILE_Y + TILE - 7, TILE - 6, 4))
                surf.fill((120, 200, 255) if m > 0.3 else (255, 150, 60),
                          (x + 3, TILE_Y + TILE - 7, int((TILE - 6) * m), 4))
            if a.active:
                pygame.draw.rect(surf, hs.color, r, 2)
            ft = self.flash.get(a.slot)
            if ft is not None and t - ft < TILE_FLASH:
                pygame.draw.rect(surf, WHITE, r.inflate(4, 4), 2)
            if a.max_charges > 1:
                tw = a.max_charges * PIP + (a.max_charges - 1) * PIP_GAP
                px = r.centerx - tw // 2
                for k in range(a.max_charges):
                    rx = px + k * (PIP + PIP_GAP)
                    if k < a.charges:
                        surf.fill(WHITE, (rx, PIP_Y, PIP, PIP))
                    else:
                        surf.fill((60, 64, 76), (rx, PIP_Y, PIP, PIP))
                        if k == a.charges and a.cd_left > 0:
                            ph = int(PIP * (1.0 - a.cd_frac))
                            if ph > 0:
                                surf.fill(C.COL_ULT, (rx, PIP_Y + PIP - ph, PIP, ph))
            kt = core.text(a.key, 'xs', (200, 205, 215))
            surf.blit(kt, (r.centerx - kt.get_width() // 2, KEY_Y))
        self.drawn.add('tiles')

    def _draw_ammo(self, surf, hs):
        plate = _plate(136, 88, 150, 14)
        surf.blit(plate, (AMMO_RIGHT + 8 - plate.get_width(), AMMO_Y - 8))
        if hs.max_ammo > 0:
            fr = hs.ammo / float(hs.max_ammo)
            col = WHITE if fr > 0.25 else ((255, 220, 0) if fr > 0.10 else (255, 70, 60))
            t2 = core.text(' / %d' % hs.max_ammo, 's', MUTED)
            t1 = core.text(str(hs.ammo), 'xl', col)
            x = AMMO_RIGHT - t2.get_width()
            surf.blit(t2, (x, AMMO_Y + t1.get_height() - t2.get_height() - 12))
            surf.blit(core.text(str(hs.ammo), 'xl', SHADOW), (x - t1.get_width() + 2, AMMO_Y + 2))
            surf.blit(t1, (x - t1.get_width(), AMMO_Y))
            if hs.reloading:
                rx, ry, rw, rh = RELOAD_RECT
                surf.fill((40, 40, 50), RELOAD_RECT)
                surf.fill((255, 220, 0), (rx, ry, int(rw * core.clamp(hs.reload_frac, 0.0, 1.0)), rh))
                self.drawn.add('reload')
        else:
            t = core.text('MELEE', 'l', WHITE)
            _shadow_text(surf, 'MELEE', 'l', WHITE, (AMMO_RIGHT - t.get_width(), AMMO_Y + 8))
        self.drawn.add('ammo')


def _draw_skull(surf, x, y, col):
    """Tiny code-drawn skull (crit tag in the kill feed), 12x14."""
    pygame.draw.circle(surf, col, (x + 6, y + 5), 5)
    surf.fill(col, (x + 3, y + 8, 7, 5))
    surf.fill((14, 18, 28), (x + 3, y + 4, 2, 3))
    surf.fill((14, 18, 28), (x + 8, y + 4, 2, 3))
    surf.fill((14, 18, 28), (x + 5, y + 11, 1, 2))
    surf.fill((14, 18, 28), (x + 7, y + 11, 1, 2))
