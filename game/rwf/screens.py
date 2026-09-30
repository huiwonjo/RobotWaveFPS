"""Screens and overlays (HUD_UX owns this file). Phase 0 STUB by FOUNDATION.

Plain-text versions of every Screen class with the final constructors and
action strings: 'start' | 'lock:<key>' | 'done' | 'resume' | 'end_match' |
'swap:<key>' | 'skip' | 'again' | 'select'. Static layers are cached.
"""
import pygame

from . import config as C
from . import core
from . import render
from . import theme

W, H = C.W, C.H
_cache = {}


def _grid_bg():
    s = _cache.get('grid')
    if s is None:
        s = pygame.Surface((W, H))
        s.fill(theme.PALETTE.get('bg', (10, 10, 20)))
        g = theme.PALETTE.get('grid', (20, 20, 35))
        for i in range(0, W, 60):
            s.fill(g, (i, 0, 1, H))
        for i in range(0, H, 60):
            s.fill(g, (0, i, W, 1))
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


def _center(surf, s, y, size='m', color=(255, 255, 255)):
    t = core.text(s, size, color)
    surf.blit(t, (W // 2 - t.get_width() // 2, y))
    return t


def _action(ev):
    if ev.type == pygame.KEYDOWN:
        return C.KEYMAP.get(ev.key)
    return None


def _confirm(ev):
    return ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)


def _click(ev):
    return ev.type == pygame.MOUSEBUTTONDOWN and getattr(ev, 'button', 0) == 1


class Screen:
    def handle(self, ev, inp):
        return None

    def update(self, real_dt):
        return None

    def draw(self, surf):
        pass


class TitleScreen(Screen):
    def handle(self, ev, inp):
        if _click(ev) or _confirm(ev):
            return 'start'
        return None

    def draw(self, surf):
        surf.blit(_grid_bg(), (0, 0))
        _center(surf, theme.TITLE, 70, 'xl', theme.PALETTE['accent'])
        _center(surf, theme.SUBTITLE, 150, 'm')
        names = '   '.join(core.HEROES[k].NAME for k in core.HERO_ORDER if k in core.HEROES)
        _center(surf, names, 230, 'l', theme.PALETTE['accent2'])
        rules = ('5 WAVES = 1 STAGE', 'WAVE 3: CAPTURE', 'WAVE 5: BOSS', 'CLEAR STAGE 3 FOR VICTORY',
                 'RANK  S 5000  A 2000  B 800  C 300')
        for i, r in enumerate(rules):
            _center(surf, r, 320 + i * 34, 's', (200, 205, 220))
        if int(core.real_time() * 2) % 2 == 0:
            _center(surf, 'CLICK TO PLAY', 640, 'l')


class HeroSelectScreen(Screen):
    CARD_X = (44, 362, 680)
    CARD_Y = 150
    CARD_W, CARD_H = 300, 440
    BUTTON = pygame.Rect(W // 2 - 120, 640 - 28, 240, 56)

    def __init__(self, default_key='vector'):
        keys = [k for k in core.HERO_ORDER if k in core.HEROES]
        self.keys = keys
        self.sel = keys.index(default_key) if default_key in keys else 0
        self.flash = 0.0

    def _lock(self):
        self.flash = 0.15
        return 'lock:' + self.keys[self.sel]

    def handle(self, ev, inp):
        a = _action(ev)
        if a in ('hero1', 'hero2', 'hero3'):
            i = int(a[-1]) - 1
            if i < len(self.keys):
                self.sel = i
        elif a == 'left':
            self.sel = (self.sel - 1) % len(self.keys)
        elif a == 'right':
            self.sel = (self.sel + 1) % len(self.keys)
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
                    self.sel = i
        return None

    def update(self, real_dt):
        self.flash = max(0.0, self.flash - real_dt)
        return None

    def draw(self, surf):
        surf.blit(_grid_bg(), (0, 0))
        _center(surf, 'CHOOSE YOUR HERO', 60, 'l')
        for i, k in enumerate(self.keys):
            cls = core.HEROES[k]
            x = self.CARD_X[i]
            r = pygame.Rect(x, self.CARD_Y, self.CARD_W, self.CARD_H)
            surf.fill((22, 26, 40), r)
            pygame.draw.rect(surf, cls.COLOR if i == self.sel else (60, 70, 100), r, 3 if i == self.sel else 1)
            cls.draw_icon('portrait', surf, pygame.Rect(x + 102, self.CARD_Y + 16, 96, 96))
            t = core.text(cls.NAME, 'l', cls.COLOR)
            surf.blit(t, (r.centerx - t.get_width() // 2, self.CARD_Y + 120))
            t = core.text('%s  %s' % (cls.ROLE, '*' * cls.DIFFICULTY), 's', (200, 205, 220))
            surf.blit(t, (r.centerx - t.get_width() // 2, self.CARD_Y + 166))
            t = core.text('HP %d' % (cls.HEALTH + cls.ARMOR + cls.SHIELDS), 's')
            surf.blit(t, (r.centerx - t.get_width() // 2, self.CARD_Y + 192))
            for j, row in enumerate(cls.KIT[:5]):
                surf.blit(core.text(row[0], 'xs', (255, 220, 0)), (x + 16, self.CARD_Y + 236 + j * 36))
                surf.blit(core.text(row[1], 'xs'), (x + 96, self.CARD_Y + 236 + j * 36))
        pygame.draw.rect(surf, (255, 220, 0), self.BUTTON, 2)
        t = core.text('LOCK IN', 'm', (255, 220, 0))
        surf.blit(t, (self.BUTTON.centerx - t.get_width() // 2, self.BUTTON.centery - t.get_height() // 2))
        if self.flash > 0:
            v = int(255 * self.flash / 0.15)
            surf.fill((v, v, v), None, pygame.BLEND_RGB_ADD)


class CountdownOverlay(Screen):
    def __init__(self, seconds=C.COUNTDOWN):
        self.left = float(seconds)

    def update(self, real_dt):
        self.left -= real_dt
        return 'done' if self.left <= 0 else None

    def draw(self, surf):
        _center(surf, 'MATCH STARTS IN %d' % max(1, int(self.left + 0.999)), 230, 'xl')
        if core.pointer_locked() is False:
            _center(surf, 'CLICK TO LOCK MOUSE', 320, 'm', (255, 220, 0))


class PauseOverlay(Screen):
    def __init__(self, world, stats, frame):
        self.world = world
        self.stats = stats
        self.frame = frame

    def handle(self, ev, inp):
        if _click(ev):
            return 'resume'
        if _action(ev) == 'end_match':
            return 'end_match'
        return None

    def draw(self, surf):
        if self.frame is not None:
            surf.blit(self.frame, (0, 0))
        surf.blit(_dim(), (0, 0))
        _center(surf, 'PAUSED', 150, 'xl')
        _center(surf, 'CLICK TO RESUME', 240, 'm')
        _center(surf, 'X - END MATCH', 276, 's')
        _center(surf, 'M - MUTE', 302, 's')
        _center(surf, '[ ] - SENS', 328, 's')
        st = self.stats
        _center(surf, 'ELIMS %d   DAMAGE %d   TIME %ds' % (st.elims, st.damage, st.time_played), 380, 's')
        cls = type(self.world.player)
        for j, row in enumerate(cls.KIT[:5]):
            _center(surf, '%s  %s' % (row[0], row[1]), 430 + j * 26, 'xs', (200, 205, 220))


class IntermissionOverlay(Screen):
    def __init__(self, world):
        self.world = world

    def handle(self, ev, inp):
        a = _action(ev)
        if a in ('hero1', 'hero2', 'hero3'):
            i = int(a[-1]) - 1
            if i < len(core.HERO_ORDER):
                return 'swap:' + core.HERO_ORDER[i]
        if _confirm(ev):
            return 'skip'
        return None

    def draw(self, surf):
        w = self.world
        d = w.director
        if w.victory and d.stage == C.VICTORY_STAGE:
            _center(surf, 'VICTORY!', 130, 'xl', (255, 220, 0))
            _center(surf, 'ENDLESS MODE CONTINUES', 200, 's')
        else:
            _center(surf, '%s %d CLEAR' % (theme.WORDS['stage'], d.stage), 130, 'xl', theme.PALETTE['accent'])
        _center(surf, '%s %d' % (theme.WORDS['score'], w.score), 230, 'm')
        _center(surf, 'NEXT %s IN %.1fs' % (theme.WORDS['stage'], d.intermission_left), 262, 's')
        names = '  '.join('%d %s' % (i + 1, core.HEROES[k].NAME) for i, k in enumerate(core.HERO_ORDER)
                          if k in core.HEROES)
        _center(surf, names, 300, 's', (255, 220, 0))
        _center(surf, 'PRESS 1/2/3 TO SWAP (KEEP 30% ULT)', 326, 'xs')


class EndBanner(Screen):
    def __init__(self, victory):
        self.victory = bool(victory)
        self.left = C.END_BANNER_TIME

    def update(self, real_dt):
        self.left -= real_dt
        return 'done' if self.left <= 0 else None

    def draw(self, surf):
        surf.fill((60, 60, 60), (0, 300, W, 120), pygame.BLEND_RGB_MULT)
        _center(surf, 'VICTORY' if self.victory else 'DEFEAT', 322, 'xl',
                (255, 220, 0) if self.victory else (255, 80, 70))


class PotgScreen(Screen):
    def __init__(self, highlight):
        self.hl = highlight or {}
        self.frames = list(self.hl.get('frames') or [])
        self.i = 0
        self.acc = 0.0

    def handle(self, ev, inp):
        if ev.type == pygame.KEYDOWN or _click(ev):
            return 'skip'
        return None

    def update(self, real_dt):
        self.acc += real_dt
        while self.acc >= 0.05:
            self.acc -= 0.05
            self.i += 1
        return 'done' if self.i >= len(self.frames) else None

    def draw(self, surf):
        if self.frames:
            render.draw_scene(surf, self.frames[min(self.i, len(self.frames) - 1)])
        surf.fill((60, 60, 60), (0, 20, W, 90), pygame.BLEND_RGB_MULT)
        _center(surf, 'PLAY OF THE GAME', 26, 'l', (255, 220, 0))
        _center(surf, '%s  -  %d ELIMS IN %.1fs' % (str(self.hl.get('hero', '')).upper(), self.hl.get('kills', 0),
                                                  self.hl.get('span', 0.0)), 72, 's')


class SummaryScreen(Screen):
    def __init__(self, world, stats, hero_key):
        self.world = world
        self.stats = stats
        self.hero_key = hero_key

    def handle(self, ev, inp):
        if _click(ev) or (ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER)):
            return 'again'
        if _action(ev) == 'hero_select':
            return 'select'
        return None

    def draw(self, surf):
        surf.blit(_grid_bg(), (0, 0))
        w = self.world
        st = self.stats
        _center(surf, 'VICTORY' if w.victory else 'DEFEAT', 40, 'xl', (255, 220, 0) if w.victory else (255, 80, 70))
        cls = core.HEROES.get(self.hero_key)
        if cls is not None:
            _center(surf, cls.NAME, 130, 'l', cls.COLOR)
        rows = ('ELIMINATIONS %d' % st.elims, 'DAMAGE DONE %d' % st.damage, 'SHOTS %d  HITS %d' % (st.shots, st.hits),
                'WAVES CLEARED %d' % st.waves_cleared, 'TIME PLAYED %ds' % st.time_played)
        for i, r in enumerate(rows):
            _center(surf, r, 200 + i * 34, 's')
        letter, col = st.rank(w.score)
        _center(surf, '%s %d' % (theme.WORDS['score'], w.score), 420, 'l')
        _center(surf, 'RANK %s' % letter, 480, 'xl', col)
        _center(surf, 'ENTER / CLICK - PLAY AGAIN    H - HERO SELECT', 640, 's')
