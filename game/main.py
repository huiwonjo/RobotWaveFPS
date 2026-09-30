import pygame
import sys
import math
import time
import random
import asyncio

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
WHITE  = (255, 255, 255)
BLACK  = (0, 0, 0)
GRAY   = (100, 100, 100)
DGRAY  = (25, 25, 35)
RED    = (220, 60, 60)
GREEN  = (60, 200, 60)
YELLOW = (240, 200, 0)
ORANGE = (255, 140, 0)
CYAN   = (0, 210, 240)
SKY    = (18, 22, 45)
FLOOR  = (42, 36, 30)

pygame.init()
_KR = None  # web: use default font
FONT_S  = pygame.font.Font(None, 22)
FONT_M  = pygame.font.Font(None, 28)
FONT_L  = pygame.font.Font(None, 46)
FONT_XL = pygame.font.Font(None, 74)

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


# -- Robot sprite ------------------------------------------------------------
def draw_robot_sprite(small, screen_x, sp_h, sp_w, sp_top, dist_sp, z_buf, rank, hp_ratio):
    shade = max(0.25, 1.0 - dist_sp / MAX_DEPTH)
    head_end  = sp_top + int(sp_h * 0.28)
    torso_end = sp_top + int(sp_h * 0.72)
    sp_bot    = sp_top + sp_h

    if rank == "boss":
        head_col, visor_col, torso_col, accent_col, leg_col = \
            (180,40,200),(255,100,255),(120,20,150),(220,80,255),(90,15,110)
    elif rank == "elite":
        head_col, visor_col, torso_col, accent_col, leg_col = \
            (30,160,200),(80,240,255),(20,100,140),(0,220,255),(15,70,100)
    else:
        head_col, visor_col, torso_col, accent_col, leg_col = \
            (80,160,80),(180,255,80),(50,110,50),(100,255,100),(35,75,35)

    def sc(c): return tuple(int(v * shade) for v in c)
    half = sp_w // 2

    for sx in range(screen_x - half, screen_x + half + 1):
        if not (0 <= sx < COLS): continue
        if z_buf[sx] <= dist_sp: continue
        col_ratio = (sx - (screen_x - half)) / max(sp_w, 1)

        pygame.draw.line(small, sc(head_col), (sx, sp_top), (sx, head_end))
        visor_top = sp_top + int(sp_h * 0.10)
        visor_bot = sp_top + int(sp_h * 0.20)
        pygame.draw.line(small, sc(visor_col), (sx, visor_top), (sx, visor_bot))

        is_arm = col_ratio < 0.15 or col_ratio > 0.85
        torso_start = head_end if not is_arm else head_end + int(sp_h * 0.08)
        pygame.draw.line(small, sc(torso_col), (sx, torso_start), (sx, torso_end))

        acc_y = head_end + int(sp_h * 0.15)
        if torso_start <= acc_y <= torso_end:
            small.set_at((sx, acc_y), sc(accent_col))
            if acc_y + 1 <= torso_end:
                small.set_at((sx, acc_y + 1), sc(accent_col))

        if 0.3 < col_ratio < 0.7:
            pygame.draw.line(small, sc(leg_col), (sx, torso_end), (sx, sp_bot))

    bar_w = max(sp_w, 10)
    bar_x = screen_x - bar_w // 2
    bar_y = sp_top - 7
    if 0 < bar_y < H:
        pygame.draw.rect(small, (80, 0, 0), (bar_x, bar_y, bar_w, 4))
        pygame.draw.rect(small, (0, 220, 60), (bar_x, bar_y, int(bar_w * hp_ratio), 4))


def render_world(surf, px, py, angle, pitch, robots, packs):
    small = pygame.Surface((COLS, H))
    horizon = H // 2 + int(pitch)

    pygame.draw.rect(small, SKY,   (0, 0, COLS, max(horizon, 0)))
    pygame.draw.rect(small, FLOOR, (0, max(horizon, 0), COLS, H))

    z_buf = []
    for col in range(COLS):
        ray_angle = angle - HALF_FOV + FOV * col / COLS
        dist, side, _, _ = cast_ray(px, py, ray_angle)
        dist_corr = max(dist * math.cos(ray_angle - angle), 0.01)

        wall_h = min(int(H / dist_corr), H * 3)
        wall_top    = horizon - wall_h // 2
        wall_bottom = wall_top + wall_h
        draw_top    = max(wall_top, 0)
        draw_bottom = min(wall_bottom, H)

        shade = max(0.15, 1.0 - dist_corr / MAX_DEPTH)
        base = (175, 155, 135) if side == 0 else (120, 105, 90)
        color = tuple(int(c * shade) for c in base)

        if draw_bottom > draw_top:
            pygame.draw.line(small, color, (col, draw_top), (col, draw_bottom))
        z_buf.append(dist_corr)

    sorted_robots = sorted(robots, key=lambda r: -((r.x-px)**2 + (r.y-py)**2))
    for robot in sorted_robots:
        if not robot.alive: continue
        dx = robot.x - px
        dy = robot.y - py
        dist_sp = math.sqrt(dx*dx + dy*dy)
        if dist_sp < 0.1 or dist_sp > MAX_DEPTH: continue

        sprite_angle = math.atan2(dy, dx) - angle
        while sprite_angle >  math.pi: sprite_angle -= 2 * math.pi
        while sprite_angle < -math.pi: sprite_angle += 2 * math.pi
        if abs(sprite_angle) > HALF_FOV + 0.35: continue

        screen_x = int((0.5 + sprite_angle / FOV) * COLS)
        sp_h = min(int(H / max(dist_sp, 0.1) * 0.5), H)   # 50% of wall height
        sp_w = max(sp_h // 2, 4)
        sp_top = horizon - sp_h // 2

        hp_ratio = robot.hp / robot.max_hp
        draw_robot_sprite(small, screen_x, sp_h, sp_w, sp_top,
                          dist_sp, z_buf, robot.rank, hp_ratio)

    # ---
    for pack in packs:
        if not pack.active: continue
        dx = pack.x - px
        dy = pack.y - py
        dist_sp = math.sqrt(dx*dx + dy*dy)
        if dist_sp < 0.1 or dist_sp > MAX_DEPTH: continue
        sprite_angle = math.atan2(dy, dx) - angle
        while sprite_angle >  math.pi: sprite_angle -= 2 * math.pi
        while sprite_angle < -math.pi: sprite_angle += 2 * math.pi
        if abs(sprite_angle) > HALF_FOV + 0.2: continue

        screen_x = int((0.5 + sprite_angle / FOV) * COLS)
        sp_h = min(int(H / max(dist_sp, 0.1) * 0.3), H)
        sp_w = max(sp_h // 2, 4)
        sp_top = horizon - sp_h // 2
        shade = max(0.4, 1.0 - dist_sp / MAX_DEPTH)
        gc = tuple(int(c * shade) for c in (0, 120, 255))   # body
        rc = tuple(int(c * shade) for c in (255, 255, 255)) # eye glow

        for sx in range(screen_x - sp_w//2, screen_x + sp_w//2 + 1):
            if not (0 <= sx < COLS): continue
            if z_buf[sx] <= dist_sp: continue
            pygame.draw.line(small, gc, (sx, sp_top), (sx, sp_top + sp_h))
        # ---
        mid_y = sp_top + sp_h // 2
        for sx in range(screen_x - sp_w, screen_x + sp_w + 1):
            if 0 <= sx < COLS and z_buf[sx] > dist_sp:
                arm_h = max(sp_h // 5, 2)
                pygame.draw.line(small, rc, (sx, mid_y - arm_h), (sx, mid_y + arm_h))

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
    gy = H - 80 + recoil + bob_y
    lx = W // 4 - 80 - bob_x
    ly = H - 80 + recoil + bob_y

    for (bx, by) in [(gx, gy), (lx, ly)]:
        flip = (bx == lx)
        sign = -1 if flip else 1

        barrel_x = bx - sign * 100
        pygame.draw.rect(surf, (45, 50, 62), (barrel_x if not flip else bx, by + 12, 110, 20))
        pygame.draw.rect(surf, (0, 210, 110), (barrel_x if not flip else bx, by + 12, 110, 5))

        body_x = bx - sign * 10
        pygame.draw.rect(surf, (38, 42, 55), (body_x if not flip else bx - 90, by + 6, 95, 60))
        pygame.draw.rect(surf, (0, 180, 230), (body_x if not flip else bx - 88, by + 18, 80, 7))
        pygame.draw.rect(surf, (70, 80, 100), (body_x if not flip else bx - 90, by + 6, 95, 60), 1)

        pygame.draw.rect(surf, (30, 33, 42), (bx - sign * 10 + (0 if not flip else -30), by + 60, 32, 70))
        pygame.draw.rect(surf, (50, 55, 70), (bx - sign * 10 + (0 if not flip else -30), by + 60, 32, 70), 1)

        scope_x = bx - sign * 40
        pygame.draw.rect(surf, (55, 60, 75), (scope_x if not flip else bx - 70, by, 35, 14))
        pygame.draw.rect(surf, (0, 200, 220), (scope_x + 5 if not flip else bx - 65, by + 3, 25, 6))

    flash_dur = 0.07
    if fire_elapsed < flash_dur:
        ratio = 1.0 - fire_elapsed / flash_dur
        r = int(30 * ratio)

        for (bx, by) in [(gx, gy), (lx, ly)]:
            flip = (bx == lx)
            mx = (bx - 100) if not flip else (bx + 10)
            my = by + 22

            flash_surf = pygame.Surface((r*4+2, r*4+2), pygame.SRCALPHA)
            pygame.draw.circle(flash_surf, (255, 255, 200, int(220*ratio)), (r*2, r*2), r)
            pygame.draw.circle(flash_surf, (255, 230, 80, int(180*ratio)), (r*2, r*2), r//2)
            surf.blit(flash_surf, (mx - r*2, my - r*2))

            for ang_deg in range(0, 360, 40):
                ang = math.radians(ang_deg)
                ex = mx + int(math.cos(ang) * r * 2.2)
                ey = my + int(math.sin(ang) * r * 2.2)
                pygame.draw.line(surf, (255, 210, 50), (mx, my), (ex, ey), max(1, r//6))

        flash_overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        flash_overlay.fill((255, 200, 100, int(30 * ratio)))
        surf.blit(flash_overlay, (0, 0))

    if fire_elapsed < 0.1:
        spread = int((1 - fire_elapsed / 0.1) * 12)
        cx, cy = W // 2, H // 2
        gap = 8 + spread
        pygame.draw.line(surf, (255, 100, 100), (cx - gap - 10, cy), (cx - gap, cy), 2)
        pygame.draw.line(surf, (255, 100, 100), (cx + gap, cy), (cx + gap + 10, cy), 2)
        pygame.draw.line(surf, (255, 100, 100), (cx, cy - gap - 10), (cx, cy - gap), 2)
        pygame.draw.line(surf, (255, 100, 100), (cx, cy + gap), (cx, cy + gap + 10), 2)


# -- HUD -----------------------------------------------------------------------
def draw_hud(surf, player, wave_mgr):
    now = time.time()
    alive_count = sum(1 for r in wave_mgr.robots if r.alive)

    if now - player.last_shot >= 0.1:
        cx, cy = W // 2, H // 2
        gap = 8
        pygame.draw.line(surf, WHITE, (cx-gap-10, cy), (cx-gap, cy), 2)
        pygame.draw.line(surf, WHITE, (cx+gap, cy), (cx+gap+10, cy), 2)
        pygame.draw.line(surf, WHITE, (cx, cy-gap-10), (cx, cy-gap), 2)
        pygame.draw.line(surf, WHITE, (cx, cy+gap), (cx, cy+gap+10), 2)
        pygame.draw.circle(surf, WHITE, (cx, cy), 3, 1)

    if now - player.hit_flash < 0.25:
        alpha = int(140 * (1 - (now - player.hit_flash) / 0.25))
        flash = pygame.Surface((W, H), pygame.SRCALPHA)
        flash.fill((200, 0, 0, alpha))
        surf.blit(flash, (0, 0))

    bar_x, bar_y, bar_w, bar_h = 22, H - 48, 240, 18
    pygame.draw.rect(surf, (15, 15, 25), (bar_x - 2, bar_y - 2, bar_w + 4, bar_h + 4))
    pygame.draw.rect(surf, DGRAY, (bar_x, bar_y, bar_w, bar_h))
    hp_r = max(player.hp / player.MAX_HP, 0)
    hp_col = GREEN if hp_r > 0.5 else YELLOW if hp_r > 0.25 else RED
    pygame.draw.rect(surf, hp_col, (bar_x, bar_y, int(bar_w * hp_r), bar_h))
    pygame.draw.rect(surf, (80, 90, 110), (bar_x, bar_y, bar_w, bar_h), 1)
    hp_t = FONT_M.render(f"HP  {max(player.hp,0)}/{player.MAX_HP}", True, WHITE)
    surf.blit(hp_t, (bar_x, bar_y - 26))

    # ---
    stage_color = [ORANGE, CYAN, (180,80,255), (255,80,80), (255,220,0)][min(wave_mgr.stage-1,4)]
    st_txt = FONT_L.render(f"STAGE {wave_mgr.stage}", True, stage_color)
    surf.blit(st_txt, (W//2 - st_txt.get_width()//2, 8))
    wv_txt = FONT_M.render(f"WAVE {wave_mgr.wave_in_stage()} / {WAVES_PER_STAGE}", True, WHITE)
    surf.blit(wv_txt, (W//2 - wv_txt.get_width()//2, 52))

    # ---
    sc_txt = FONT_M.render(f"SCORE  {wave_mgr.score}", True, WHITE)
    surf.blit(sc_txt, (W - sc_txt.get_width() - 18, 10))
    kl_txt = FONT_M.render(f"KILLS  {player.kills}", True, WHITE)
    surf.blit(kl_txt, (W - kl_txt.get_width() - 18, 36))
    mx_txt = FONT_S.render(f"x{wave_mgr.score_multiplier()} MULT", True, stage_color)
    surf.blit(mx_txt, (W - mx_txt.get_width() - 18, 62))
    et = FONT_M.render(f"ENEMIES  {alive_count}", True, (255, 180, 60))
    surf.blit(et, (W - et.get_width() - 18, 84))

    # ---
    if wave_mgr.wave > 0 and wave_mgr.all_dead() and wave_mgr.wave_clear_time > 0 and not wave_mgr.stage_clear:
        wait = wave_mgr.next_wave_delay - (now - wave_mgr.wave_clear_time)
        if wait > 0:
            ct = FONT_L.render(f"WAVE CLEAR!   Next wave {wait:.1f}s", True, GREEN)
            surf.blit(ct, (W//2 - ct.get_width()//2, H//2 - 40))

    # ---
    if wave_mgr.stage_clear:
        elapsed = now - wave_mgr.stage_clear_time
        ov = pygame.Surface((W, H), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 160))
        surf.blit(ov, (0, 0))
        s1 = FONT_XL.render(f"STAGE {wave_mgr.stage}  CLEAR!", True, stage_color)
        s2 = FONT_L.render(f"SCORE  {wave_mgr.score}   KILLS  {player.kills}", True, WHITE)
        s3 = FONT_M.render(f"Next stage in  {max(0, 4.0 - elapsed):.1f}s", True, GRAY)
        surf.blit(s1, (W//2 - s1.get_width()//2, H//2 - 90))
        surf.blit(s2, (W//2 - s2.get_width()//2, H//2))
        surf.blit(s3, (W//2 - s3.get_width()//2, H//2 + 60))

    # ---
    if player.reloading:
        reload_ratio = min((now - player.reload_start) / player.RELOAD_TIME, 1.0)
        rl_txt = FONT_M.render("Reloading...", True, YELLOW)
        surf.blit(rl_txt, (W - rl_txt.get_width() - 22, H - 52))
        pygame.draw.rect(surf, DGRAY, (W - 222, H - 28, 200, 12))
        pygame.draw.rect(surf, YELLOW, (W - 222, H - 28, int(200 * reload_ratio), 12))
    else:
        ammo_col = WHITE if player.ammo > 8 else YELLOW if player.ammo > 4 else RED
        am_txt = FONT_L.render(f"{player.ammo}  /  {player.MAX_AMMO}", True, ammo_col)
        surf.blit(am_txt, (W - am_txt.get_width() - 22, H - 58))
        am_lbl = FONT_S.render("R = Reload", True, GRAY)
        surf.blit(am_lbl, (W - am_lbl.get_width() - 22, H - 22))

    # ---
    if now - player.headshot_time < 0.8:
        alpha = int(255 * (1 - (now - player.headshot_time) / 0.8))
        hs = FONT_L.render("HEADSHOT!", True, (255, 220, 0))
        hs.set_alpha(alpha)
        surf.blit(hs, (W//2 - hs.get_width()//2, H//2 - 80))

    _draw_minimap(surf, player, wave_mgr.robots)
    draw_gun(surf, player)


def _draw_minimap(surf, player, robots):
    mm = 130
    mm_x = W - mm - 10
    mm_y = H - mm - 10
    cell = mm / MAP_W

    mini = pygame.Surface((mm, mm), pygame.SRCALPHA)
    mini.fill((0, 0, 0, 130))
    for ry in range(MAP_H):
        for rx in range(MAP_W):
            if RAW_MAP[ry][rx] == '1':
                pygame.draw.rect(mini, (130, 120, 110, 220),
                                 (rx*cell, ry*cell, cell, cell))

    for r in robots:
        if not r.alive: continue
        rc = {"normal": RED, "elite": CYAN, "boss": (220, 80, 255)}[r.rank]
        pygame.draw.circle(mini, rc, (int(r.x*cell), int(r.y*cell)), 3)

    sx, sy = int(player.x*cell), int(player.y*cell)
    pygame.draw.circle(mini, WHITE, (sx, sy), 4)
    ax = sx + int(math.cos(player.angle) * 9)
    ay = sy + int(math.sin(player.angle) * 9)
    pygame.draw.line(mini, WHITE, (sx, sy), (ax, ay), 2)
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
            sp_h = min(int(H / max(best_dist, 0.1) * 0.5), H)
            headshot = sp_h * 0.22 <= self.pitch <= sp_h * 0.50
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
    surf.fill((10, 10, 20))
    for i in range(0, W, 60): pygame.draw.line(surf, (20, 20, 35), (i, 0), (i, H))
    for i in range(0, H, 60): pygame.draw.line(surf, (20, 20, 35), (0, i), (W, i))


async def title_screen(surf, clock):
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT: pygame.quit(); sys.exit()
            if ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN): return
        await asyncio.sleep(0)
        draw_bg(surf)

        # ---
        t1 = FONT_XL.render("ROBOT WAVE FPS", True, ORANGE)
        t2 = FONT_M.render("Defeat the robot army and clear the stages!", True, WHITE)
        surf.blit(t1, (W//2 - t1.get_width()//2, 60))
        surf.blit(t2, (W//2 - t2.get_width()//2, 145))

        # ---
        pygame.draw.line(surf, (50, 55, 80), (80, 190), (W - 80, 190), 1)

        # ---
        box_x, box_y, box_w, box_h = 60, 210, 420, 220
        pygame.draw.rect(surf, (18, 20, 36), (box_x, box_y, box_w, box_h), border_radius=8)
        pygame.draw.rect(surf, (50, 60, 100), (box_x, box_y, box_w, box_h), 1, border_radius=8)
        ctrl_title = FONT_M.render("[ CONTROLS ]", True, CYAN)
        surf.blit(ctrl_title, (box_x + box_w//2 - ctrl_title.get_width()//2, box_y + 14))
        controls = [
            ("W A S D",      "Move"),
            ("Mouse",  "Look around"),
            ("LClick",       "Shoot"),
            ("ESC",          "Toggle mouse lock"),
        ]
        for i, (key, desc) in enumerate(controls):
            ky = FONT_M.render(key, True, YELLOW)
            ds = FONT_S.render(desc, True, (180, 185, 210))
            surf.blit(ky, (box_x + 20, box_y + 52 + i * 40))
            surf.blit(ds, (box_x + 190, box_y + 57 + i * 40))

        # ---
        box2_x = W - 60 - 420
        pygame.draw.rect(surf, (18, 20, 36), (box2_x, box_y, box_w, box_h), border_radius=8)
        pygame.draw.rect(surf, (50, 60, 100), (box2_x, box_y, box_w, box_h), 1, border_radius=8)
        rule_title = FONT_M.render("[ GAME RULES ]", True, CYAN)
        surf.blit(rule_title, (box2_x + box_w//2 - rule_title.get_width()//2, box_y + 14))
        rules = [
            ("5 Waves",   "= 1 Stage Clear"),
            ("Stage UP",  "Score mult up, harder enemies"),
            ("Normal  Green",   "HP 60 / basic robot"),
            ("Elite  Blue", "HP 140 / fast robot"),
            ("Boss  Purple",   "HP 400 / strong robot"),
        ]
        for i, (key, desc) in enumerate(rules):
            ky = FONT_S.render(key, True, YELLOW)
            ds = FONT_S.render(desc, True, (180, 185, 210))
            surf.blit(ky, (box2_x + 20, box_y + 52 + i * 33))
            surf.blit(ds, (box2_x + 175, box_y + 52 + i * 33))

        # ---
        pygame.draw.line(surf, (50, 55, 80), (80, 448), (W - 80, 448), 1)

        # ---
        rank_y = 462
        rk_title = FONT_M.render("Score Rank:  ", True, WHITE)
        surf.blit(rk_title, (W//2 - 330, rank_y))
        ranks_info = [("D", GRAY), ("C", (200,200,200)), ("B", (100,180,255)),
                      ("A", (100,220,100)), ("S", (255,220,0))]
        thresholds = ["~299", "300~", "800~", "2000~", "5000~"]
        rx = W//2 - 330 + rk_title.get_width()
        for (r, rc), thr in zip(ranks_info, thresholds):
            rr = FONT_M.render(r, True, rc)
            tt = FONT_S.render(f"({thr})  ", True, (150,155,175))
            surf.blit(rr, (rx, rank_y))
            surf.blit(tt, (rx + rr.get_width() + 2, rank_y + 5))
            rx += rr.get_width() + tt.get_width() + 10

        # ---
        if int(time.time() * 2) % 2 == 0:
            start = FONT_L.render(">> Press any key to start <<", True, (255, 255, 255))
            surf.blit(start, (W//2 - start.get_width()//2, H - 80))

        pygame.display.flip()
        clock.tick(30)


async def game_over_screen(surf, clock, kills, score, wave, stage):
    # ---
    if   score >= 5000: rank, rank_col = "S", (255, 220, 0)
    elif score >= 2000: rank, rank_col = "A", (100, 220, 100)
    elif score >= 800:  rank, rank_col = "B", (100, 180, 255)
    elif score >= 300:  rank, rank_col = "C", (200, 200, 200)
    else:               rank, rank_col = "D", GRAY

    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT: pygame.quit(); sys.exit()
            if ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN): return True
        await asyncio.sleep(0)
        draw_bg(surf)
        t1 = FONT_XL.render("GAME  OVER", True, RED)
        t2 = FONT_L.render(f"STAGE {stage}   WAVE {wave}   KILLS {kills}", True, WHITE)
        t3 = FONT_L.render(f"SCORE  {score}", True, YELLOW)
        rk = FONT_XL.render(f"RANK  {rank}", True, rank_col)
        t4 = FONT_M.render("Press any key to restart", True, GRAY)
        surf.blit(t1, (W//2 - t1.get_width()//2, H//2 - 160))
        surf.blit(t2, (W//2 - t2.get_width()//2, H//2 - 70))
        surf.blit(t3, (W//2 - t3.get_width()//2, H//2 - 10))
        surf.blit(rk, (W//2 - rk.get_width()//2, H//2 + 55))
        surf.blit(t4, (W//2 - t4.get_width()//2, H//2 + 140))
        pygame.display.flip()
        clock.tick(30)


# -- Main loop ---------------------------------------------------------------
async def run_game():
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("Robot Wave FPS")
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
        surf = pygame.Surface((W, H))

        running = True
        while running:
            dt = min(clock.tick(60) / 1000, 0.05)

            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        if mouse_grabbed:
                            pygame.event.set_grab(False)
                            pygame.mouse.set_visible(True)
                            mouse_grabbed = False
                        else:
                            pygame.event.set_grab(True)
                            pygame.mouse.set_visible(False)
                            mouse_grabbed = True
                    if ev.key == pygame.K_r:
                        player.try_reload()
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    if not mouse_grabbed:
                        pygame.event.set_grab(True)
                        pygame.mouse.set_visible(False)
                        mouse_grabbed = True
                if ev.type == pygame.MOUSEMOTION and mouse_grabbed:
                    player.angle += ev.rel[0] * 0.0014   # mouse sensitivity
                    player.pitch = max(-220, min(220, player.pitch - ev.rel[1] * 0.55))

            # ---
            if mouse_grabbed and pygame.mouse.get_pressed()[0]:
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

asyncio.run(main())
