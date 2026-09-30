"""Constants, caps, key map and shared colours (spec 7.4). FOUNDATION owns this file."""
import math

import pygame

# --- screen / raycaster -----------------------------------------------------
W, H = 1024, 768
COLS = 320
FOV = math.pi / 3
HALF_FOV = FOV / 2
MAX_DEPTH = 20
COL_SCALE = W / COLS            # 3.2: one raycast column in 1024 space

# --- bodies -------------------------------------------------------------------
EYE_Z = 0.5
PLAYER_RADIUS = 0.25
HIT_PAD = 0.08

TEAM_PLAYER, TEAM_ENEMY = 0, 1

# sprite flags (re-exported by render; defined here so combat can use them)
FLAG_FLASH = 1
FLAG_STUN = 2
FLAG_DYING = 4
FLAG_NOSHADE = 8

# --- caps (section 8, rule 5) -----------------------------------------------
CAP_ALIVE = 10
CAP_SUMMONS = 2
CAP_PROJECTILES = 40
CAP_PARTICLES = 64
CAP_EFFECTS = 24
CAP_BARRIERS = 4
CAP_PLAYER_BARRIERS = 1
CAP_ENEMY_BARRIERS = 3
CAP_LOS_PER_FRAME = 8

# --- combat -------------------------------------------------------------------
CRIT_MULT = 2.0
ARMOR_REDUCTION = 0.30
SHIELD_REGEN_DELAY = 3.0
SHIELD_REGEN_RATE = 30.0

ULT_PASSIVE_RATE = 5.0
ULT_SWAP_KEEP = 0.30
ULT_SLOWMO = (0.35, 0.3)        # (timescale, real seconds)

# --- look ---------------------------------------------------------------------
MOUSE_YAW = 0.0014
MOUSE_PITCH = 0.55
PITCH_LIMIT = 220
SENS_MIN, SENS_MAX, SENS_STEP = 0.4, 2.5, 0.1

# --- match flow ---------------------------------------------------------------
WAVES_PER_STAGE = 5
VICTORY_STAGE = 3
WAVE_CLEAR_DELAY = 3.0
INTERMISSION = 8.0
COUNTDOWN = 3.0
END_BANNER_TIME = 2.0
SPAWN_MIN_DIST = (7.0, 5.0, 3.0)

# --- health packs (spec 4.8) ------------------------------------------------
PACKS_LARGE = ((1.5, 9.5), (18.5, 9.5), (5.5, 14.5), (14.5, 5.5))
PACKS_SMALL = ((5.5, 5.5), (9.5, 9.5), (10.5, 10.5), (14.5, 14.5), (1.5, 14.5), (18.5, 5.5))
PACK_LARGE = (250.0, 15.0, 0.45)    # heal, respawn seconds, sprite height
PACK_SMALL = (75.0, 10.0, 0.30)
PACK_RADIUS = 0.75

# --- rank (score thresholds, unchanged from the original game) ---------------
RANKS = (('S', 5000, (255, 220, 0)), ('A', 2000, (100, 220, 100)), ('B', 800, (100, 180, 255)),
         ('C', 300, (200, 200, 200)), ('D', 0, (100, 100, 100)))

# --- colours shared by gameplay-facing UI -----------------------------------
COL_HEALTH = (235, 235, 235)
COL_ARMOR = (255, 170, 40)
COL_SHIELD = (90, 170, 255)
COL_MISSING = (40, 48, 56)
COL_PLAYER = (80, 190, 255)
COL_ENEMY = (255, 90, 80)
COL_CRIT = (255, 60, 40)
COL_ULT = (255, 210, 60)
COL_ELITE = (0, 220, 255)
POOL_COLORS = {'health': COL_HEALTH, 'armor': COL_ARMOR, 'shields': COL_SHIELD}

# --- input (spec 2 / 7.4). The first key listed for an action is the one the
# --- harness uses when it synthesises events.
KEYMAP = {
    pygame.K_w: 'fwd', pygame.K_UP: 'fwd',
    pygame.K_s: 'back', pygame.K_DOWN: 'back',
    pygame.K_a: 'left', pygame.K_LEFT: 'left',
    pygame.K_d: 'right', pygame.K_RIGHT: 'right',
    pygame.K_LSHIFT: 'ab1', pygame.K_RSHIFT: 'ab1', pygame.K_SPACE: 'ab1',
    pygame.K_e: 'ab2',
    pygame.K_q: 'ult',
    pygame.K_f: 'alt',
    pygame.K_r: 'reload',
    pygame.K_v: 'melee',
    pygame.K_ESCAPE: 'pause', pygame.K_p: 'pause',
    pygame.K_1: 'hero1', pygame.K_2: 'hero2', pygame.K_3: 'hero3',
    pygame.K_RETURN: 'confirm', pygame.K_KP_ENTER: 'confirm',
    pygame.K_m: 'mute',
    pygame.K_0: 'debug',
    pygame.K_LEFTBRACKET: 'sens_down', pygame.K_RIGHTBRACKET: 'sens_up',
    pygame.K_h: 'hero_select',
    pygame.K_x: 'end_match',
}
MOUSEMAP = {1: 'fire', 3: 'alt'}
