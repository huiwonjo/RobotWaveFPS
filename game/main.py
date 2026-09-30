import pygame
import sys
import math
import time
import random
import asyncio
from pathlib import Path

# -- Settings ----------------------------------------------------------------
W, H = 1024, 768
COLS = 320
FOV = math.pi / 3
HALF_FOV = FOV / 2
MAX_DEPTH = 20

# -- Map ---------------------------------------------------------------------
RAW_MAP = [
    "11111111111111111111",
    "10000000010000000001",
    "10111011110001110101",
    "10100010001000100101",
    "10101110001110101101",
    "10000000000000000001",
    "11011011011101101101",
    "10000000000000000001",
    "10111101000010111101",
    "10000001000010000001",
    "10000001000010000001",
    "10111101000010111101",
    "10000000000000000001",
    "11011011011101101101",
    "10000000000000000001",
    "10101110001110101101",
    "10100010001000100101",
    "10111011110001110101",
    "10000000010000000001",
    "11111111111111111111",
]
MAP_W = len(RAW_MAP[0])
MAP_H = len(RAW_MAP)

OPEN_CELLS = [
    (x + 0.5, y + 0.5)
    for y in range(MAP_H) for x in range(MAP_W)
    if RAW_MAP[y][x] == '0'
]

def is_wall(x, y):
    mx, my = int(x), int(y)
    if 0 <= mx < MAP_W and 0 <= my < MAP_H:
        return RAW_MAP[my][mx] == '1'
    return True

# -- Colors / fonts ----------------------------------------------------------
WHITE  = (235, 241, 237)
BLACK  = (0, 0, 0)
GRAY   = (100, 100, 100)
DGRAY  = (25, 25, 35)
RED    = (220, 60, 60)
GREEN  = (119, 222, 181)
YELLOW = (239, 201, 132)
ORANGE = (244, 144, 94)
CYAN   = (110, 226, 217)
SKY    = (8, 17, 29)
FLOOR  = (15, 23, 30)
INK = (9, 19, 28)
MUTED = (139, 165, 173)
EDGE = (58, 86, 91)
GOLD = (236, 193, 119)
RANK_COLORS = {"normal": CYAN, "elite": ORANGE, "boss": (204, 164, 238)}
ASSET_DIR = Path(__file__).resolve().parent / "assets"

pygame.init()
_KR = next((str(p) for p in (ASSET_DIR / "NotoSansKR.ttf", ASSET_DIR / "MalgunGothic.ttf") if p.exists()), None)
if _KR is None and sys.platform != "emscripten":
    _KR = pygame.font.match_font("malgungothic,nanumgothic,notosanscjkkr")
FONT_XS = pygame.font.Font(_KR, 12 if _KR else 18)
FONT_S  = pygame.font.Font(_KR, 15 if _KR else 22)
FONT_M  = pygame.font.Font(_KR, 20 if _KR else 28)
FONT_L  = pygame.font.Font(_KR, 33 if _KR else 46)
FONT_XL = pygame.font.Font(_KR, 53 if _KR else 74)
FONT_NUM = pygame.font.Font(None, 52)
FONT_HERO = pygame.font.Font(None, 104)
if _KR:
    for ui_font in (FONT_XS, FONT_S, FONT_M):
        ui_font.set_bold(True)
ASSETS = {}
MENU_BACKDROP = None
SKY_STRIP = None
WORLD_BUFFER = pygame.Surface((COLS, H))
WALL_TEXTURES = []


def tr(korean, english):
    return korean if _KR else english


def label(surf, text, pos, font=FONT_S, color=WHITE, anchor="topleft"):
    rendered = font.render(str(text), True, color)
    rect = rendered.get_rect(**{anchor: pos})
    surf.blit(rendered, rect)
    return rect


def panel(surf, rect, alpha=210, accent=None):
    x, y, width, height = rect
    layer = pygame.Surface((width, height), pygame.SRCALPHA)
    layer.fill((*INK, alpha))
    pygame.draw.rect(layer, (*EDGE, 180), layer.get_rect(), 1, border_radius=3)
    if accent:
        pygame.draw.rect(layer, accent, (0, 0, 3, height))
    surf.blit(layer, (x, y))


def fit_image(image, size):
    ratio = max(size[0] / image.get_width(), size[1] / image.get_height())
    scaled = pygame.transform.smoothscale(image, (int(image.get_width()*ratio), int(image.get_height()*ratio)))
    result = pygame.Surface(size)
    result.blit(scaled, ((size[0]-scaled.get_width())//2, (size[1]-scaled.get_height())//2))
    return result


def load_assets():
    """Assets are bundled beside main.py, so desktop and pygbag share the art."""
    global MENU_BACKDROP, SKY_STRIP
    for name in ("seoul-night", "dokkaebi-normal", "dokkaebi-elite", "dokkaebi-boss"):
        path = ASSET_DIR / (name + ".png")
        if path.exists():
            try:
                loaded = pygame.image.load(str(path)).convert_alpha()
                if name.startswith("dokkaebi-") and loaded.get_height() > 512:
                    loaded = pygame.transform.smoothscale(loaded, (round(loaded.get_width()*512/loaded.get_height()), 512))
                ASSETS[name] = loaded
            except (pygame.error, OSError) as exc:
                print("Unable to load", name, exc)
    if "seoul-night" in ASSETS:
        background = ASSETS["seoul-night"]
        MENU_BACKDROP = fit_image(background, (W, H))
        # Only the skyline is used above the raycast street, keeping geometry readable.
        crop = background.subsurface((0, 0, background.get_width(), max(1, int(background.get_height()*.56))))
        SKY_STRIP = pygame.transform.smoothscale(crop, (COLS*3, H//2+220))
        SKY_STRIP.fill((130, 157, 175), special_flags=pygame.BLEND_RGB_MULT)
    build_wall_textures()


def build_wall_textures():
    """Seoul alley facades: tiled storefronts, shutters, neon and tiled eaves."""
    WALL_TEXTURES.clear()
    shop_names = [tr("종로 상회", "JONGNO"), tr("을지 다방", "EULJI"), tr("서울 야시장", "SEOUL"), tr("청계 공방", "CHEONGGYE")]
    for index in range(4):
        texture = pygame.Surface((128, 256))
        texture.fill([(35, 47, 56), (42, 47, 55), (29, 49, 53), (45, 43, 53)][index])
        for y in range(0, 256, 19):
            pygame.draw.line(texture, (22, 33, 41), (0, y), (127, y))
            offset = 0 if (y//19)%2 == 0 else 24
            for x in range(offset, 128, 48):
                pygame.draw.line(texture, (24, 34, 43), (x, y), (x, y+19))
        pygame.draw.rect(texture, (14, 23, 30), (7, 102, 114, 132))
        for y in range(108, 231, 9):
            pygame.draw.line(texture, (48, 61, 68), (11, y), (116, y))
        neon = [CYAN, ORANGE, GOLD, (193, 153, 225)][index]
        pygame.draw.rect(texture, (11, 27, 34), (4, 56, 120, 40))
        pygame.draw.rect(texture, neon, (4, 56, 120, 40), 2)
        sign = FONT_S.render(shop_names[index], True, neon)
        if sign.get_width() > 108:
            sign = pygame.transform.smoothscale(sign, (108, max(1, int(sign.get_height()*108/sign.get_width()))))
        texture.blit(sign, (64-sign.get_width()//2, 76-sign.get_height()//2))
        pygame.draw.rect(texture, (10, 21, 28), (0, 16, 128, 9))
        pygame.draw.line(texture, (68, 97, 99), (0, 25), (128, 25), 2)
        for x in range(0, 128, 12):
            pygame.draw.line(texture, (76, 101, 104), (x, 15), (x+5, 5), 2)
        pygame.draw.rect(texture, (15, 29, 35), (0, 240, 128, 16))
        pygame.draw.line(texture, (71, 82, 79), (0, 240), (128, 240), 3)
        WALL_TEXTURES.append(texture)

# -- Raycasting --------------------------------------------------------------
def cast_ray(px, py, angle):
    rd_x = math.cos(angle)
    rd_y = math.sin(angle)
    mx, my = int(px), int(py)
    delta_x = abs(1 / rd_x) if rd_x != 0 else 1e30
    delta_y = abs(1 / rd_y) if rd_y != 0 else 1e30

    if rd_x < 0: step_x, sx = -1, (px - mx) * delta_x
    else:         step_x, sx =  1, (mx + 1 - px) * delta_x
    if rd_y < 0: step_y, sy = -1, (py - my) * delta_y
    else:         step_y, sy =  1, (my + 1 - py) * delta_y

    side = 0
    for _ in range(MAX_DEPTH * 4):
        if sx < sy: sx += delta_x; mx += step_x; side = 0
        else:        sy += delta_y; my += step_y; side = 1
        if 0 <= mx < MAP_W and 0 <= my < MAP_H and RAW_MAP[my][mx] == '1':
            break
    else:
        return MAX_DEPTH, side, mx, my

    dist = (mx - px + (1 - step_x) / 2) / rd_x if side == 0 else \
           (my - py + (1 - step_y) / 2) / rd_y
    return max(dist, 0.01), side, mx, my


# -- Dokkaebi / Seoul street renderer ----------------------------------------
def fallback_dokkaebi(rank):
    """A horned silhouette keeps the game usable if an art file is unavailable."""
    sprite = pygame.Surface((96, 160), pygame.SRCALPHA)
    color = RANK_COLORS[rank]
    pygame.draw.ellipse(sprite, (24, 53, 60), (19, 60, 60, 73))
    pygame.draw.circle(sprite, color, (48, 43), 25)
    pygame.draw.polygon(sprite, GOLD, [(27, 30), (22, 2), (41, 23)])
    pygame.draw.polygon(sprite, GOLD, [(59, 23), (77, 2), (70, 32)])
    pygame.draw.line(sprite, WHITE, (32, 42), (43, 46), 4)
    pygame.draw.line(sprite, WHITE, (53, 46), (64, 42), 4)
    pygame.draw.line(sprite, color, (31, 124), (25, 157), 13)
    pygame.draw.line(sprite, color, (64, 124), (72, 157), 13)
    pygame.draw.line(sprite, GOLD, (85, 47), (85, 133), 8)
    return sprite


def draw_occluded(small, sprite, left, top, depth, z_buf):
    """Clip contiguous visible sprite columns against perpendicular wall depth."""
    start = None
    right = left + sprite.get_width()
    for col in range(max(left, 0), min(right, COLS)+1):
        visible = col < min(right, COLS) and z_buf[col] > depth
        if visible and start is None:
            start = col
        elif not visible and start is not None:
            small.blit(sprite, (start, top), (start-left, 0, col-start, sprite.get_height()))
            start = None


def draw_robot_sprite(small, screen_x, sp_h, sp_top, depth, z_buf, robot):
    sprite = ASSETS.get("dokkaebi-" + robot.rank)
    if sprite is None:
        sprite = ASSETS.setdefault("fallback-" + robot.rank, fallback_dokkaebi(robot.rank))
    # The world has 320 horizontal columns but 768 vertical pixels. Compensate
    # before the final 1024px upscale so the source proportions stay correct.
    sp_w = max(2, round(sp_h * sprite.get_width()/sprite.get_height() * COLS/W))
    scaled = pygame.transform.smoothscale(sprite, (sp_w, sp_h))
    shade = int(max(.40, 1-depth/25)*255)
    scaled.fill((shade, shade, shade, 255), special_flags=pygame.BLEND_RGBA_MULT)
    left = screen_x-sp_w//2
    draw_occluded(small, scaled, left, sp_top, depth, z_buf)
    if robot.hp < robot.max_hp and 5 < sp_top < H and 0 <= screen_x < COLS and z_buf[screen_x] > depth:
        bar_w = max(8, sp_w*2//3)
        bar = pygame.Surface((bar_w, 4), pygame.SRCALPHA)
        bar.fill((16, 26, 34, 235))
        pygame.draw.rect(bar, RANK_COLORS[robot.rank], (0, 0, max(1, int(bar_w*robot.hp/robot.max_hp)), 2))
        draw_occluded(small, bar, screen_x-bar_w//2, sp_top-8, depth, z_buf)


def render_world(surf, px, py, angle, pitch, robots, packs):
    small = WORLD_BUFFER
    horizon = H//2 + int(pitch)
    small.fill(SKY)
    if SKY_STRIP:
        offset = int((angle % (2*math.pi))/(2*math.pi) * SKY_STRIP.get_width())
        small.blit(SKY_STRIP, (-offset, horizon-SKY_STRIP.get_height()))
        small.blit(SKY_STRIP, (SKY_STRIP.get_width()-offset, horizon-SKY_STRIP.get_height()))
    for y in range(max(0, horizon), H, 4):
        depth_t = (y-horizon)/max(H-horizon, 1)
        color = (int(13+depth_t*12), int(24+depth_t*12), int(32+depth_t*14))
        pygame.draw.rect(small, color, (0, y, COLS, 4))
    z_buf = []
    if not WALL_TEXTURES:
        build_wall_textures()
    for col in range(COLS):
        ray_angle = angle-HALF_FOV + FOV*(col+.5)/COLS
        dist, side, mx, my = cast_ray(px, py, ray_angle)
        depth = max(dist*math.cos(ray_angle-angle), .01)
        wall_h = min(int(H/depth), H*6)
        top = horizon-wall_h//2
        texture = WALL_TEXTURES[(mx*3+my)%len(WALL_TEXTURES)]
        hit = py+dist*math.sin(ray_angle) if side == 0 else px+dist*math.cos(ray_angle)
        tx = min(texture.get_width()-1, int((hit % 1)*texture.get_width()))
        column = pygame.transform.scale(texture.subsurface((tx, 0, 1, 256)), (1, max(1, wall_h)))
        shade = int(max(.23, 1-depth/22) * (255 if side == 0 else 214))
        column.fill((shade, shade, shade), special_flags=pygame.BLEND_RGB_MULT)
        small.blit(column, (col, top))
        bottom = top+wall_h
        if horizon < bottom < H:
            reflection_h = min(H-bottom, max(2, wall_h//3))
            reflection = pygame.transform.flip(pygame.transform.scale(column, (1, reflection_h)), False, True)
            reflection.fill((45, 64, 76), special_flags=pygame.BLEND_RGB_MULT)
            small.blit(reflection, (col, bottom))
        z_buf.append(depth)

    # Health charms and enemies share one depth-sorted pass for correct layering.
    objects = [(r.x, r.y, r) for r in robots if r.alive]
    objects += [(p.x, p.y, p) for p in packs if p.active]
    objects.sort(key=lambda item: -((item[0]-px)**2+(item[1]-py)**2))
    for ox, oy, obj in objects:
        dx, dy = ox-px, oy-py
        distance = math.hypot(dx, dy)
        if distance < .1 or distance > MAX_DEPTH:
            continue
        relative = (math.atan2(dy, dx)-angle+math.pi) % (2*math.pi)-math.pi
        if abs(relative) > HALF_FOV+.35:
            continue
        depth = max(.1, distance*math.cos(relative))
        screen_x = int((.5+relative/FOV)*COLS)
        wall_h = H/depth
        if isinstance(obj, Robot):
            height_ratio = {"normal": .80, "elite": .88, "boss": 1.02}[obj.rank]
            sp_h = min(int(wall_h*height_ratio), H*3)
            sp_top = int(horizon+wall_h*.5-sp_h)
            draw_robot_sprite(small, screen_x, max(1, sp_h), sp_top, depth, z_buf, obj)
        else:
            sp_h = max(6, min(int(wall_h*.20), H))
            sp_w = max(2, int(sp_h*.62*COLS/W))
            charm = pygame.Surface((sp_w, sp_h), pygame.SRCALPHA)
            charm.fill((*GOLD, 235))
            pygame.draw.line(charm, (124, 50, 33), (sp_w//2, sp_h//5), (sp_w//2, sp_h*4//5), max(1, sp_w//5))
            pygame.draw.line(charm, (124, 50, 33), (sp_w//5, sp_h//2), (sp_w*4//5, sp_h//2), max(1, sp_h//12))
            sp_top = int(horizon+wall_h*.42-sp_h+math.sin(time.time()*2)*3)
            draw_occluded(small, charm, screen_x-sp_w//2, sp_top, depth, z_buf)
    pygame.transform.scale(small, (W, H), surf)


# -- Gun ---------------------------------------------------------------------
def draw_gun(surf, player):
    now = time.time()
    fire_elapsed = now - player.last_shot

    anim_dur = 0.15
    if fire_elapsed < anim_dur:
        t = fire_elapsed / anim_dur
        recoil = int(math.sin(t * math.pi) * 55)
    else:
        recoil = 0

    bob_y = int(math.sin(now * 1.8) * 4)
    bob_x = int(math.sin(now * 0.9) * 2)

    gx = W * 3 // 4 + bob_x
    gy = H - 184 + recoil + bob_y
    lx = W // 4 - 80 - bob_x
    ly = H - 184 + recoil + bob_y

    for (bx, by) in [(gx, gy), (lx, ly)]:
        flip = (bx == lx)
        sign = -1 if flip else 1

        barrel_x = bx - sign * 100
        pygame.draw.rect(surf, (45, 50, 62), (barrel_x if not flip else bx, by + 12, 110, 20))
        pygame.draw.rect(surf, GOLD, (barrel_x if not flip else bx, by + 12, 110, 5))

        body_x = bx - sign * 10
        pygame.draw.rect(surf, (38, 42, 55), (body_x if not flip else bx - 90, by + 6, 95, 60))
        pygame.draw.rect(surf, CYAN, (body_x if not flip else bx - 88, by + 18, 80, 4))
        pygame.draw.rect(surf, (70, 80, 100), (body_x if not flip else bx - 90, by + 6, 95, 60), 1)

        pygame.draw.rect(surf, (30, 33, 42), (bx - sign * 10 + (0 if not flip else -30), by + 60, 32, 70))
        pygame.draw.rect(surf, (50, 55, 70), (bx - sign * 10 + (0 if not flip else -30), by + 60, 32, 70), 1)

        scope_x = bx - sign * 40
        pygame.draw.rect(surf, (55, 60, 75), (scope_x if not flip else bx - 70, by, 35, 14))
        pygame.draw.rect(surf, CYAN, (scope_x + 5 if not flip else bx - 65, by + 3, 25, 6))
        seal_x = bx+12 if not flip else bx-57
        pygame.draw.rect(surf, GOLD, (seal_x, by+29, 17, 29))
        pygame.draw.line(surf, (147, 59, 43), (seal_x+8, by+33), (seal_x+8, by+53), 2)
        pygame.draw.line(surf, (147, 59, 43), (seal_x+3, by+39), (seal_x+13, by+39), 2)

    flash_dur = 0.07
    if fire_elapsed < flash_dur:
        ratio = 1.0 - fire_elapsed / flash_dur
        r = int(30 * ratio)

        for (bx, by) in [(gx, gy), (lx, ly)]:
            flip = (bx == lx)
            mx = (bx - 100) if not flip else (bx + 10)
            my = by + 22

            flash_surf = pygame.Surface((r*4+2, r*4+2), pygame.SRCALPHA)
            pygame.draw.circle(flash_surf, (111, 245, 222, int(220*ratio)), (r*2, r*2), r)
            pygame.draw.circle(flash_surf, (234, 255, 238, int(240*ratio)), (r*2, r*2), r//2)
            surf.blit(flash_surf, (mx - r*2, my - r*2))

            for ang_deg in range(0, 360, 40):
                ang = math.radians(ang_deg)
                ex = mx + int(math.cos(ang) * r * 2.2)
                ey = my + int(math.sin(ang) * r * 2.2)
                pygame.draw.line(surf, CYAN, (mx, my), (ex, ey), max(1, r//6))

        flash_overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        flash_overlay.fill((100, 225, 205, int(24 * ratio)))
        surf.blit(flash_overlay, (0, 0))

# -- HUD ---------------------------------------------------------------------
def draw_hud(surf, player, wave_mgr):
    now = time.time()
    alive_count = sum(1 for r in wave_mgr.robots if r.alive)
    draw_gun(surf, player)
    # Top and bottom scrims make small text readable against neon storefronts.
    scrim = pygame.Surface((W, 112), pygame.SRCALPHA)
    for y in range(112):
        pygame.draw.line(scrim, (4, 12, 19, int(155*(1-y/112))), (0, y), (W, y))
    surf.blit(scrim, (0, 0))
    surf.blit(pygame.transform.flip(scrim, False, True), (0, H-112))

    panel(surf, (24, 24, 232, 65), accent=CYAN)
    label(surf, 'SEOUL  /  NIGHT WATCH', (40, 34), FONT_XS, CYAN)
    label(surf, tr('종로 · 귀문 봉쇄 작전', 'JONGNO / GATE CONTAINMENT'), (40, 57), FONT_S)
    panel(surf, (W//2-112, 24, 224, 65))
    label(surf, f'SECTOR {wave_mgr.stage:02d}', (W//2, 34), FONT_XS, GOLD, 'midtop')
    label(surf, f'WAVE  {wave_mgr.wave_in_stage():02d} / {WAVES_PER_STAGE:02d}', (W//2, 55), FONT_M, WHITE, 'midtop')
    for index in range(WAVES_PER_STAGE):
        pygame.draw.rect(surf, CYAN if index < wave_mgr.wave_in_stage() else EDGE, (W//2-42+index*18, 84, 12, 2))
    panel(surf, (W-244, 24, 220, 65))
    label(surf, 'SPIRIT SCORE', (W-226, 35), FONT_XS, MUTED)
    label(surf, f'{wave_mgr.score:06d}', (W-42, 29), FONT_M, GOLD, 'topright')
    label(surf, tr(f'퇴치 {player.kills:02d}', f'BANISHED {player.kills:02d}'), (W-226, 60), FONT_XS, WHITE)
    label(surf, f'x{wave_mgr.score_multiplier()}  /  {alive_count:02d} HOSTILES', (W-42, 60), FONT_XS, CYAN, 'topright')

    _draw_minimap(surf, player, wave_mgr.robots)
    panel(surf, (24, H-116, 258, 91), accent=CYAN)
    label(surf, tr('생명력', 'VITALITY'), (42, H-103), FONT_XS, MUTED)
    hp_r = max(0, player.hp/player.MAX_HP)
    hp_color = CYAN if hp_r > .5 else GOLD if hp_r > .25 else RED
    label(surf, f'{max(0, player.hp):03d}', (42, H-88), FONT_NUM, hp_color)
    label(surf, '/ 100', (117, H-70), FONT_S, MUTED)
    for segment in range(20):
        color = hp_color if segment/20 < hp_r else (32, 52, 61)
        pygame.draw.rect(surf, color, (42+segment*11, H-41, 8, 4))

    panel(surf, (W-282, H-116, 258, 91), accent=GOLD)
    label(surf, tr('쌍문 · 봉인총', 'TWIN SEAL / SIDEARMS'), (W-264, H-103), FONT_XS, MUTED)
    if player.reloading:
        ratio = min((now-player.reload_start)/player.RELOAD_TIME, 1)
        label(surf, tr('기운 충전 중', 'RECHARGING'), (W-264, H-78), FONT_M, GOLD)
        pygame.draw.rect(surf, EDGE, (W-264, H-42, 220, 3))
        pygame.draw.rect(surf, GOLD, (W-264, H-42, int(220*ratio), 3))
    else:
        ammo_color = WHITE if player.ammo > 8 else GOLD if player.ammo > 4 else RED
        label(surf, f'{player.ammo:02d}', (W-264, H-88), FONT_NUM, ammo_color)
        label(surf, f'/ {player.MAX_AMMO:02d}', (W-201, H-70), FONT_S, MUTED)
        label(surf, tr('R  재장전', 'R  RELOAD'), (W-44, H-48), FONT_XS, GOLD, 'topright')
    label(surf, tr('WASD 이동    R 재장전    ESC 일시정지', 'WASD MOVE    R RELOAD    ESC PAUSE'), (W//2, H-24), FONT_XS, MUTED, 'midbottom')

    cx, cy = W//2, H//2
    firing = max(0, 1-(now-player.last_shot)/.12)
    gap = 7+int(firing*9)
    cross_color = GOLD if firing else CYAN
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        pygame.draw.line(surf, cross_color, (cx+dx*gap, cy+dy*gap), (cx+dx*(gap+7), cy+dy*(gap+7)), 1)
    pygame.draw.circle(surf, WHITE, (cx, cy), 2)
    if now-player.hit_flash < .25:
        alpha = int(110*(1-(now-player.hit_flash)/.25))
        flash = pygame.Surface((W, H), pygame.SRCALPHA)
        pygame.draw.rect(flash, (188, 44, 48, alpha), flash.get_rect(), 26)
        surf.blit(flash, (0, 0))
    if now-player.headshot_time < .8:
        hs = FONT_S.render(tr('급소 명중', 'CRITICAL SEAL'), True, GOLD)
        hs.set_alpha(int(255*(1-(now-player.headshot_time)/.8)))
        surf.blit(hs, (cx-hs.get_width()//2, cy-57))
    if wave_mgr.wave > 0 and wave_mgr.all_dead() and wave_mgr.wave_clear_time > 0 and not wave_mgr.stage_clear:
        wait = wave_mgr.next_wave_delay-(now-wave_mgr.wave_clear_time)
        if wait > 0:
            panel(surf, (W//2-218, 135, 436, 67), accent=CYAN)
            label(surf, tr('귀문 안정화', 'GATE STABILIZED'), (W//2, 144), FONT_M, CYAN, 'midtop')
            label(surf, tr(f'다음 습격까지 {wait:.1f}초', f'NEXT WAVE IN {wait:.1f}s'), (W//2, 176), FONT_XS, WHITE, 'midtop')
    if wave_mgr.stage_clear:
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((4, 13, 23, 182))
        surf.blit(overlay, (0, 0))
        label(surf, f'SECTOR {wave_mgr.stage:02d}  /  SECURED', (W//2, H//2-103), FONT_XS, GOLD, 'midtop')
        label(surf, tr('서울의 밤을 지켰다', 'THE NIGHT IS OURS'), (W//2, H//2-62), FONT_L, CYAN, 'midtop')
        label(surf, f'{wave_mgr.score:06d} SPIRIT SCORE  /  {player.kills} BANISHED', (W//2, H//2+10), FONT_S, WHITE, 'midtop')
        wait = max(0, 4-(now-wave_mgr.stage_clear_time))
        label(surf, tr(f'{wait:.1f}초 후 다음 구역으로 이동', f'NEXT SECTOR IN {wait:.1f}s'), (W//2, H//2+56), FONT_S, MUTED, 'midtop')


def _draw_minimap(surf, player, robots):
    mm = 132
    mm_x, mm_y = 36, 129
    cell = mm/MAP_W
    panel(surf, (24, 104, 156, 167), 188)
    label(surf, 'JONGNO  /  LIVE', (36, 110), FONT_XS, MUTED)
    mini = pygame.Surface((mm, mm), pygame.SRCALPHA)
    mini.fill((9, 21, 30, 205))
    for ry in range(MAP_H):
        for rx in range(MAP_W):
            if RAW_MAP[ry][rx] == '1':
                pygame.draw.rect(mini, (54, 76, 83), (rx*cell, ry*cell, cell-1, cell-1))
    for robot in robots:
        if robot.alive:
            pygame.draw.circle(mini, RANK_COLORS[robot.rank], (int(robot.x*cell), int(robot.y*cell)), 2 if robot.rank == 'normal' else 3)
    sx, sy = int(player.x*cell), int(player.y*cell)
    points = [(sx+math.cos(player.angle+a)*radius, sy+math.sin(player.angle+a)*radius) for a, radius in ((0, 7), (2.5, 4), (-2.5, 4))]
    pygame.draw.polygon(mini, WHITE, points)
    surf.blit(mini, (mm_x, mm_y))

# -- Player ------------------------------------------------------------------
class Player:
    MAX_HP  = 100
    SPEED   = 4.2
    FIRE_CD = 0.13
    DAMAGE  = 25

    MAX_AMMO    = 24
    RELOAD_TIME = 2.0

    def __init__(self):
        self.x = 1.5
        self.y = 1.5
        self.angle = 0.0
        self.pitch = 0.0
        self.hp = self.MAX_HP
        self.last_shot = 0
        self.kills = 0
        self.hit_flash = 0
        self.ammo = self.MAX_AMMO
        self.reloading = False
        self.reload_start = 0
        self.headshot_time = 0   # headshot indicator timer

    def move(self, keys, dt):
        spd = self.SPEED * dt
        mx = my = 0.0
        if keys[pygame.K_w]: mx += math.cos(self.angle)*spd; my += math.sin(self.angle)*spd
        if keys[pygame.K_s]: mx -= math.cos(self.angle)*spd; my -= math.sin(self.angle)*spd
        if keys[pygame.K_a]: mx += math.cos(self.angle - math.pi/2)*spd; my += math.sin(self.angle - math.pi/2)*spd
        if keys[pygame.K_d]: mx += math.cos(self.angle + math.pi/2)*spd; my += math.sin(self.angle + math.pi/2)*spd
        m = 0.25
        nx, ny = self.x + mx, self.y + my
        if not is_wall(nx + math.copysign(m, mx) if mx else nx, self.y): self.x = nx
        if not is_wall(self.x, ny + math.copysign(m, my) if my else ny): self.y = ny

    def can_shoot(self):
        if self.reloading: return False
        if self.ammo <= 0: return False
        return time.time() - self.last_shot >= self.FIRE_CD

    def try_reload(self):
        if self.reloading or self.ammo == self.MAX_AMMO: return
        self.reloading = True
        self.reload_start = time.time()

    def update_reload(self):
        if self.reloading and time.time() - self.reload_start >= self.RELOAD_TIME:
            self.ammo = self.MAX_AMMO
            self.reloading = False

    def shoot(self, robots):
        self.last_shot = time.time()
        self.ammo -= 1
        if self.ammo == 0:
            self.try_reload()

        rd_x = math.cos(self.angle)
        rd_y = math.sin(self.angle)
        best_dist = MAX_DEPTH
        best = None

        for r in robots:
            if not r.alive: continue
            dx = r.x - self.x
            dy = r.y - self.y
            dist = math.sqrt(dx*dx + dy*dy)
            if dist > best_dist: continue
            proj = dx*rd_x + dy*rd_y
            if proj <= 0: continue
            perp = abs(dx*rd_y - dy*rd_x)
            if perp < 0.45:
                wall_dist, _, _, _ = cast_ray(self.x, self.y, self.angle)
                if proj < wall_dist:
                    best_dist = dist
                    best = r

        if best:
            # ---
            relative = math.atan2(best.y-self.y, best.x-self.x)-self.angle
            wall_h = H/max(best_dist*math.cos(relative), .1)
            sp_h = min(int(wall_h*{"normal": .80, "elite": .88, "boss": 1.02}[best.rank]), H*3)
            sprite_top = H/2+self.pitch+wall_h*.5-sp_h
            headshot = sprite_top+sp_h*.06 <= H/2 <= sprite_top+sp_h*.30
            dmg = int(self.DAMAGE * 2.5) if headshot else self.DAMAGE
            best.take_damage(dmg)
            if headshot:
                self.headshot_time = time.time()
            if not best.alive:
                self.kills += 1
        return best


# -- Robot -------------------------------------------------------------------
class Robot:
    RANKS = {
        "normal": {"hp": 60,  "spd": 1.7, "dmg": 10, "score": 10,  "atk_cd": 0.9},
        "elite":  {"hp": 140, "spd": 2.3, "dmg": 18, "score": 25,  "atk_cd": 0.7},
        "boss":   {"hp": 400, "spd": 1.2, "dmg": 28, "score": 100, "atk_cd": 1.2},
    }

    def __init__(self, x, y, rank="normal"):
        self.x, self.y = x, y
        self.rank = rank
        s = self.RANKS[rank]
        self.max_hp, self.hp = s["hp"], s["hp"]
        self.spd = s["spd"]
        self.dmg = s["dmg"]
        self.score = s["score"]
        self.atk_cd = s["atk_cd"]
        self.alive = True
        self.last_attack = 0
        self.scored = False

    def take_damage(self, dmg):
        self.hp = max(0, self.hp - dmg)
        if self.hp == 0:
            self.alive = False

    def update(self, player, dt):
        if not self.alive: return
        dx = player.x - self.x
        dy = player.y - self.y
        dist = math.sqrt(dx*dx + dy*dy)

        if dist < 1.0:
            now = time.time()
            if now - self.last_attack > self.atk_cd:
                self.last_attack = now
                player.hp -= self.dmg
                player.hit_flash = now
            return

        if dist > 0:
            nx = self.x + (dx/dist) * self.spd * dt
            ny = self.y + (dy/dist) * self.spd * dt
            m = 0.25
            if not is_wall(nx + math.copysign(m, dx/dist), self.y): self.x = nx
            if not is_wall(self.x, ny + math.copysign(m, dy/dist)): self.y = ny


# -- Health pack -------------------------------------------------------------
class HealthPack:
    HEAL    = 35
    RESPAWN = 15.0
    # ---
    POSITIONS = [
        (5.5, 5.5), (14.5, 5.5),
        (1.5, 9.5), (18.5, 9.5),
        (9.5, 9.5), (10.5, 10.5),
        (5.5, 14.5), (14.5, 14.5),
        (1.5, 14.5), (18.5, 5.5),
    ]

    def __init__(self, x, y):
        self.x, self.y = x, y
        self.active = True
        self.pickup_time = 0.0

    def update(self, player):
        if not self.active:
            if time.time() - self.pickup_time >= self.RESPAWN:
                self.active = True
            return
        dx = player.x - self.x
        dy = player.y - self.y
        if math.sqrt(dx*dx + dy*dy) < 0.75:
            player.hp = min(player.MAX_HP, player.hp + self.HEAL)
            player.hit_flash = 0   # clear damage flash on pickup
            self.active = False
            self.pickup_time = time.time()


# -- Stage / wave ------------------------------------------------------------
WAVES_PER_STAGE = 5   # 5 waves = 1 stage

class WaveManager:
    def __init__(self):
        self.wave = 0
        self.stage = 1
        self.score = 0
        self.robots = []
        self.wave_clear_time = 0
        self.next_wave_delay = 3.0
        self.stage_clear = False     # showing stage-clear banner
        self.stage_clear_time = 0

    def all_dead(self):
        return all(not r.alive for r in self.robots)

    def wave_in_stage(self):
        """Wave number within the current stage (1..WAVES_PER_STAGE)"""
        return ((self.wave - 1) % WAVES_PER_STAGE) + 1

    def is_last_wave_of_stage(self):
        return self.wave % WAVES_PER_STAGE == 0

    def score_multiplier(self):
        return self.stage

    def start_next_wave(self, player):
        self.wave += 1
        # ---
        self.stage = (self.wave - 1) // WAVES_PER_STAGE + 1
        self.robots = []

        # ---
        count = 3 + self.wave * 2
        boss_count  = 1 if self.wave % WAVES_PER_STAGE == 0 else 0
        elite_count = min(self.wave // 2, count // 3)
        normal_count = count - elite_count - boss_count
        ranks = ["normal"]*normal_count + ["elite"]*elite_count + ["boss"]*boss_count
        random.shuffle(ranks)

        # ---
        spd_boost = 1.0 + (self.stage - 1) * 0.15
        dmg_boost = 1.0 + (self.stage - 1) * 0.20

        cands = [c for c in OPEN_CELLS
                 if math.sqrt((c[0]-player.x)**2 + (c[1]-player.y)**2) > 5.0]
        if len(cands) < len(ranks):
            cands = OPEN_CELLS[:]
        positions = random.sample(cands, min(len(ranks), len(cands)))
        for i, rank in enumerate(ranks[:len(positions)]):
            r = Robot(positions[i][0], positions[i][1], rank)
            r.spd *= spd_boost
            r.dmg = int(r.dmg * dmg_boost)
            self.robots.append(r)

    def update(self, player, dt):
        now = time.time()

        # ---
        if self.stage_clear:
            if now - self.stage_clear_time >= 4.0:
                self.stage_clear = False
                self.start_next_wave(player)
            return

        for r in self.robots:
            r.update(player, dt)
            if not r.alive and not r.scored:
                self.score += r.score * self.score_multiplier()
                r.scored = True

        if self.all_dead():
            if self.wave_clear_time == 0:
                self.wave_clear_time = now
            elif now - self.wave_clear_time >= self.next_wave_delay:
                self.wave_clear_time = 0
                if self.is_last_wave_of_stage():
                    # ---
                    self.stage_clear = True
                    self.stage_clear_time = now
                else:
                    self.start_next_wave(player)
        else:
            self.wave_clear_time = 0


# -- Screens -----------------------------------------------------------------
def draw_bg(surf):
    if MENU_BACKDROP:
        surf.blit(MENU_BACKDROP, (0, 0))
    else:
        surf.fill(SKY)
        for i in range(18):
            height = 150+(i*71)%280
            pygame.draw.rect(surf, (20+i%3*5, 38, 48), (i*64, H-height, 56, height))
            for y in range(H-height+18, H, 32):
                pygame.draw.line(surf, EDGE, (i*64+12, y), (i*64+44, y), 3)
    overlay = pygame.Surface((W, H), pygame.SRCALPHA)
    for x in range(W):
        alpha = int(224-139*x/W)
        pygame.draw.line(overlay, (4, 13, 22, alpha), (x, 0), (x, H))
    for y in range(H-190, H):
        pygame.draw.line(overlay, (4, 13, 22, int(155+85*(y-H+190)/190)), (0, y), (W, y))
    surf.blit(overlay, (0, 0))
    # Quiet, deterministic rain streaks add movement without hiding the artwork.
    tick = time.time()*38
    for i in range(26):
        x = (i*137+37) % W
        y = int((i*91+tick) % H)
        pygame.draw.line(surf, (63, 89, 100), (x, y), (x-3, y+12), 1)


def draw_sigil(surf, center, radius, color):
    cx, cy = center
    pygame.draw.circle(surf, color, center, radius, 1)
    pygame.draw.circle(surf, color, center, radius-7, 1)
    for index in range(8):
        angle = index*math.pi/4
        p1 = (cx+int(math.cos(angle)*(radius-4)), cy+int(math.sin(angle)*(radius-4)))
        p2 = (cx+int(math.cos(angle)*(radius+5)), cy+int(math.sin(angle)*(radius+5)))
        pygame.draw.line(surf, color, p1, p2, 2)
    pygame.draw.line(surf, color, (cx-9, cy-11), (cx+9, cy-11), 2)
    pygame.draw.line(surf, color, (cx, cy-19), (cx, cy+19), 2)
    pygame.draw.lines(surf, color, False, [(cx-11, cy+10), (cx, cy+1), (cx+11, cy+10)], 2)


def draw_title_scene(surf):
    draw_bg(surf)
    draw_sigil(surf, (78, 63), 25, GOLD)
    label(surf, 'NIGHT WATCH DIVISION', (119, 43), FONT_S, WHITE)
    label(surf, 'SEOUL, REPUBLIC OF KOREA  /  37.57 N 126.98 E', (119, 68), FONT_XS, MUTED)
    label(surf, 'CHAPTER 01', (W-54, 44), FONT_XS, GOLD, 'topright')
    label(surf, tr('종로의 밤', 'NIGHTS OF JONGNO'), (W-54, 68), FONT_S, WHITE, 'topright')
    pygame.draw.line(surf, EDGE, (54, 110), (W-54, 110))

    label(surf, tr('서울, 귀문이 열리다', 'THE SPIRIT GATE IS OPEN'), (56, 160), FONT_M, CYAN)
    label(surf, 'DOKKAEBI', (50, 195), FONT_HERO, WHITE)
    label(surf, 'N I G H T F A L L', (56, 285), FONT_L, GOLD)
    label(surf, tr('익숙한 골목, 낯선 존재들.', 'Familiar streets. Spirits after dark.'), (57, 359), FONT_M, WHITE)
    label(surf, tr('푸른 도깨비불을 쫓아 서울의 밤을 되찾으세요.', 'Follow the ghost fire. Take back the night.'), (57, 399), FONT_S, MUTED)
    pygame.draw.line(surf, GOLD, (57, 449), (96, 449), 2)
    label(surf, tr('5번의 습격 · 3종의 도깨비 · 끝없는 밤', '5 WAVES / 3 SPIRIT CLASSES / ENDLESS NIGHT'), (109, 440), FONT_XS, GOLD)

    label(surf, tr('도깨비 도감', 'SPIRIT FIELD GUIDE'), (560, 416), FONT_XS, MUTED)
    rank_info = [('normal', tr('청귀', 'CHEONGGWI'), '60 HP'), ('elite', tr('적귀', 'JEOKGWI'), '140 HP'), ('boss', tr('도깨비 왕', 'SPIRIT KING'), '400 HP')]
    for index, (rank, name, hp) in enumerate(rank_info):
        x, y = 560+index*140, 448
        panel(surf, (x, y, 128, 183), 202)
        pygame.draw.line(surf, RANK_COLORS[rank], (x+1, y), (x+126, y), 2)
        sprite = ASSETS.get('dokkaebi-'+rank)
        if sprite is not None:
            ratio = min(112/sprite.get_width(), 112/sprite.get_height())
            thumbnail = pygame.transform.smoothscale(sprite, (max(1, int(sprite.get_width()*ratio)), max(1, int(sprite.get_height()*ratio))))
            surf.blit(thumbnail, (x+64-thumbnail.get_width()//2, y+12+112-thumbnail.get_height()))
        else:
            draw_sigil(surf, (x+64, y+67), 31, RANK_COLORS[rank])
        label(surf, name, (x+64, y+129), FONT_S, WHITE, 'midtop')
        label(surf, hp, (x+64, y+156), FONT_XS, RANK_COLORS[rank], 'midtop')

    button = pygame.Rect(56, 542, 448, 65)
    hovered = button.collidepoint(pygame.mouse.get_pos())
    pygame.draw.rect(surf, (147, 237, 215) if hovered else CYAN, button, border_radius=2)
    label(surf, tr('야간 순찰 시작', 'BEGIN NIGHT WATCH'), (78, 558), FONT_M, INK)
    label(surf, 'ENTER  >', (481, 565), FONT_XS, INK, 'topright')
    label(surf, tr('Enter 또는 클릭으로 시작', 'PRESS ENTER OR CLICK TO START'), (57, 621), FONT_XS, MUTED)
    pygame.draw.line(surf, EDGE, (54, 682), (W-54, 682))
    label(surf, tr('WASD 이동    마우스 조준    좌클릭 발사    R 재장전', 'WASD MOVE    MOUSE AIM    LMB FIRE    R RELOAD'), (56, 705), FONT_XS, WHITE)
    label(surf, 'SEOUL / 00:00 / GATE ACTIVE', (W-54, 705), FONT_XS, CYAN, 'topright')


async def title_screen(surf, clock):
    pygame.mouse.set_visible(True)
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                return
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                return
        draw_title_scene(surf)
        pygame.display.flip()
        clock.tick(30)
        await asyncio.sleep(0)


def draw_game_over_scene(surf, kills, score, wave, stage):
    if score >= 5000: rank, rank_color = 'S', GOLD
    elif score >= 2000: rank, rank_color = 'A', CYAN
    elif score >= 800: rank, rank_color = 'B', (140, 187, 227)
    elif score >= 300: rank, rank_color = 'C', WHITE
    else: rank, rank_color = 'D', MUTED
    draw_bg(surf)
    panel(surf, (224, 94, 576, 580), 222)
    label(surf, 'NIGHT WATCH / AFTER ACTION REPORT', (W//2, 119), FONT_XS, GOLD, 'midtop')
    label(surf, tr('순찰 종료', 'WATCH ENDED'), (W//2, 168), FONT_XL, WHITE, 'midtop')
    label(surf, tr('서울의 밤은 아직 끝나지 않았습니다.', 'The city still needs its guardian.'), (W//2, 246), FONT_S, MUTED, 'midtop')
    pygame.draw.circle(surf, EDGE, (W//2, 355), 68, 1)
    pygame.draw.circle(surf, rank_color, (W//2, 355), 60, 1)
    label(surf, rank, (W//2, 310), FONT_HERO, rank_color, 'midtop')
    label(surf, 'GUARDIAN RANK', (W//2, 433), FONT_XS, MUTED, 'midtop')
    for x, value, title in ((330, f'{score:06d}', 'SPIRIT SCORE'), (W//2, f'{kills:02d}', 'BANISHED'), (693, f'{stage:02d} / {wave:02d}', 'SECTOR / WAVE')):
        label(surf, value, (x, 474), FONT_M, WHITE, 'midtop')
        label(surf, title, (x, 511), FONT_XS, MUTED, 'midtop')
    pygame.draw.rect(surf, CYAN, (276, 568, 472, 59), border_radius=2)
    label(surf, tr('다시 서울을 지키러 가기', 'RETURN TO THE NIGHT'), (W//2, 583), FONT_M, INK, 'midtop')
    label(surf, tr('Enter 또는 클릭으로 다시 시작', 'ENTER OR CLICK TO RESTART'), (W//2, 641), FONT_XS, MUTED, 'midtop')


async def game_over_screen(surf, clock, kills, score, wave, stage):
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                return True
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                return True
        draw_game_over_scene(surf, kills, score, wave, stage)
        pygame.display.flip()
        clock.tick(30)
        await asyncio.sleep(0)

def shift_pause_timers(player, wave_mgr, packs, elapsed):
    """Keep cooldowns, reloads, and wave transitions frozen while paused."""
    fields = [(player, ("last_shot", "reload_start", "hit_flash")),
              (wave_mgr, ("wave_clear_time", "stage_clear_time"))]
    fields += [(robot, ("last_attack",)) for robot in wave_mgr.robots]
    fields += [(pack, ("pickup_time",)) for pack in packs]
    for obj, names in fields:
        for name in names:
            value = getattr(obj, name)
            if value > 0:
                setattr(obj, name, value+elapsed)


def draw_pause_overlay(surf):
    veil = pygame.Surface((W, H), pygame.SRCALPHA)
    veil.fill((3, 12, 22, 195))
    surf.blit(veil, (0, 0))
    panel(surf, (252, 266, 520, 236), 240, CYAN)
    label(surf, 'NIGHT WATCH / ON HOLD', (W//2, 292), FONT_XS, GOLD, 'midtop')
    label(surf, tr('잠시 숨을 고르세요', 'WATCH PAUSED'), (W//2, 333), FONT_L, WHITE, 'midtop')
    label(surf, tr('ESC 또는 클릭으로 순찰 계속', 'ESC OR CLICK TO RESUME'), (W//2, 408), FONT_S, CYAN, 'midtop')
    label(surf, tr('일시정지 중에는 공격받지 않습니다.', 'The city waits while you are away.'), (W//2, 452), FONT_XS, MUTED, 'midtop')


# -- Main loop ---------------------------------------------------------------
async def run_game():
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Dokkaebi: Nightfall | Seoul Night Watch")
    load_assets()
    if sys.platform == "emscripten":
        import platform
        try:
            platform.window.gameReady()
        except Exception as exc:
            print("Browser ready notification unavailable:", exc)
    clock = pygame.time.Clock()
    await title_screen(screen, clock)

    while True:
        player   = Player()
        wave_mgr = WaveManager()
        wave_mgr.start_next_wave(player)
        packs = [HealthPack(x, y) for x, y in HealthPack.POSITIONS]

        pygame.event.set_grab(True)
        pygame.mouse.set_visible(False)
        mouse_grabbed = True
        paused_at = None
        suppress_fire = False
        surf = pygame.Surface((W, H))

        def set_paused(paused):
            nonlocal mouse_grabbed, paused_at, suppress_fire
            if paused == (not mouse_grabbed):
                return
            if paused:
                paused_at = time.time()
            else:
                if paused_at is not None:
                    shift_pause_timers(player, wave_mgr, packs, time.time()-paused_at)
                paused_at = None
                suppress_fire = True
            mouse_grabbed = not paused
            pygame.event.set_grab(mouse_grabbed)
            pygame.mouse.set_visible(paused)
            pygame.mouse.get_rel()

        running = True
        while running:
            dt = min(clock.tick(60) / 1000, 0.05)

            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        set_paused(mouse_grabbed)
                    if ev.key == pygame.K_r and mouse_grabbed:
                        player.try_reload()
                if ev.type == pygame.WINDOWFOCUSLOST:
                    set_paused(True)
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    if not mouse_grabbed:
                        set_paused(False)
                if ev.type == pygame.MOUSEMOTION and mouse_grabbed:
                    player.angle += ev.rel[0] * 0.0014   # mouse sensitivity
                    player.pitch = max(-220, min(220, player.pitch - ev.rel[1] * 0.55))

            if not mouse_grabbed:
                screen.blit(surf, (0, 0))
                draw_hud(screen, player, wave_mgr)
                draw_pause_overlay(screen)
                pygame.display.flip()
                await asyncio.sleep(0)
                continue

            fire_held = pygame.mouse.get_pressed()[0]
            if not fire_held:
                suppress_fire = False
            if fire_held and not suppress_fire:
                if player.can_shoot():
                    player.shoot(wave_mgr.robots)
                elif player.ammo == 0 and not player.reloading:
                    player.try_reload()

            keys = pygame.key.get_pressed()
            player.move(keys, dt)
            player.update_reload()

            for pack in packs:
                pack.update(player)

            wave_mgr.update(player, dt)

            if player.hp <= 0:
                pygame.event.set_grab(False)
                pygame.mouse.set_visible(True)
                await game_over_screen(screen, clock,
                                       player.kills, wave_mgr.score,
                                       wave_mgr.wave, wave_mgr.stage)
                running = False
                break

            render_world(surf, player.x, player.y, player.angle, player.pitch,
                         wave_mgr.robots, packs)
            screen.blit(surf, (0, 0))
            draw_hud(screen, player, wave_mgr)
            pygame.display.flip()
            await asyncio.sleep(0)


async def main():
    await run_game()

if __name__ == "__main__":
    asyncio.run(main())
