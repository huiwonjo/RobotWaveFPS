"""World renderer: walls, Scene, painter/sprite cache, orbs, segments, rings, projection (spec 7.7).

Presentation only. Nothing in here changes gameplay state. The whole world is
drawn into `small` (COLS x H, allocated once) and upscaled into the target.
"""
import math
import random
from collections import namedtuple, OrderedDict

import pygame

from . import config as C
from . import core
from . import theme
from .config import W, H, COLS, FOV, HALF_FOV, MAX_DEPTH, EYE_Z
from .config import FLAG_FLASH, FLAG_STUN, FLAG_DYING, FLAG_NOSHADE   # re-exported
from .world import WALL_GRID

ScreenBox = namedtuple('ScreenBox', 'x0 y0 x1 y1 depth visible')   # 1024x768 coordinates

SPRITE_CACHE_SIZE = 160
MAX_SPRITE_H = int(1.5 * H)
NEAR_CLIP = 0.15
_K_W = COLS / (FOV * H)          # sprite columns per pixel of height, per unit of width/height
_TAU = 2.0 * math.pi


# ============================ scene ==========================================
class Scene:
    """Everything visible in one frame, as plain tuples. POTG stores these and replays them."""
    __slots__ = ('cam', 'now', 'sprites', 'orbs', 'segments', 'rings')

    def __init__(self, cam, now=0.0):
        self.cam = cam                  # (x, y, angle, pitch)
        self.now = now                  # sim time, for emit_visuals flags only
        self.sprites = []
        self.orbs = []
        self.segments = []
        self.rings = []

    def sprite(self, x, y, key, state, height, width, *, z0=0.0, flags=0, elite=False, ref=None):
        self.sprites.append((x, y, key, state, height, width, z0, flags, elite, ref))

    def orb(self, x, y, z, radius, color, core=None):
        self.orbs.append((x, y, z, radius, color, core))

    def segment(self, x1, y1, x2, y2, color_add, *, z0=0.0, z1=0.9, edge=(120, 200, 255), ref=None):
        self.segments.append((x1, y1, x2, y2, color_add, z0, z1, edge, ref))

    def ring(self, x, y, r, color, width=2, n=20):
        self.rings.append((x, y, r, color, width, n))


# ============================ painters =======================================
PAINTERS = {}                   # key -> (fn, base_w, base_h)
_base = {}                      # (key, state, elite, variant) -> Surface at base size
_scaled = OrderedDict()         # (key, state, elite, variant, w, h) -> Surface (LRU)


def register_painter(key, fn, base_w, base_h):
    """fn(surf, state, elite) draws once per (key, state, elite) onto a transparent base_w x base_h surface."""
    PAINTERS[key] = (fn, int(base_w), int(base_h))
    for k in [k for k in _base if k[0] == key]:
        del _base[k]
    for k in [k for k in _scaled if k[0] == key]:
        del _scaled[k]


def _missing_painter(surf, state, elite):
    w, h = surf.get_size()
    surf.fill((255, 0, 255), (0, 0, w, h))


def paint_base(key, state, elite=False, variant=0):
    """Base-size surface for (key, state, elite). variant: 0 plain, 'f' flash, 1 / 2 shaded."""
    k = (key, state, bool(elite), variant)
    s = _base.get(k)
    if s is not None:
        return s
    if variant == 0:
        fn, bw, bh = PAINTERS.get(key) or (_missing_painter, 32, 64)
        s = pygame.Surface((bw, bh), pygame.SRCALPHA)
        fn(s, state, bool(elite))
    else:
        s = paint_base(key, state, elite, 0).copy()
        if variant == 'f':
            s.fill((255, 255, 255), special_flags=pygame.BLEND_RGB_MAX)
        else:
            v = 191 if variant == 1 else 128
            s.fill((v, v, v), special_flags=pygame.BLEND_RGB_MULT)
    _base[k] = s
    return s


def _scaled_surface(key, state, elite, variant, w, h):
    k = (key, state, elite, variant, w, h)
    s = _scaled.get(k)
    if s is not None:
        _scaled.move_to_end(k)
        return s
    s = pygame.transform.scale(paint_base(key, state, elite, variant), (w, h))
    _scaled[k] = s
    if len(_scaled) > SPRITE_CACHE_SIZE:
        _scaled.popitem(last=False)
    return s


def _bucket(h):
    h = int(h) + 1
    if h <= 256:
        b = (h + 7) & ~7
    elif h <= 512:
        b = (h + 15) & ~15
    else:
        b = (h + 31) & ~31
    return 8 if b < 8 else (MAX_SPRITE_H if b > MAX_SPRITE_H else b)


# ============================ lazily built state =============================
_st = {}


def _col_tables():
    offs = [-HALF_FOV + FOV * c / COLS for c in range(COLS)]
    return [math.cos(o) for o in offs], [math.sin(o) for o in offs]


_COL_COS, _COL_SIN = _col_tables()
_LVLS = 64
_LVL_K = (_LVLS - 1) / MAX_DEPTH


def _shade(c, k):
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


def _ensure():
    if _st:
        return _st
    pal = theme.PALETTE
    small = pygame.Surface((COLS, H))
    try:
        small = small.convert()
    except Exception:
        pass
    bg = pygame.Surface((COLS, 2 * H))
    try:
        bg = bg.convert()
    except Exception:
        pass
    sky = pal['sky']
    floor = pal['floor']
    for r in range(H):                      # sky: darker at the top
        k = 0.45 + 0.75 * (r / H) ** 1.5
        bg.fill(_shade(sky, k), (0, r, COLS, 1))
    for r in range(H):                      # floor: dark at the horizon, lighter near the feet
        k = 0.35 + 0.95 * (r / H) ** 0.8
        bg.fill(_shade(floor, min(k, 1.3)), (0, H + r, COLS, 1))
    wa = pal.get('wall_a', (175, 155, 135))
    wb = pal.get('wall_b', (120, 105, 90))
    cols = []
    for base in (wa, wb):
        cols.append([small.map_rgb(_shade(base, max(0.15, 1.0 - (i / _LVL_K) / MAX_DEPTH)))
                     for i in range(_LVLS)])
    _st.update(small=small, bg=bg, zbuf=[MAX_DEPTH] * COLS, wall_cols=cols, big=None, direct=True,
               fx=random.Random(12345))
    return _st


# ============================ walls ==========================================
def _draw_walls(small, zb, px, py, ang, horizon, wall_cols):
    """Flat-shaded walls. Columns are written through a PixelArray: SDL fills of 1-px wide
    rects pay a per-row cost (about 5x slower for tall columns)."""
    ca = math.cos(ang)
    sa = math.sin(ang)
    grid = WALL_GRID
    ccos = _COL_COS
    csin = _COL_SIN
    cola, colb = wall_cols
    mxi = int(px)
    myi = int(py)
    fx = px - mxi
    fy = py - myi
    lvl_k = _LVL_K
    top_lvl = _LVLS - 1
    hh = H
    pa = pygame.PixelArray(small)
    try:
        for col in range(COLS):
            co = ccos[col]
            so = csin[col]
            rx = ca * co - sa * so
            ry = sa * co + ca * so
            if rx < 0:
                ddx = -1.0 / rx
                stx = -1
                sx = fx * ddx
            elif rx > 0:
                ddx = 1.0 / rx
                stx = 1
                sx = (1.0 - fx) * ddx
            else:
                ddx = 1e30
                stx = 1
                sx = 1e30
            if ry < 0:
                ddy = -1.0 / ry
                sty = -1
                sy = fy * ddy
            elif ry > 0:
                ddy = 1.0 / ry
                sty = 1
                sy = (1.0 - fy) * ddy
            else:
                ddy = 1e30
                sty = 1
                sy = 1e30
            mx = mxi
            my = myi
            side = 0
            d = MAX_DEPTH
            for _ in range(80):
                if sx < sy:
                    d = sx
                    sx += ddx
                    mx += stx
                    side = 0
                else:
                    d = sy
                    sy += ddy
                    my += sty
                    side = 1
                if grid[my][mx]:
                    break
            perp = d * co
            if perp < 0.01:
                perp = 0.01
            zb[col] = perp
            half = int(hh / perp) >> 1
            top = horizon - half
            bot = horizon + half
            if top < 0:
                top = 0
            if bot > hh:
                bot = hh
            if bot > top:
                lvl = int(perp * lvl_k)
                if lvl > top_lvl:
                    lvl = top_lvl
                pa[col, top:bot] = (cola if side == 0 else colb)[lvl]
    finally:
        pa.close()


# ============================ projection =====================================
def _cam_tuple(cam):
    if isinstance(cam, tuple):
        return cam
    return (cam.x, cam.y, cam.angle, cam.pitch)


def project_point(cam, x, y, z):
    """(screen x, screen y, depth) in 1024x768 space, or None when depth < 0.15."""
    cx, cy, ang, pitch = _cam_tuple(cam)
    dx = x - cx
    dy = y - cy
    ca = math.cos(ang)
    sa = math.sin(ang)
    d = dx * ca + dy * sa
    if d < NEAR_CLIP:
        return None
    lat = -dx * sa + dy * ca
    col = (0.5 + math.atan2(lat, d) / FOV) * COLS
    horizon = H // 2 + int(pitch)
    return (int(col * C.COL_SCALE), int(horizon + (EYE_Z - z) * H / d), d)


def _ring_pts(n):
    key = ('ring', n)
    t = _st.get(key)
    if t is None:
        t = [(math.cos(_TAU * i / n), math.sin(_TAU * i / n)) for i in range(n + 1)]
        _st[key] = t
    return t


def _draw_ring(small, zb, cx, cy, ca, sa, horizon, ring):
    x, y, r, color, width, n = ring
    n = max(6, int(n))
    prev = None
    line = pygame.draw.line
    for ux, uy in _ring_pts(n):
        dx = x + ux * r - cx
        dy = y + uy * r - cy
        d = dx * ca + dy * sa
        if d < NEAR_CLIP:
            prev = None
            continue
        lat = -dx * sa + dy * ca
        col = (0.5 + math.atan2(lat, d) / FOV) * COLS
        sy = horizon + EYE_Z * H / d
        cur = (col, sy, d)
        if prev is not None:
            mc = int((prev[0] + col) * 0.5)
            if 0 <= mc < COLS and zb[mc] >= (prev[2] + d) * 0.5 and (-COLS < col < 2 * COLS):
                line(small, color, (prev[0], prev[1]), (col, sy), width)
        prev = cur


# ============================ depth-sorted pass ==============================
def _draw_sprite(small, zb, horizon, d, col_c, it, now, proj):
    x, y, key, state, height, width, z0, flags, elite, ref = it
    hpx = height * H / d
    if hpx < 1.0 or height <= 0.0:
        if ref is not None:
            proj[ref] = ScreenBox(0, 0, 0, 0, d, False)
        return
    hb = _bucket(hpx)
    cw = int(hb * width / height * _K_W + 0.5)
    if cw < 1:
        cw = 1
    bottom = horizon + (EYE_Z - z0) * H / d
    top = int(bottom - hb)
    left = int(col_c - cw * 0.5)
    right = left + cw
    visible = False
    if right > 0 and left < COLS and top < H and bottom > 0:
        if flags & FLAG_FLASH:
            variant = 'f'
        elif flags & FLAG_DYING:
            variant = 2
        elif flags & FLAG_NOSHADE:
            variant = 0
        else:
            variant = 0 if d < 6.0 else (1 if d < 12.0 else 2)
        img = None
        run = -1
        c0 = left if left > 0 else 0
        c1 = right if right < COLS else COLS
        for c in range(c0, c1):
            if zb[c] > d:
                if run < 0:
                    run = c
            elif run >= 0:
                if img is None:
                    img = _scaled_surface(key, state, elite, variant, cw, hb)
                small.blit(img, (run, top), (run - left, 0, c - run, hb))
                visible = True
                run = -1
        if run >= 0:
            if img is None:
                img = _scaled_surface(key, state, elite, variant, cw, hb)
            small.blit(img, (run, top), (run - left, 0, c1 - run, hb))
            visible = True
    if ref is not None:
        s = C.COL_SCALE
        proj[ref] = ScreenBox(int(left * s), top, int(right * s), top + hb, d, visible)


def _draw_orb(small, zb, horizon, d, col_c, it):
    x, y, z, radius, color, core_col = it
    col = int(col_c)
    if col < 0 or col >= COLS or zb[col] <= d:
        return
    R = radius * H / d
    if R < 1.0:
        R = 1.0
    elif R > 80.0:
        R = 80.0
    cy = horizon + (EYE_Z - z) * H / d
    if R <= 1.6:
        small.fill(color, (col, int(cy - R), 1, int(2 * R) or 1))
        return
    rw = 2.0 * R / C.COL_SCALE
    if rw < 1.0:
        rw = 1.0
    pygame.draw.ellipse(small, color, (int(col_c - rw * 0.5), int(cy - R), int(rw) or 1, int(2 * R)))
    if core_col is not None and R >= 3.0:
        r2 = R * 0.55
        rw2 = max(1.0, rw * 0.55)
        pygame.draw.ellipse(small, core_col, (int(col_c - rw2 * 0.5), int(cy - r2), int(rw2) or 1, int(2 * r2)))


def _draw_segment(small, zb, horizon, cx, cy, ca, sa, it):
    """Barrier segment as additive column spans; adjacent columns with (almost) the same
    top/bottom are merged into one rect so the blended fill is paid per run, not per column."""
    x1, y1, x2, y2, color_add, z0, z1, edge, ref = it
    cols = []
    for (px, py) in ((x1, y1), (x2, y2)):
        dx = px - cx
        dy = py - cy
        d = dx * ca + dy * sa
        lat = -dx * sa + dy * ca
        cols.append((0.5 + math.atan2(lat, d) / FOV) * COLS)
    c0 = int(max(0.0, min(cols)))
    c1 = int(min(COLS - 1.0, max(cols)))
    if c1 < c0:
        return
    sxs = x2 - x1
    sys_ = y2 - y1
    qx = x1 - cx
    qy = y1 - cy
    fill = small.fill
    add = pygame.BLEND_RGB_ADD
    ccos = _COL_COS
    csin = _COL_SIN
    run0 = -1
    last = -2
    rt = rb = 0
    for c in range(c0, c1 + 2):
        ok = False
        if c <= c1:
            co = ccos[c]
            so = csin[c]
            rx = ca * co - sa * so
            ry = sa * co + ca * so
            den = rx * sys_ - ry * sxs
            if not (-1e-12 < den < 1e-12):
                t = (qx * sys_ - qy * sxs) / den
                u = (qx * ry - qy * rx) / den
                if t > 0.0 and 0.0 <= u <= 1.0:
                    depth = t * co
                    if depth >= 0.05 and zb[c] >= depth:
                        k = H / depth
                        yt = int(horizon + (EYE_Z - z1) * k)
                        yb = int(horizon + (EYE_Z - z0) * k)
                        ok = yb > yt
        if ok and run0 >= 0 and c == last + 1 and -2 <= yt - rt <= 2 and -2 <= yb - rb <= 2:
            last = c
            continue
        if run0 >= 0:
            wdt = last - run0 + 1
            fill(color_add, (run0, rt, wdt, rb - rt), add)
            fill(edge, (run0, rt, wdt, 1))
            fill(edge, (run0, rb - 1, wdt, 1))
            run0 = -1
        if ok:
            run0 = last = c
            rt = yt
            rb = yb


def draw_scene(surf, scene):
    """Draw walls from scene.cam plus every scene item into surf. Returns {ref: ScreenBox}."""
    st = _ensure()
    small = st['small']
    zb = st['zbuf']
    cx, cy, ang, pitch = scene.cam
    horizon = H // 2 + int(pitch)
    small.blit(st['bg'], (0, horizon - H))
    _draw_walls(small, zb, cx, cy, ang, horizon, st['wall_cols'])
    ca = math.cos(ang)
    sa = math.sin(ang)
    for rg in scene.rings:
        _draw_ring(small, zb, cx, cy, ca, sa, horizon, rg)

    items = []
    now = scene.now
    atan2 = math.atan2
    lo = -0.5 * COLS
    hi = 1.5 * COLS
    orbs = scene.orbs
    stun_orbs = None
    for it in scene.sprites:
        if it[7] & FLAG_STUN:
            if stun_orbs is None:
                stun_orbs = []
            zt = it[6] + it[4] + 0.08
            rr = max(0.12, it[5] * 0.45)
            for k in range(3):
                a = now * 4.0 + k * 2.094
                stun_orbs.append((it[0] + math.cos(a) * rr, it[1] + math.sin(a) * rr, zt, 0.035,
                                  (255, 230, 60), None))
    if stun_orbs:
        orbs = orbs + stun_orbs
    for kind, lst in ((0, scene.sprites), (1, orbs)):
        for it in lst:
            dx = it[0] - cx
            dy = it[1] - cy
            d = dx * ca + dy * sa
            if d < NEAR_CLIP or d > MAX_DEPTH + 2:
                if kind == 0 and it[9] is not None:
                    items.append((-1.0, 3, it, 0.0))
                continue
            col_c = (0.5 + atan2(-dx * sa + dy * ca, d) / FOV) * COLS
            if col_c < lo or col_c > hi:
                if kind == 0 and it[9] is not None:
                    items.append((-1.0, 3, it, d))
                continue
            items.append((d, kind, it, col_c))
    for it in scene.segments:
        mx = (it[0] + it[2]) * 0.5 - cx
        my = (it[1] + it[3]) * 0.5 - cy
        items.append((mx * ca + my * sa, 2, it, 0.0))
    items.sort(key=lambda t: -t[0])

    proj = {}
    for d, kind, it, extra in items:
        if kind == 0:
            _draw_sprite(small, zb, horizon, d, extra, it, now, proj)
        elif kind == 1:
            _draw_orb(small, zb, horizon, d, extra, it)
        elif kind == 2:
            _draw_segment(small, zb, horizon, cx, cy, ca, sa, it)
        else:
            proj[it[9]] = ScreenBox(0, 0, 0, 0, extra, False)
    _upscale(small, surf, st)
    return proj


def _upscale(small, surf, st):
    if surf.get_size() == (W, H) and st['direct']:
        try:
            pygame.transform.scale(small, (W, H), surf)
            return
        except Exception:
            st['direct'] = False
    size = surf.get_size()
    big = st['big']
    if big is None or big.get_size() != size:
        big = pygame.Surface(size)
        st['big'] = big
    pygame.transform.scale(small, size, big)
    surf.blit(big, (0, 0))


def build_scene(world):
    cam = world.cam
    sc = Scene((cam.x, cam.y, cam.angle, cam.pitch), world.now)
    for e in world.enemies:
        e.emit_visuals(sc)
    for pk in world.packs:
        pk.emit_visuals(sc)
    for pr in world.projectiles:
        if not pr.alive:
            continue
        if pr.draw is not None:
            pr.draw(sc, pr)
        else:
            sc.orb(pr.x, pr.y, pr.z, pr.size, pr.color, pr.core)
    for b in world.barriers:
        if b.active and not b.owner_view_only:
            sc.segment(b.x1, b.y1, b.x2, b.y2, b.color_add)
    for ef in world.effects:
        ef.emit_visuals(sc)
    world.director.emit_visuals(sc)
    world.player.emit_visuals(sc)
    for q in world.particles:
        sc.orb(q.x, q.y, q.z, q.size * 0.012, q.color)
    return sc


def render_frame(surf, world):
    """build + draw + world.projection + shake; returns the Scene (for POTG)."""
    sc = build_scene(world)
    world.projection = draw_scene(surf, sc)
    cam = world.cam
    if cam.shake_left > 0.0 and cam.shake_amp >= 1.0:
        a = int(cam.shake_amp)
        fx = _st['fx']
        surf.scroll(fx.randint(-a, a), fx.randint(-a, a))
    return sc


# ============================ foundation painters ============================
def _paint_pack(big):
    def fn(surf, state, elite):
        w, h = surf.get_size()
        body = pygame.Rect(2, int(h * 0.30), w - 4, int(h * 0.70) - 2)
        pygame.draw.rect(surf, (225, 232, 240), body, border_radius=4)
        pygame.draw.rect(surf, (120, 140, 160), body, 2, border_radius=4)
        bw = max(3, w // 6)
        cxm = w // 2
        cym = body.centery
        arm = int(body.height * 0.34)
        blue = (40, 120, 255) if big else (60, 150, 255)
        surf.fill(blue, (cxm - bw // 2, cym - arm, bw, arm * 2))
        surf.fill(blue, (cxm - arm, cym - bw // 2, arm * 2, bw))
    return fn


def _paint_dummy(surf, state, elite):
    w, h = surf.get_size()
    pygame.draw.rect(surf, (90, 96, 110), (w * 0.2, h * 0.22, w * 0.6, h * 0.5), border_radius=4)
    pygame.draw.rect(surf, (120, 128, 140), (w * 0.3, 2, w * 0.4, h * 0.2), border_radius=3)
    surf.fill((255, 200, 60), (w * 0.34, h * 0.07, w * 0.32, h * 0.06))
    surf.fill((70, 74, 84), (w * 0.44, h * 0.72, w * 0.12, h * 0.28))
    pygame.draw.circle(surf, (230, 60, 50), (w // 2, int(h * 0.45)), int(w * 0.18), 3)
    if elite:
        pygame.draw.rect(surf, C.COL_ELITE, (w * 0.2, h * 0.22, w * 0.6, h * 0.5), 2, border_radius=4)


register_painter('pack_small', _paint_pack(False), 32, 32)
register_painter('pack_big', _paint_pack(True), 40, 40)
register_painter('dummy', _paint_dummy, 48, 96)


# ============================ app-level overlays (presentation) ==============
def draw_debug(surf, lines, pos=(12, 210)):
    """Debug overlay (key 0): a darkened box and cached text lines."""
    x, y = pos
    wmax = 0
    surfs = [core.text(s, 'xs', (200, 255, 200)) for s in lines]
    for t in surfs:
        wmax = max(wmax, t.get_width())
    surf.fill((70, 70, 70), (x - 6, y - 4, wmax + 12, 18 * len(surfs) + 8), pygame.BLEND_RGB_MULT)
    for i, t in enumerate(surfs):
        surf.blit(t, (x, y + i * 18))


def draw_toast(surf, msg):
    t = core.text(msg, 'm', (255, 255, 255))
    x = W // 2 - t.get_width() // 2
    y = 560
    surf.fill((60, 60, 60), (x - 10, y - 4, t.get_width() + 20, t.get_height() + 8), pygame.BLEND_RGB_MULT)
    surf.blit(t, (x, y))
