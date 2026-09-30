"""In-match HUD (HUD_UX owns this file). Phase 0 STUB by FOUNDATION.

A port of the original HUD reduced to the spec 6.3 geometry: cached minimap,
score, stage/wave, health segments, HP numbers, ult %, plain ability tiles,
ammo/reload and a body/crit/kill hitmarker. Everything cached; no per-frame
surface allocation.
"""
import math

import pygame

from . import config as C
from . import core
from . import theme
from .world import MAP_H, MAP_W, WALL_GRID

MINI = (12, 12, 140, 140)
MINI_CELL = 7
STAGE_COLORS = ((255, 140, 0), (0, 210, 240), (180, 80, 255), (255, 80, 80), (255, 220, 0))
KIND_COLORS = {'trooper': (230, 70, 60), 'slicer': (255, 120, 120), 'detonator': (255, 170, 40),
               'eradicator': (120, 150, 255), 'warden': (220, 80, 255), 'dummy': (200, 200, 200)}


class HUD:
    def __init__(self, world):
        self.world = world
        self._mini = None
        self._icons = {}
        self._hit_t = -9.0
        self._hit_kind = 'body'
        world.bus.on('damage', self._on_damage)

    def _on_damage(self, d):
        if d['source'] is self.world.player and not d['to_player']:
            self._hit_t = core.real_time()
            self._hit_kind = 'kill' if d['killed'] else ('crit' if d['crit'] else 'body')

    def update(self, world, real_dt):
        pass

    # --- pieces --------------------------------------------------------------------
    def _minimap_bg(self):
        if self._mini is None:
            s = pygame.Surface((MINI[2], MINI[3]))
            s.fill((14, 18, 26))
            for y in range(MAP_H):
                for x in range(MAP_W):
                    if WALL_GRID[y][x]:
                        s.fill((110, 104, 96), (x * MINI_CELL, y * MINI_CELL, MINI_CELL, MINI_CELL))
            self._mini = s
        return self._mini

    def _icon(self, cls, slot):
        k = (cls.KEY, slot)
        s = self._icons.get(k)
        if s is None:
            s = pygame.Surface((52, 52))
            s.fill((24, 28, 38))
            cls.draw_icon(slot, s, s.get_rect())
            self._icons[k] = s
        return s

    def _draw_minimap(self, surf, world):
        ox, oy = MINI[0], MINI[1]
        surf.blit(self._minimap_bg(), (ox, oy))
        c = MINI_CELL
        circle = pygame.draw.circle
        for pk in world.packs:
            if pk.active:
                circle(surf, (60, 220, 90), (ox + int(pk.x * c), oy + int(pk.y * c)), 2)
        for e in world.enemies:
            if not e.alive:
                continue
            col = C.COL_ELITE if e.elite else KIND_COLORS.get(e.KIND, C.COL_ENEMY)
            circle(surf, col, (ox + int(e.x * c), oy + int(e.y * c)), 4 if e.BOSS else 2)
        p = world.player
        px = ox + p.x * c
        py = oy + p.y * c
        a = p.angle
        pts = [(px + math.cos(a) * 6, py + math.sin(a) * 6),
               (px + math.cos(a + 2.5) * 4, py + math.sin(a + 2.5) * 4),
               (px + math.cos(a - 2.5) * 4, py + math.sin(a - 2.5) * 4)]
        pygame.draw.polygon(surf, (255, 255, 255), pts)

    def _draw_health(self, surf, hs):
        x, y, w, h = 104, 694, 280, 18
        segs = []
        for kind, cur, mx in (('health', hs.health, hs.max_health), ('armor', hs.armor, hs.max_armor),
                              ('shields', hs.shields, hs.max_shields)):
            n = int(math.ceil(mx / 25.0 - 1e-9))
            for i in range(n):
                segs.append((C.POOL_COLORS[kind], core.clamp((cur - i * 25.0) / 25.0, 0.0, 1.0)))
        if not segs:
            return
        sw = max(4, w // len(segs) - 2)
        fill = surf.fill
        for i, (col, frac) in enumerate(segs):
            sx = x + i * (sw + 2)
            fill(C.COL_MISSING, (sx, y, sw, h))
            if frac > 0:
                fill(col, (sx, y, max(1, int(sw * frac)), h))
        total = int(math.ceil(hs.health + hs.armor + hs.shields - 1e-9))
        mtot = int(math.ceil(hs.max_health + hs.max_armor + hs.max_shields - 1e-9))
        t1 = core.text(str(total), 'l')
        surf.blit(t1, (x, 716))
        surf.blit(core.text(' / %d' % mtot, 's', (180, 185, 200)), (x + t1.get_width(), 730))

    def _draw_tiles(self, surf, world, hs):
        abil = hs.abilities
        n = len(abil)
        x0 = 872 - n * 52 - (n - 1) * 8
        cls = type(world.player)
        for i, a in enumerate(abil):
            x = x0 + i * 60
            r = pygame.Rect(x, 684, 52, 52)
            surf.blit(self._icon(cls, a.slot), r)
            if a.cd_left > 0 and a.charges == 0:
                surf.fill((90, 90, 90), r, pygame.BLEND_RGB_MULT)
                t = core.text(str(int(math.ceil(a.cd_left))), 'm')
                surf.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))
            if a.active:
                pygame.draw.rect(surf, hs.color, r, 2)
            if a.max_charges > 1:
                for k in range(a.max_charges):
                    surf.fill((255, 255, 255) if k < a.charges else (70, 70, 80), (x + k * 9, 676, 6, 6))
            if a.meter is not None:
                surf.fill((40, 40, 50), (x + 3, 730, 46, 4))
                surf.fill((120, 200, 255), (x + 3, 730, int(46 * core.clamp(a.meter, 0, 1)), 4))
            t = core.text(a.key, 'xs', (200, 205, 215))
            surf.blit(t, (r.centerx - t.get_width() // 2, 738))

    def _draw_hitmarker(self, surf):
        age = core.real_time() - self._hit_t
        k = self._hit_kind
        life = {'body': 0.12, 'crit': 0.18, 'kill': 0.30}[k]
        if age > life:
            return
        ln = {'body': 10, 'crit': 14, 'kill': 18}[k]
        col = (255, 60, 40) if k == 'kill' else (255, 255, 255)
        cx, cy = C.W // 2, C.H // 2
        g = 8
        line = pygame.draw.line
        for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            line(surf, col, (cx + sx * g, cy + sy * g), (cx + sx * (g + ln), cy + sy * (g + ln)), 2)

    # --- frame -----------------------------------------------------------------------
    def draw(self, surf, world):
        p = world.player
        hs = p.hud_state(world)
        d = world.director
        self._draw_minimap(surf, world)
        surf.blit(core.text('%s %06d' % (theme.WORDS['score'], world.score), 'm'), (12, 158))
        surf.blit(core.text('x%d MULT' % max(1, d.stage), 's', STAGE_COLORS[min(d.stage - 1, 4)]), (12, 184))
        if d.wave > 0:
            t = core.text('%s %d  |  WAVE %d/%d' % (theme.WORDS['stage'], d.stage, d.wave_in_stage,
                                                   C.WAVES_PER_STAGE), 'm')
            surf.blit(t, (C.W // 2 - t.get_width() // 2, 10))
            lab = d.label + (' - %d LEFT' % d.remaining if d.kind == 'assault' and d.state == 'active' else '')
            t = core.text(lab, 's', (220, 225, 235))
            surf.blit(t, (C.W // 2 - t.get_width() // 2, 38))
        p.draw_crosshair(surf, world)
        self._draw_hitmarker(surf)
        surf.blit(core.text(hs.name, 'm', hs.color), (104, 668))
        self._draw_health(surf, hs)
        pct = 'Q' if hs.ult_ready else '%d%%' % int(hs.ult_frac * 100)
        pygame.draw.circle(surf, C.COL_ULT if hs.ult_ready else (90, 90, 100), (512, 700), 38, 6)
        t = core.text(pct, 'm', C.COL_ULT)
        surf.blit(t, (512 - t.get_width() // 2, 700 - t.get_height() // 2))
        self._draw_tiles(surf, world, hs)
        if hs.max_ammo > 0:
            col = (255, 255, 255) if hs.ammo > hs.max_ammo * 0.25 else (
                (255, 220, 0) if hs.ammo > hs.max_ammo * 0.10 else (255, 70, 60))
            t2 = core.text(' / %d' % hs.max_ammo, 's', (180, 185, 200))
            t1 = core.text(str(hs.ammo), 'xl', col)
            x = 1004 - t2.get_width()
            surf.blit(t2, (x, 720))
            surf.blit(t1, (x - t1.get_width(), 682))
            if hs.reloading:
                surf.fill((40, 40, 50), (884, 742, 120, 6))
                surf.fill((255, 220, 0), (884, 742, int(120 * hs.reload_frac), 6))
        else:
            t = core.text('MELEE', 'l')
            surf.blit(t, (1004 - t.get_width(), 690))
