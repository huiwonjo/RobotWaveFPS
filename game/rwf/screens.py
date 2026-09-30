"""Screens and overlays (spec 6.1, 6.2). HUD_UX owns this file.

Constructors (7.4): TitleScreen(); HeroSelectScreen(default_key); CountdownOverlay(seconds);
PauseOverlay(world, stats, frame); IntermissionOverlay(world); EndBanner(victory); PotgScreen(highlight);
SummaryScreen(world, stats, hero_key).
Action strings: 'start' | 'lock:<key>' | 'done' | 'resume' | 'end_match' | 'swap:<key>' | 'skip' | 'again'
| 'select'.

Layout constants sit at the top of each class. Static layers (backgrounds, cards, panels, the summary
page) are drawn ONCE into cached surfaces (module-level `_cache`, panels keyed by (w, h, accent)); per
frame only small dynamic parts are drawn. Screens have no world bus, so 'ui' sounds use sfx.play directly.
Session settings for the pause panel: sfx.muted and core.SETTINGS['sens'].
"""
import math

import pygame

from . import config as C
from . import core
from . import render
from . import sfx
from . import stats as stats_mod
from . import theme

W, H = C.W, C.H
CX = W // 2
PAL = theme.PALETTE
ACCENT = PAL['accent']
ACCENT2 = PAL['accent2']
TEXT = PAL['text']
MUTED = PAL['muted']
INK = PAL['ink']
EDGE = PAL['edge']
GOLD = (255, 210, 60)
RED = (255, 80, 70)
KEY_COL = (255, 220, 0)
WHITE_T = (255, 255, 255)
_cache = {}


# ============================ shared helpers =================================
def _grid_bg():
    s = _cache.get('grid')
    if s is None:
        s = pygame.Surface((W, H))
        img = theme.backdrop((W, H))
        if img is not None:
            s.blit(img, (0, 0))
            s.fill((110, 110, 110), special_flags=pygame.BLEND_RGB_MULT)
        else:
            s.fill(PAL.get('bg', (10, 10, 20)))
            g = PAL.get('grid', (20, 20, 35))
            for i in range(0, W, 60):
                s.fill(g, (i, 0, 1, H))
            for i in range(0, H, 60):
                s.fill(g, (0, i, W, 1))
            for i in range(0, 180, 3):          # soft glow band behind the title area
                k = 1.0 - i / 180.0
                s.fill((int(10 * k), int(14 * k), int(26 * k)), (0, i, W, 3), pygame.BLEND_RGB_ADD)
        _cache['grid'] = s
    return s


def _dim():
    s = _cache.get('dim')
    if s is None:
        s = pygame.Surface((W, H))
        s.fill((0, 0, 0))
        s.set_alpha(128)
        _cache['dim'] = s
    return s


def panel(w, h, accent=None, alpha=215):
    """Panel surface cached per (w, h, accent, alpha): dark ink body, thin edge, accent strip on top."""
    key = ('panel', w, h, accent, alpha)
    s = _cache.get(key)
    if s is None:
        s = pygame.Surface((w, h), pygame.SRCALPHA)
        s.fill(INK + (alpha,))
        pygame.draw.rect(s, EDGE, s.get_rect(), 1)
        if accent is not None:
            s.fill(accent, (0, 0, w, 3))
        _cache[key] = s
    return s


def _band(w, h, color, slant=40, alpha=225):
    """Slanted band (parallelogram) cached per size/colour, used by the end banner and POTG."""
    key = ('band', w, h, color, slant, alpha)
    s = _cache.get(key)
    if s is None:
        s = pygame.Surface((w + slant, h), pygame.SRCALPHA)
        pygame.draw.polygon(s, INK + (alpha,), [(slant, 0), (w + slant, 0), (w, h), (0, h)])
        pygame.draw.polygon(s, color, [(slant, 0), (w + slant, 0), (w + slant - 2, 5), (slant - 2, 5)])
        pygame.draw.polygon(s, color, [(2, h - 5), (w + 2, h - 5), (w, h), (0, h)])
        _cache[key] = s
    return s


def _text_at(surf, s, size, color, pos, shadow=True):
    t = core.text(s, size, color)
    if shadow:
        surf.blit(core.text(s, size, (0, 0, 0)), (pos[0] + 2, pos[1] + 2))
    surf.blit(t, pos)
    return t


def _center(surf, s, y, size='m', color=(255, 255, 255), x=CX, shadow=True):
    t = core.text(s, size, color)
    return _text_at(surf, s, size, color, (x - t.get_width() // 2, y), shadow)


def _right(surf, s, y, size, color, x_right, shadow=False):
    t = core.text(s, size, color)
    return _text_at(surf, s, size, color, (x_right - t.get_width(), y), shadow)


def _fit(s, size, max_w):
    """Trim a string with '...' so it renders within max_w px (measured with font.size, not rendered)."""
    s = str(s)
    f = core.font(size)
    if f.size(s)[0] <= max_w:
        return s
    while len(s) > 1 and f.size(s + '...')[0] > max_w:
        s = s[:-1]
    return s.rstrip() + '...'


def _action(ev):
    if ev.type == pygame.KEYDOWN:
        return C.KEYMAP.get(ev.key)
    return None


def _confirm(ev):
    return ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)


def _click(ev):
    return ev.type == pygame.MOUSEBUTTONDOWN and getattr(ev, 'button', 0) == 1


def _portrait(cls, size):
    key = ('portrait', cls.KEY, size)
    s = _cache.get(key)
    if s is None:
        s = pygame.Surface((size, size))
        s.fill((24, 28, 38))
        try:
            cls.draw_icon('portrait', s, s.get_rect())
        except Exception:
            t = core.text(cls.NAME[:1], 'l', cls.COLOR)
            s.blit(t, (size // 2 - t.get_width() // 2, size // 2 - t.get_height() // 2))
        _cache[key] = s
    return s


def _star(surf, cx, cy, r, color, filled):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    pygame.draw.polygon(surf, color, pts, 0 if filled else 1)


def pool_bar(surf, x, y, w, h, maxes, cur=None, unit=25.0, gap=2):
    """Static pool bar split into `unit`-HP segments coloured by pool type (select card, summary)."""
    n = sum(int(math.ceil(m / unit - 1e-9)) for m in maxes if m > 0) or 1
    sw = max(2, w // n - gap)
    xx = x
    cur = cur or maxes
    for kind, m, c in zip(('health', 'armor', 'shields'), maxes, cur):
        k = int(math.ceil(m / unit - 1e-9)) if m > 0 else 0
        for i in range(k):
            full = c >= (i + 1) * unit - 1e-6 or c >= m - 1e-6
            surf.fill(C.POOL_COLORS[kind] if full else C.COL_MISSING, (xx, y, sw, h))
            xx += sw + gap


def _rank_rows():
    out = []
    for letter, thr, col in C.RANKS[:-1]:
        out.append(('%s %d' % (letter, thr), col))
    return out


class Screen:
    def handle(self, ev, inp):
        return None

    def update(self, real_dt):
        return None

    def draw(self, surf):
        pass


# ============================ TITLE ==========================================
class TitleScreen(Screen):
    TITLE_Y = 64
    SUB_Y = 150
    HEROES_BOX = pygame.Rect(212, 196, 600, 186)
    RULES_BOX = pygame.Rect(212, 398, 600, 206)
    PLAY_Y = 628
    HINT_Y = 722

    def __init__(self):
        self.t = 0.0

    def handle(self, ev, inp):
        if _click(ev) or _confirm(ev):
            sfx.play('ui')
            return 'start'
        return None

    def update(self, real_dt):
        self.t += real_dt
        return None

    def _static(self):
        s = _cache.get('title')
        if s is None:
            s = _grid_bg().copy()
            _center(s, theme.TITLE, self.TITLE_Y, 'xl', ACCENT)
            _center(s, theme.SUBTITLE, self.SUB_Y, 'm', TEXT)
            b = self.HEROES_BOX
            s.blit(panel(b.w, b.h, ACCENT2), b)
            keys = [k for k in core.HERO_ORDER if k in core.HEROES]
            for i, k in enumerate(keys):
                cls = core.HEROES[k]
                cx = b.x + b.w * (i + 1) // (len(keys) + 1)
                p = _portrait(cls, 96)
                s.blit(p, (cx - 48, b.y + 18))
                pygame.draw.rect(s, cls.COLOR, (cx - 50, b.y + 16, 100, 100), 2)
                _center(s, cls.NAME, b.y + 124, 's', cls.COLOR, x=cx)
                _center(s, '%s  %s' % (cls.ROLE, '*' * int(cls.DIFFICULTY)), b.y + 152, 'xs', MUTED, x=cx,
                        shadow=False)
            r = self.RULES_BOX
            s.blit(panel(r.w, r.h, ACCENT), r)
            rules = ('5 WAVES = 1 STAGE', 'WAVE 3: CAPTURE', 'WAVE 5: BOSS', 'CLEAR STAGE 3 FOR VICTORY')
            for i, line in enumerate(rules):
                _center(s, line, r.y + 16 + i * 34, 's', TEXT, shadow=False)
            rows = _rank_rows()
            parts = [core.text('RANK', 's', MUTED)] + [core.text(t, 's', col) for t, col in rows]
            tw = sum(p.get_width() for p in parts) + 24 * (len(parts) - 1)
            x = CX - tw // 2
            for p in parts:
                s.blit(p, (x, r.y + 16 + 4 * 34 + 8))
                x += p.get_width() + 24
            _center(s, 'WASD MOVE   MOUSE AIM   LMB FIRE   RMB/F ALT   SHIFT/SPACE   E   Q ULT   V MELEE   '
                       'R RELOAD   ESC/P PAUSE   M MUTE', self.HINT_Y, 'xs', MUTED, shadow=False)
            _cache['title'] = s
        return s

    def draw(self, surf):
        surf.blit(self._static(), (0, 0))
        if int(self.t * 2) % 2 == 0:
            _center(surf, 'CLICK TO PLAY', self.PLAY_Y, 'l', WHITE_T)


# ============================ HERO SELECT ====================================
class HeroSelectScreen(Screen):
    CARD_X = (44, 362, 680)
    CARD_Y = 150
    CARD_W, CARD_H = 300, 440
    BUTTON = pygame.Rect(CX - 120, 640 - 28, 240, 56)
    HEADER_Y = 40
    BLURB_Y = 104
    HINT_Y = 690
    FLASH = 0.15

    def __init__(self, default_key='vector'):
        keys = [k for k in core.HERO_ORDER if k in core.HEROES]
        self.keys = keys
        self.sel = keys.index(default_key) if default_key in keys else 0
        self.flash = 0.0
        self.locking = None
        self.t = 0.0

    def _lock(self):
        if self.locking is None:
            self.locking = self.keys[self.sel]
            self.flash = self.FLASH
            sfx.play('ui')
        return None

    def _select(self, i):
        if 0 <= i < len(self.keys) and i != self.sel:
            self.sel = i
            sfx.play('ui', 0.6)

    def handle(self, ev, inp):
        if self.locking is not None:
            return None
        a = _action(ev)
        if a in ('hero1', 'hero2', 'hero3'):
            self._select(int(a[-1]) - 1)
        elif a == 'left':
            self._select((self.sel - 1) % len(self.keys))
        elif a == 'right':
            self._select((self.sel + 1) % len(self.keys))
        elif _confirm(ev):
            return self._lock()
        if _click(ev):
            pos = getattr(ev, 'pos', (0, 0))
            if self.BUTTON.collidepoint(pos):
                return self._lock()
            for i, x in enumerate(self.CARD_X[:len(self.keys)]):
                if pygame.Rect(x, self.CARD_Y, self.CARD_W, self.CARD_H).collidepoint(pos):
                    if i == self.sel:
                        return self._lock()
                    self._select(i)
        return None

    def update(self, real_dt):
        self.t += real_dt
        if self.locking is not None:
            self.flash -= real_dt
            if self.flash <= 0:
                self.flash = 0.0
                return 'lock:' + self.locking      # after the 0.15 s lock-in flash has been shown
        return None

    def _card(self, k, selected):
        key = ('card', k, selected)
        s = _cache.get(key)
        if s is not None:
            return s
        cls = core.HEROES[k]
        cw, ch = self.CARD_W, self.CARD_H
        s = pygame.Surface((cw, ch))
        s.fill(INK if selected else (16, 20, 30))
        s.fill(cls.COLOR, (0, 0, cw, 6))
        s.blit(_portrait(cls, 96), (cw // 2 - 48, 16))
        pygame.draw.rect(s, cls.COLOR, (cw // 2 - 50, 14, 100, 100), 2)
        _center(s, cls.NAME, 118, 'l', cls.COLOR, x=cw // 2)
        role = core.text(cls.ROLE, 's', MUTED)
        rx = cw // 2 - (role.get_width() + 10 + 3 * 20) // 2
        s.blit(role, (rx, 166))
        for i in range(3):
            _star(s, rx + role.get_width() + 18 + i * 20, 176, 8, KEY_COL, i < int(cls.DIFFICULTY))
        maxes = (float(cls.HEALTH), float(cls.ARMOR), float(cls.SHIELDS))
        pool_bar(s, 20, 198, cw - 40, 12, maxes)
        parts = ['%d HEALTH' % cls.HEALTH]
        if cls.ARMOR:
            parts.append('%d ARMOR' % cls.ARMOR)
        if cls.SHIELDS:
            parts.append('%d SHIELDS' % cls.SHIELDS)
        _center(s, '  +  '.join(parts), 214, 'xs', MUTED, x=cw // 2, shadow=False)
        for j, row in enumerate(tuple(cls.KIT)[:5]):
            y = 240 + j * 39
            s.blit(core.text(str(row[0]), 'xs', KEY_COL), (16, y))
            s.blit(core.text(_fit(row[1], 'xs', cw - 94), 'xs', WHITE_T), (84, y))
            if len(row) > 2 and row[2]:
                s.blit(core.text(_fit(row[2], 'xs', cw - 94), 'xs', MUTED), (84, y + 17))
        if selected:
            pygame.draw.rect(s, cls.COLOR, s.get_rect(), 3)
        else:
            pygame.draw.rect(s, EDGE, s.get_rect(), 1)
            s.fill((150, 150, 150), special_flags=pygame.BLEND_RGB_MULT)
        _cache[key] = s
        return s

    def _static(self):
        s = _cache.get('select_bg')
        if s is None:
            s = _grid_bg().copy()
            _center(s, 'CHOOSE YOUR HERO', self.HEADER_Y, 'l', WHITE_T)
            _center(s, '1 / 2 / 3 OR ARROWS TO PICK   -   ENTER OR CLICK TO LOCK IN', self.HINT_Y, 'xs', MUTED,
                    shadow=False)
            _cache['select_bg'] = s
        return s

    def draw(self, surf):
        surf.blit(self._static(), (0, 0))
        cls = core.HEROES[self.keys[self.sel]]
        _center(surf, cls.BLURB or cls.ROLE, self.BLURB_Y, 's', cls.COLOR)
        for i, k in enumerate(self.keys):
            surf.blit(self._card(k, i == self.sel), (self.CARD_X[i], self.CARD_Y))
        b = self.BUTTON
        pulse = 0.5 + 0.5 * math.sin(self.t * 4.0)
        surf.fill((int(40 + 30 * pulse), int(34 + 26 * pulse), 0), b)
        pygame.draw.rect(surf, KEY_COL, b, 2)
        t = core.text('LOCK IN', 'm', KEY_COL)
        surf.blit(t, (b.centerx - t.get_width() // 2, b.centery - t.get_height() // 2))
        if self.flash > 0:
            v = int(255 * self.flash / self.FLASH)
            surf.fill((v, v, v), None, pygame.BLEND_RGB_ADD)


# ============================ COUNTDOWN ======================================
class CountdownOverlay(Screen):
    TEXT_Y = 230
    BAND = (0, 214, W, 150)

    def __init__(self, seconds=C.COUNTDOWN):
        self.left = float(seconds)
        self._shown = None

    def update(self, real_dt):
        self.left -= real_dt
        n = max(1, int(self.left + 0.999))
        if n != self._shown:
            self._shown = n
            sfx.play('beep', 0.7)
        return 'done' if self.left <= 0 else None

    def draw(self, surf):
        surf.fill((110, 110, 110), self.BAND, pygame.BLEND_RGB_MULT)
        _center(surf, 'MATCH STARTS IN %d' % max(1, int(self.left + 0.999)), self.TEXT_Y, 'xl', WHITE_T)
        if core.pointer_locked() is False:
            _center(surf, 'CLICK TO LOCK MOUSE', self.TEXT_Y + 86, 'm', KEY_COL)
        else:
            _center(surf, 'GET READY', self.TEXT_Y + 90, 's', MUTED)


# ============================ PAUSE ==========================================
class PauseOverlay(Screen):
    TITLE_Y = 96
    LEFT = pygame.Rect(152, 200, 350, 206)
    RIGHT = pygame.Rect(522, 200, 350, 206)
    KIT = pygame.Rect(152, 426, 720, 230)

    def __init__(self, world, stats, frame):
        self.world = world
        self.stats = stats
        self.frame = frame
        self._bg_ready = False

    def handle(self, ev, inp):
        if _click(ev):
            return 'resume'
        if _action(ev) == 'end_match':
            return 'end_match'
        return None

    def _background(self):
        """The frozen frame and the 50% black layer, composed once per pause into a reused surface."""
        s = _cache.get('pause_bg')
        if s is None:
            s = pygame.Surface((W, H))
            _cache['pause_bg'] = s
        if not self._bg_ready:
            if self.frame is not None:
                s.blit(self.frame, (0, 0))
            else:
                s.fill((0, 0, 0))
            s.blit(_dim(), (0, 0))
            self._bg_ready = True
        return s

    def draw(self, surf):
        surf.blit(self._background(), (0, 0))
        _center(surf, 'PAUSED', self.TITLE_Y, 'xl', WHITE_T)
        l = self.LEFT
        surf.blit(panel(l.w, l.h, ACCENT2), l)
        _text_at(surf, 'CONTROLS', 's', ACCENT2, (l.x + 16, l.y + 12), False)
        rows = (('CLICK TO RESUME', KEY_COL), ('X - END MATCH', TEXT),
                ('M - MUTE (%s)' % ('ON' if sfx.muted else 'OFF'), TEXT),
                ('[ ] - SENS %.1fx' % core.SETTINGS.get('sens', 1.0), TEXT))
        for i, (txt, col) in enumerate(rows):
            _text_at(surf, txt, 'm' if i == 0 else 's', col, (l.x + 16, l.y + 48 + i * 38), False)
        r = self.RIGHT
        surf.blit(panel(r.w, r.h, ACCENT), r)
        _text_at(surf, 'MATCH STATS', 's', ACCENT, (r.x + 16, r.y + 12), False)
        st = self.stats
        live = st.live_rows() if st is not None and hasattr(st, 'live_rows') else []
        for i, (label, val) in enumerate(live):
            y = r.y + 50 + i * 36
            _text_at(surf, label, 's', MUTED, (r.x + 16, y + 4), False)
            _right(surf, val, y, 'm', WHITE_T, r.right - 16)
        k = self.KIT
        surf.blit(panel(k.w, k.h, None), k)
        cls = type(self.world.player)
        _text_at(surf, '%s  -  %s' % (cls.NAME, cls.ROLE), 's', cls.COLOR, (k.x + 16, k.y + 12), False)
        for j, row in enumerate(tuple(cls.KIT)[:5]):
            y = k.y + 48 + j * 34
            _text_at(surf, str(row[0]), 's', KEY_COL, (k.x + 16, y), False)
            _text_at(surf, str(row[1]), 's', WHITE_T, (k.x + 110, y), False)
            if len(row) > 2 and row[2]:
                _text_at(surf, _fit(row[2], 'xs', k.w - 346), 'xs', MUTED, (k.x + 330, y + 3), False)


# ============================ INTERMISSION ===================================
class IntermissionOverlay(Screen):
    PANEL = pygame.Rect(CX - 300, 120, 600, 260)
    CHIP_W, CHIP_H, CHIP_GAP = 164, 34, 14

    def __init__(self, world):
        self.world = world
        self.t = 0.0

    def handle(self, ev, inp):
        a = _action(ev)
        if a in ('hero1', 'hero2', 'hero3'):
            i = int(a[-1]) - 1
            if i < len(core.HERO_ORDER):
                key = core.HERO_ORDER[i]
                if key in core.HEROES and key != self.world.player.KEY:
                    sfx.play('ui')
                return 'swap:' + key
        if _confirm(ev) or _click(ev):
            return 'skip'
        return None

    def update(self, real_dt):
        self.t += real_dt
        return None

    def draw(self, surf):
        w = self.world
        d = w.director
        p = self.PANEL
        surf.blit(panel(p.w, p.h, ACCENT), p)
        stage_col = (255, 140, 0), (0, 210, 240), (180, 80, 255), (255, 80, 80), (255, 220, 0)
        if w.victory and d.stage == C.VICTORY_STAGE:
            _center(surf, 'VICTORY!', p.y + 8, 'xl', GOLD)
            _center(surf, 'ENDLESS MODE CONTINUES', p.y + 74, 's', TEXT)
        else:
            _center(surf, '%s %d CLEAR' % (theme.WORDS['stage'], d.stage), p.y + 12, 'xl',
                    stage_col[min(max(d.stage, 1) - 1, 4)])
        st = stats_mod.stats_for(w)
        elims = st.elims if st is not None else 0
        _center(surf, '%s %d      ELIMS %d' % (theme.WORDS['score'], w.score, elims), p.y + 98, 'm', WHITE_T)
        _center(surf, 'NEXT %s IN %.1fs' % (theme.WORDS['stage'], max(0.0, d.intermission_left)), p.y + 136, 's',
                MUTED, shadow=False)
        keys = [k for k in core.HERO_ORDER if k in core.HEROES]
        tw = len(keys) * self.CHIP_W + (len(keys) - 1) * self.CHIP_GAP
        x = CX - tw // 2
        y = p.y + 166
        cur = w.player.KEY
        for i, k in enumerate(keys):
            cls = core.HEROES[k]
            r = pygame.Rect(x + i * (self.CHIP_W + self.CHIP_GAP), y, self.CHIP_W, self.CHIP_H)
            on = k == cur
            surf.fill(cls.COLOR if on else (30, 36, 50), r)
            pygame.draw.rect(surf, cls.COLOR, r, 2)
            t = core.text('%d  %s' % (i + 1, cls.NAME), 's', INK if on else cls.COLOR)
            surf.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))
        _center(surf, 'PRESS 1/2/3 TO SWAP (KEEP 30% ULT)', p.y + 210, 'xs', KEY_COL, shadow=False)
        _center(surf, 'ENTER / SPACE / CLICK - SKIP', p.y + 232, 'xs', MUTED, shadow=False)


# ============================ END BANNER =====================================
class EndBanner(Screen):
    BAND_Y = 300
    BAND_H = 120
    SLIDE = 0.25
    SKIP_AFTER = 0.6

    def __init__(self, victory):
        self.victory = bool(victory)
        self.left = C.END_BANNER_TIME
        self.age = 0.0

    def handle(self, ev, inp):
        if self.age >= self.SKIP_AFTER and (_confirm(ev) or _click(ev)):
            return 'skip'
        return None

    def update(self, real_dt):
        self.left -= real_dt
        self.age += real_dt
        return 'done' if self.left <= 0 else None

    def draw(self, surf):
        col = GOLD if self.victory else RED
        band = _band(W, self.BAND_H, col)
        k = min(1.0, self.age / self.SLIDE)
        x = int((1.0 - k) * -W) - 20
        surf.fill((120, 120, 120), (0, self.BAND_Y - 20, W, self.BAND_H + 40), pygame.BLEND_RGB_MULT)
        surf.blit(band, (x, self.BAND_Y))
        if k >= 1.0:
            word = 'VICTORY' if self.victory else 'DEFEAT'
            th = core.text(word, 'xl', col).get_height()
            _center(surf, word, self.BAND_Y + (self.BAND_H - th) // 2 + 2, 'xl', col)


# ============================ PLAY OF THE GAME ===============================
class PotgScreen(Screen):
    """Replays the highlight's Scenes through render.draw_scene at 20 Hz real time (no viewmodel, no
    HUD). A red hitmarker flashes on kill frames. Any key or click skips. With no frames, or with
    highlight['static'] True, or if a replay draw fails, it shows the static card over the last frame."""
    RATE = 20.0
    MIN_SHOW = 2.5          # seconds on screen at least (short clips hold their last frame)
    STATIC_SHOW = 3.0
    BAND_Y = 18
    BAND_H = 96
    KILL_FLASH = 3          # frames

    def __init__(self, highlight):
        self.hl = highlight or {}
        self.frames = list(self.hl.get('frames') or [])
        self.kill_frames = set(self.hl.get('kill_frames') or ())
        self.static = bool(self.hl.get('static')) or not self.frames
        self.i = 0
        self.acc = 0.0
        self.age = 0.0
        self._card = None
        key = self.hl.get('hero')
        cls = core.HEROES.get(key) if key else None
        self.name = self.hl.get('name') or (cls.NAME if cls is not None else str(key or '').upper())
        self.color = cls.COLOR if cls is not None else ACCENT2
        n = int(self.hl.get('kills', 0) or 0)
        span = float(self.hl.get('span', 0.0) or 0.0)
        if n <= 1:
            self.sub = '%d ELIM' % n
        else:
            self.sub = '%d ELIMS IN %.1fs' % (n, span)

    def handle(self, ev, inp):
        if ev.type == pygame.KEYDOWN or _click(ev):
            return 'skip'
        return None

    def update(self, real_dt):
        self.age += real_dt
        if self.static:
            return 'done' if self.age >= self.STATIC_SHOW else None
        self.acc += real_dt
        step = 1.0 / self.RATE
        while self.acc >= step:
            self.acc -= step
            self.i += 1
        n = len(self.frames)
        if self.i >= n and self.age >= max(self.MIN_SHOW, n * step):
            return 'done'
        return None

    def _banner(self, surf):
        b = _band(W - 120, self.BAND_H, GOLD, 40, 215)
        surf.blit(b, (40, self.BAND_Y))
        _center(surf, 'PLAY OF THE GAME', self.BAND_Y + 8, 'l', GOLD)
        t1 = core.text(self.name, 'm', self.color)
        t2 = core.text('  -  ' + self.sub, 'm', WHITE_T)
        x = CX - (t1.get_width() + t2.get_width()) // 2
        y = self.BAND_Y + 56
        surf.blit(t1, (x, y))
        surf.blit(t2, (x + t1.get_width(), y))

    def _static_card(self, surf):
        s = self._card
        if s is None:
            s = _cache.get('potg_card')
            if s is None:
                s = pygame.Surface((W, H))
                _cache['potg_card'] = s
            s.blit(_grid_bg(), (0, 0))
            if self.frames:
                try:
                    render.draw_scene(s, self.frames[-1])
                except Exception:
                    pass
            s.fill((150, 150, 150), special_flags=pygame.BLEND_RGB_MULT)
            self._card = s
        surf.blit(s, (0, 0))

    def draw(self, surf):
        if self.static:
            self._static_card(surf)
        else:
            idx = min(self.i, len(self.frames) - 1)
            try:
                render.draw_scene(surf, self.frames[idx])
            except Exception:
                self.static = True
                self._static_card(surf)
            if not self.static:
                surf.fill((255, 255, 255), (CX - 1, H // 2 - 1, 3, 3))
                if any(0 <= idx - k < self.KILL_FLASH for k in self.kill_frames):
                    line = pygame.draw.line
                    for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                        line(surf, C.COL_CRIT, (CX + sx * 8, H // 2 + sy * 8), (CX + sx * 26, H // 2 + sy * 26), 3)
                n = len(self.frames)
                surf.fill((40, 40, 50), (40, H - 16, W - 80, 4))
                surf.fill(GOLD, (40, H - 16, int((W - 80) * min(1.0, (idx + 1) / float(n))), 4))
        self._banner(surf)
        _center(surf, 'ANY KEY - SKIP', H - 42, 'xs', MUTED)


# ============================ SUMMARY ========================================
class SummaryScreen(Screen):
    HEADER_Y = 18
    HERO_POS = (72, 104)
    LEFT_X, LEFT_R = 72, 480
    ROWS_Y = 222
    ROW_STEP = 34
    MEDAL_X = 540
    MEDAL_Y = 118
    MEDAL_STEP = 76
    MEDAL_R = 26
    BOTTOM_Y = 588
    FOOTER_Y = 720
    INPUT_GUARD = 0.35

    def __init__(self, world, stats, hero_key):
        self.world = world
        self.stats = stats
        self.hero_key = hero_key
        self.age = 0.0
        self._built = False

    def handle(self, ev, inp):
        if self.age < self.INPUT_GUARD:
            return None
        if _click(ev) or (ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER)):
            sfx.play('ui')
            return 'again'
        if _action(ev) == 'hero_select':
            sfx.play('ui')
            return 'select'
        return None

    def update(self, real_dt):
        self.age += real_dt
        return None

    def _page(self):
        s = _cache.get('summary')
        if s is None:
            s = pygame.Surface((W, H))
            _cache['summary'] = s
        if self._built:
            return s
        self._built = True
        w = self.world
        st = self.stats
        s.blit(_grid_bg(), (0, 0))
        win = bool(getattr(w, 'victory', False))
        _center(s, 'VICTORY' if win else 'DEFEAT', self.HEADER_Y, 'xl', GOLD if win else RED)
        cls = core.HEROES.get(self.hero_key)
        hx, hy = self.HERO_POS
        if cls is not None:
            s.blit(_portrait(cls, 96), (hx, hy))
            pygame.draw.rect(s, cls.COLOR, (hx - 2, hy - 2, 100, 100), 2)
            _text_at(s, cls.NAME, 'l', cls.COLOR, (hx + 112, hy + 8))
            d = getattr(w, 'director', None)
            reached = getattr(st, 'stage_reached', getattr(d, 'stage', 1)) if st is not None else 1
            _text_at(s, '%s  -  %s %d' % (cls.ROLE, theme.WORDS['stage'], reached), 's', MUTED,
                     (hx + 114, hy + 58), False)
        # left column: stats
        s.blit(panel(self.LEFT_R - self.LEFT_X + 24, 10 * self.ROW_STEP + 20, ACCENT2),
               (self.LEFT_X - 12, self.ROWS_Y - 12))
        rows = st.rows() if st is not None and hasattr(st, 'rows') else []
        for i, (label, val) in enumerate(rows):
            y = self.ROWS_Y + i * self.ROW_STEP
            _text_at(s, label, 's', MUTED, (self.LEFT_X, y + 4), False)
            _right(s, val, y, 'm', WHITE_T, self.LEFT_R)
        # right column: medals
        _text_at(s, 'MEDALS', 's', GOLD, (self.MEDAL_X, self.MEDAL_Y - 30), False)
        medals = st.medals() if st is not None and hasattr(st, 'medals') else []
        for i, (name, tier, val) in enumerate(medals[:stats_mod.MAX_MEDALS]):
            y = self.MEDAL_Y + i * self.MEDAL_STEP
            col = stats_mod.TIER_COLORS.get(tier, MUTED)
            cx, cy = self.MEDAL_X + self.MEDAL_R, y + self.MEDAL_R + 4
            pygame.draw.circle(s, (0, 0, 0), (cx + 2, cy + 3), self.MEDAL_R)
            pygame.draw.circle(s, col, (cx, cy), self.MEDAL_R)
            pygame.draw.circle(s, WHITE_T, (cx, cy), self.MEDAL_R, 2)
            t = core.text(tier[:1].upper(), 'm', INK)
            s.blit(t, (cx - t.get_width() // 2, cy - t.get_height() // 2))
            _text_at(s, name, 's', col, (cx + 40, y + 6), False)
            _text_at(s, val, 'm', WHITE_T, (cx + 40, y + 28), False)
        if not medals:
            _text_at(s, 'NO MEDALS THIS MATCH', 's', MUTED, (self.MEDAL_X, self.MEDAL_Y + 10), False)
        # bottom: score and rank
        score = int(getattr(w, 'score', 0))
        letter, rcol = st.rank(score) if st is not None else ('D', MUTED)
        s.blit(panel(560, 110, rcol), (CX - 280, self.BOTTOM_Y))
        _text_at(s, '%s' % theme.WORDS['score'], 's', MUTED, (CX - 250, self.BOTTOM_Y + 22), False)
        _text_at(s, '%06d' % score, 'l', WHITE_T, (CX - 250, self.BOTTOM_Y + 46))
        _text_at(s, 'RANK', 's', MUTED, (CX + 70, self.BOTTOM_Y + 38), False)
        _text_at(s, letter, 'xl', rcol, (CX + 150, self.BOTTOM_Y + 16))
        _center(s, 'ENTER / CLICK - PLAY AGAIN    H - HERO SELECT', self.FOOTER_Y, 's', TEXT)
        return s

    def draw(self, surf):
        surf.blit(self._page(), (0, 0))
