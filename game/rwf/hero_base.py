"""Ability, AbilityHUD, HeroHUD and the Hero base class (spec 3.0, 7.4).

Builders subclass Hero and override only: on_input, think, after_move, on_ult,
on_removed, draw_viewmodel, draw_overlay, draw_crosshair, draw_icon (classmethod),
emit_visuals (and optionally on_ult_end / restore, calling super()).
Never override handle_input or update.

Per frame (World.update step 2): pool.update -> handle_input -> update.
handle_input: speed_mult = 1, custom_motion = False, look (turn_limit, rad/s), axes;
then, only while can_act (alive, not stunned/pinned, lock_input False): Q try_ult,
R reload, V quick melee, auto-reload on an empty mag with fire held, on_input.
update: abilities, reload, melee timer, ult timer (-> 'ult_end' + on_ult_end),
passive ult while director.in_combat, think, move (unless custom_motion), after_move.
"""
import math
from collections import namedtuple

import pygame

from . import config as C
from . import core
from . import theme
from .combat import Entity, HealthPool, StatusSet, apply_damage, cone_targets, hitscan, knockback, spark
from .config import TEAM_PLAYER, CRIT_MULT, MAX_DEPTH
from .world import move_slide

AbilityHUD = namedtuple('AbilityHUD', 'slot name key cd_left cd_frac charges max_charges active active_frac meter usable')
HeroHUD = namedtuple('HeroHUD', 'key name color health max_health armor max_armor shields max_shields ammo max_ammo '
                                'reloading reload_frac abilities ult_frac ult_ready ult_active_frac statuses')


class Ability:
    """A cooldown/charges slot ('secondary', 'ab1' or 'ab2').

    use() consumes a charge and starts the recharge (cooldown 0 = never consumed).
    Charges come back one after another, each `cooldown` seconds, emitting
    'ability_ready'. start(duration)/stop() drive the 'active' state (e.g. sprint,
    rewind travel). start_cooldown(s) puts the slot on cooldown now for s seconds
    (a single-charge ability loses its charge). meter (None or 0..1) feeds the HUD.
    """

    def __init__(self, hero, slot, name, key_label, cooldown, charges=1, duration=0.0):
        self.hero = hero
        self.slot = slot
        self.name = name
        self.key_label = key_label
        self.cooldown = float(cooldown)
        self.max_charges = int(charges)
        self.charges = int(charges)
        self.recharge_left = 0.0
        self.duration = float(duration)
        self.active_left = 0.0
        self.meter = None

    @property
    def active(self):
        return self.active_left > 0.0

    @property
    def cd_frac(self):
        if self.charges >= self.max_charges or self.cooldown <= 0:
            return 0.0
        return core.clamp(self.recharge_left / self.cooldown, 0.0, 1.0)

    def ready(self):
        h = self.hero
        return self.charges > 0 and h.can_act(h.world)

    def use(self, world):
        if not self.ready():
            return False
        if self.cooldown > 0:
            if self.charges >= self.max_charges:
                self.recharge_left = self.cooldown
            self.charges -= 1
        world.bus.emit('ability_used', hero=self.hero.KEY, slot=self.slot, name=self.name)
        return True

    def start(self, duration=None):
        self.active_left = self.duration if duration is None else float(duration)

    def stop(self):
        self.active_left = 0.0

    def start_cooldown(self, seconds):
        self.recharge_left = float(seconds)
        if self.max_charges == 1:
            self.charges = 0
        elif self.charges >= self.max_charges:
            self.charges = self.max_charges - 1

    def update(self, world, dt):
        if self.active_left > 0.0:
            self.active_left = max(0.0, self.active_left - dt)
        if self.charges >= self.max_charges:
            self.recharge_left = 0.0
            return
        if world.debug.get('no_cooldowns'):
            self.recharge_left = 0.0
            self.charges = self.max_charges
            world.bus.emit('ability_ready', hero=self.hero.KEY, slot=self.slot, name=self.name)
            return
        self.recharge_left -= dt
        if self.recharge_left <= 0.0:
            self.charges += 1
            if self.charges < self.max_charges:
                self.recharge_left += self.cooldown
                if self.recharge_left < 0.0:
                    self.recharge_left = 0.0
            else:
                self.recharge_left = 0.0
            world.bus.emit('ability_ready', hero=self.hero.KEY, slot=self.slot, name=self.name)

    def reset(self):
        self.charges = self.max_charges
        self.recharge_left = 0.0
        self.active_left = 0.0

    def hud(self):
        cd_left = self.recharge_left if self.charges < self.max_charges else 0.0
        af = (self.active_left / self.duration) if self.duration > 0 else (1.0 if self.active_left > 0 else 0.0)
        return AbilityHUD(self.slot, self.name, self.key_label, cd_left, self.cd_frac, self.charges,
                          self.max_charges, self.active, core.clamp(af, 0.0, 1.0), self.meter, self.ready())


class Hero(Entity):
    KEY = 'hero'
    NAME = 'HERO'
    ROLE = 'DAMAGE'
    DIFFICULTY = 1
    COLOR = (200, 200, 200)
    BLURB = ''
    KIT = ()                    # ((key, name, one-line), ...)
    LABELS = {}
    HEALTH = 200
    ARMOR = 0
    SHIELDS = 0
    SPEED = 4.0
    ULT_COST = 1500
    ULT_NAME = 'ULT'
    ULT_CALLOUT = 'ULT!'
    ULT_DURATION = 0.0
    MAX_AMMO = 0
    RELOAD_TIME = 0.0
    HUD_ORDER = ('ab1', 'ab2')
    radius = C.PLAYER_RADIUS
    height = 0.9
    width = 0.5

    def __init__(self, world):
        super().__init__()
        self.world = world
        self.team = TEAM_PLAYER
        self.pool = HealthPool(self.HEALTH, self.ARMOR, self.SHIELDS)
        self.status = StatusSet()
        self.alive = True
        self.knockback_immune = False
        self.angle = 0.0
        self.pitch = 0.0
        self.ammo = self.MAX_AMMO
        self.reloading = False
        self.reload_left = 0.0
        self._reload_frame = -1     # world.frame the reload started in (that frame's dt doesn't count)
        self.ult_charge = 0.0
        self.ult_active_left = 0.0
        self.move_fwd = 0
        self.move_right = 0
        self.speed_mult = 1.0
        self.custom_motion = False
        self.turn_limit = None      # rad/s, or None
        self.lock_input = False
        self.last_fire = -9.0
        self.melee_left = 0.0
        self.last_melee = -9.0
        self.abilities = {}

    # --- properties -------------------------------------------------------------
    @property
    def ult_frac(self):
        return core.clamp(self.ult_charge / self.ULT_COST, 0.0, 1.0) if self.ULT_COST > 0 else 0.0

    @property
    def ult_ready(self):
        return self.ult_charge >= self.ULT_COST or bool(self.world.debug.get('inf_ult'))

    def can_act(self, world):
        return self.alive and not self.lock_input and self.status.can_act(world.now)

    # --- input / update (not overridden) -------------------------------------------
    def handle_input(self, inp, world):
        self.speed_mult = 1.0
        self.custom_motion = False
        sens = getattr(inp, 'sens', 1.0)
        dyaw = inp.mouse_dx * C.MOUSE_YAW * sens
        if self.turn_limit is not None:
            lim = self.turn_limit * max(world.dt, 1e-6)
            dyaw = core.clamp(dyaw, -lim, lim)
        self.angle = core.wrap_angle(self.angle + dyaw)
        self.pitch = core.clamp(self.pitch - inp.mouse_dy * C.MOUSE_PITCH * sens, -C.PITCH_LIMIT, C.PITCH_LIMIT)
        if self.lock_input:
            self.move_fwd = self.move_right = 0
            return
        self.move_fwd, self.move_right = inp.axes()
        if not self.can_act(world):
            return
        if inp.hit('ult'):
            self.try_ult(world)
        if inp.hit('reload'):
            self.start_reload(world)
        if inp.hit('melee'):
            self.quick_melee(world)
        if (self.MAX_AMMO > 0 and self.ammo <= 0 and not self.reloading and inp.down('fire')
                and self.ult_active_left <= 0):
            self.start_reload(world)
        self.on_input(inp, world)

    def update(self, world, dt):
        for ab in self.abilities.values():
            ab.update(world, dt)
        if self.reloading and world.frame != self._reload_frame:
            self.reload_left -= dt
            if self.reload_left <= 1e-9:            # float sums: 30 x (1/30) must finish a 1.0 s reload
                self.reloading = False
                self.reload_left = 0.0
                self.ammo = self.MAX_AMMO
        if self.melee_left > 0.0:
            self.melee_left = max(0.0, self.melee_left - dt)
        if self.ult_active_left > 0.0:
            self.ult_active_left -= dt
            if self.ult_active_left <= 0.0:
                self.ult_active_left = 0.0
                world.bus.emit('ult_end', hero=self.KEY)
                self.on_ult_end(world)
        if world.director.in_combat:
            self.add_ult(C.ULT_PASSIVE_RATE * dt)
        self.think(world, dt)
        if not self.custom_motion:
            self.move(world, dt)
        self.after_move(world, dt)

    def move(self, world, dt):
        now = world.now
        if not self.status.can_move(now):
            return
        f = self.move_fwd
        r = self.move_right
        if not f and not r:
            return
        a = self.angle
        ca = math.cos(a)
        sa = math.sin(a)
        vx = ca * f - sa * r
        vy = sa * f + ca * r
        m = math.hypot(vx, vy)
        sp = self.SPEED * self.speed_mult * self.status.speed_mult(now) * dt / m
        self.x, self.y = move_slide(self.x, self.y, vx * sp, vy * sp, self.radius)

    # --- shared actions -------------------------------------------------------------
    def fire_hitscan(self, world, damage, *, spread=0.0, falloff=None, ability='primary', angle=None, pitch=None,
                     allow_crit=True, used_slot='primary'):
        """One hitscan trace. falloff = (full_until, zero_at, min_mult). Applies falloff, then crit.

        angle / pitch default to the view; pass them to aim elsewhere (e.g. an auto-aim ult).
        allow_crit=False: never crits (no x2, crit False in 'damage' / 'shot' and on the returned Hit),
        e.g. VECTOR Lock-On. Emits 'shot', then 'ability_used' with slot used_slot and name
        label_for(used_slot); used_slot=None skips 'ability_used' (e.g. extra traces of one shot)."""
        rng = world.rng
        ang = self.angle if angle is None else angle
        pitch = self.pitch if pitch is None else pitch
        if spread > 0:
            ang += rng.uniform(-spread, spread)
            pitch += rng.uniform(-spread * C.H, spread * C.H)
        hit = hitscan(world, self, ang, pitch)
        if not allow_crit:
            hit.crit = False
        self.last_fire = world.now
        if hit.kind == 'enemy':
            dmg = float(damage)
            if falloff is not None:
                full, zero_at, min_mult = falloff
                if hit.dist > full:
                    k = min(1.0, (hit.dist - full) / max(1e-6, zero_at - full))
                    dmg *= 1.0 - (1.0 - min_mult) * k
            if hit.crit:
                dmg *= CRIT_MULT
            apply_damage(world, hit.target, dmg, self, ability=ability, crit=hit.crit, from_xy=(self.x, self.y))
        elif hit.kind == 'barrier':
            hit.target.take(world, float(damage), self)
            spark(world, hit.x, hit.y, hit.z, (120, 200, 255), 2)
        elif hit.kind == 'wall':
            if 0.0 <= hit.z <= 1.0:
                spark(world, hit.x - math.cos(ang) * 0.05, hit.y - math.sin(ang) * 0.05, hit.z, (255, 220, 150), 2)
        world.bus.emit('shot', hero=self.KEY, hit=hit.kind == 'enemy', crit=bool(hit.crit), kind=hit.kind,
                       x=hit.x, y=hit.y)
        if used_slot:
            world.bus.emit('ability_used', hero=self.KEY, slot=used_slot, name=self.label_for(used_slot))
        return hit

    def quick_melee(self, world):
        """V: 40 damage to the nearest enemy within reach 1.5 and +-30 deg (LOS), 0.8 s cooldown."""
        if self.melee_left > 0.0:
            return
        self.melee_left = 0.8
        self.last_melee = world.now
        world.bus.emit('ability_used', hero=self.KEY, slot='melee', name='MELEE')
        tg = cone_targets(world, self.x, self.y, self.angle, math.radians(30), 1.5)
        if tg:
            e = tg[0]
            apply_damage(world, e, 40.0, self, ability='melee', from_xy=(self.x, self.y))
            if not getattr(e, 'BOSS', False):
                knockback(world, e, self.x, self.y, 0.3)

    def start_reload(self, world):
        if self.MAX_AMMO <= 0 or self.reloading or self.ammo >= self.MAX_AMMO:
            return
        self.reloading = True
        self.reload_left = self.RELOAD_TIME
        # started during this frame's input: RELOAD_TIME counts from the next frame, so a 1.0 s reload at
        # 30 fps takes 30 frames (not 29, which it did when the start frame's dt was counted too)
        self._reload_frame = world.frame

    def cancel_reload(self):
        self.reloading = False
        self.reload_left = 0.0

    def use_ammo(self, n=1):
        if self.MAX_AMMO <= 0:
            return True
        if self.reloading or self.ammo < n:
            return False
        self.ammo -= n
        return True

    def add_ult(self, pts, ignore_lock=False):
        if pts <= 0 or self.ULT_COST <= 0:
            return
        if self.ult_active_left > 0.0 and not ignore_lock:
            return
        was = self.ult_charge >= self.ULT_COST
        self.ult_charge = min(float(self.ULT_COST), self.ult_charge + pts)
        if not was and self.ult_charge >= self.ULT_COST:
            self.world.bus.emit('ult_ready', hero=self.KEY)

    def try_ult(self, world):
        if not self.can_act(world):
            return False
        if self.ult_charge < self.ULT_COST and not world.debug.get('inf_ult'):
            return False
        if self.ult_active_left > 0.0 and not world.debug.get('inf_ult'):
            return False
        self.ult_charge = 0.0
        self.ult_active_left = self.ULT_DURATION
        world.bus.emit('ult_used', hero=self.KEY, name=self.ULT_NAME, callout=self.ULT_CALLOUT)
        self.on_ult(world)
        return True

    def restore(self, world):
        """Stage clear: full pools, cooldowns/charges reset, ammo refilled; ult kept."""
        self.pool.refill()
        for ab in self.abilities.values():
            ab.reset()
        self.ammo = self.MAX_AMMO
        self.reloading = False
        self.reload_left = 0.0

    def hud_state(self, world):
        p = self.pool
        abil = [self.abilities[k].hud() for k in self.HUD_ORDER if k in self.abilities]
        rf = 0.0
        if self.reloading and self.RELOAD_TIME > 0:
            rf = core.clamp(1.0 - self.reload_left / self.RELOAD_TIME, 0.0, 1.0)
        uaf = (self.ult_active_left / self.ULT_DURATION) if self.ULT_DURATION > 0 else 0.0
        return HeroHUD(self.KEY, self.NAME, self.COLOR, p.health, p.max_health, p.armor, p.max_armor,
                       p.shields, p.max_shields, self.ammo, self.MAX_AMMO, self.reloading, rf, abil,
                       self.ult_frac, self.ult_ready, core.clamp(uaf, 0.0, 1.0), self.status.active(world.now))

    def label_for(self, ability):
        if ability == 'melee':
            return self.LABELS.get('melee', 'MELEE')
        if ability == 'chain':
            return self.LABELS.get('chain', theme.enemy_name('detonator'))
        return self.LABELS.get(ability, str(ability).upper())

    # --- overridden by HERO_A / HERO_B / HERO_C ----------------------------------------
    def on_input(self, inp, world):
        pass

    def think(self, world, dt):
        pass

    def after_move(self, world, dt):
        pass

    def on_ult(self, world):
        pass

    def on_ult_end(self, world):
        pass

    def on_removed(self, world):
        pass

    def draw_viewmodel(self, surf, world):
        pass

    def draw_overlay(self, surf, world):
        pass

    def draw_crosshair(self, surf, world):
        cx, cy = C.W // 2, C.H // 2
        surf.fill((255, 255, 255), (cx - 1, cy - 1, 3, 3))

    @classmethod
    def draw_icon(cls, slot, surf, rect):
        rect = pygame.Rect(rect)
        pygame.draw.rect(surf, cls.COLOR, rect, 2, border_radius=6)
        letter = {'portrait': cls.NAME[:1], 'secondary': 'R', 'ab1': 'S', 'ab2': 'E', 'ult': 'Q'}.get(slot, '?')
        t = core.text(letter, 'l' if rect.h >= 80 else 'm', cls.COLOR)
        surf.blit(t, (rect.centerx - t.get_width() // 2, rect.centery - t.get_height() // 2))

    def emit_visuals(self, scene):
        pass
