"""RAMPART (HERO_C owns this file). Phase 0 STUB by FOUNDATION.

Final class attributes (spec 3.4) and working slots; the real kit (hammer
viewmodel, hex barrier overlay, Charge pin/carry, Flame Strike visuals, Quake
wave effect, icons) is HERO_C's job.
"""
import math

import pygame

from . import config as C
from . import core
from .combat import Barrier, Projectile, apply_damage, cone_targets, knockback
from .config import TEAM_PLAYER
from .hero_base import Ability, Hero
from .world import dash_target

TUNING = {
    'hammer_damage': 80.0, 'hammer_reach': 2.5, 'hammer_arc_deg': 45.0, 'hammer_interval': 0.9,
    'barrier_hp': 600.0, 'barrier_regen': 150.0, 'barrier_regen_delay': 2.0, 'barrier_lockout': 5.0,
    'barrier_dist': 1.0, 'barrier_half_width': 1.2, 'barrier_speed_mult': 0.7,
    'charge_cd': 7.0, 'flame_damage': 90.0, 'flame_speed': 14.0, 'flame_range': 12.0, 'flame_cd': 6.0,
    'quake_damage': 120.0, 'quake_len': 8.0, 'quake_stun': 2.5, 'quake_root': 0.6,
}


@core.register_hero
class Rampart(Hero):
    KEY = 'rampart'
    NAME = 'RAMPART'
    ROLE = 'TANK'
    DIFFICULTY = 2
    COLOR = (230, 180, 60)
    BLURB = 'Hold the line. Hammer, shield, charge.'
    KIT = (('LMB', 'ROCKET HAMMER', 'Wide melee swings.'),
           ('RMB/F', 'BARRIER (HOLD)', 'A big shield in front of you.'),
           ('SHIFT', 'CHARGE', 'Rush forward and pin an enemy.'),
           ('E', 'FLAME STRIKE', 'Piercing fire projectile.'),
           ('Q', 'QUAKE SLAM', 'Stun everything in front of you.'))
    LABELS = {'primary': 'HAMMER', 'ab1': 'CHARGE', 'ab2': 'FLAME STRIKE', 'ult': 'QUAKE', 'melee': 'MELEE'}
    HEALTH = 300
    ARMOR = 200
    SHIELDS = 0
    SPEED = 3.9
    ULT_COST = 1400
    ULT_NAME = 'QUAKE SLAM'
    ULT_CALLOUT = 'QUAKE!'
    ULT_DURATION = 0.0
    MAX_AMMO = 0
    RELOAD_TIME = 0.0
    HUD_ORDER = ('ab1', 'ab2', 'secondary')

    def __init__(self, world):
        super().__init__(world)
        self.abilities = {
            'secondary': Ability(self, 'secondary', 'BARRIER', 'RMB', TUNING['barrier_lockout']),
            'ab1': Ability(self, 'ab1', 'CHARGE', 'SHIFT', TUNING['charge_cd']),
            'ab2': Ability(self, 'ab2', 'FLAME STRIKE', 'E', TUNING['flame_cd'], charges=2),
        }
        self.barrier = Barrier(TEAM_PLAYER, TUNING['barrier_hp'], TUNING['barrier_half_width'], owner=self)
        self.barrier.owner_view_only = True
        self.barrier_up = False
        self._lowered_at = -9.0
        self._next_swing = 0.0
        self.abilities['secondary'].meter = 1.0

    def on_input(self, inp, world):
        now = world.now
        sec = self.abilities['secondary']
        want = inp.down('alt')
        if want and not self.barrier_up and sec.charges > 0 and self.barrier.hp >= 1.0:
            self._raise(world)
        elif not want and self.barrier_up:
            self._lower(world)
        if self.barrier_up:
            self.speed_mult *= TUNING['barrier_speed_mult']
        if inp.hit('ab1') and not self.barrier_up and self.abilities['ab1'].use(world):
            self.x, self.y = dash_target(self.x, self.y, self.angle, 3.0)     # stub: short dash
        if inp.hit('ab2') and self.abilities['ab2'].use(world):
            self._flame(world)
        if inp.down('fire') and not self.barrier_up and now >= self._next_swing:
            self._next_swing = now + TUNING['hammer_interval']
            self._swing(world)

    def _raise(self, world):
        b = self.barrier
        b.active = True
        if world.add_barrier(b):
            self.barrier_up = True
            world.bus.emit('ability_used', hero=self.KEY, slot='secondary', name='BARRIER')

    def _lower(self, world):
        self.barrier_up = False
        self._lowered_at = world.now
        world.remove_barrier(self.barrier)

    def _swing(self, world):
        self.last_fire = world.now
        world.bus.emit('ability_used', hero=self.KEY, slot='primary', name='HAMMER')
        for e in cone_targets(world, self.x, self.y, self.angle, math.radians(TUNING['hammer_arc_deg']),
                              TUNING['hammer_reach']):
            apply_damage(world, e, TUNING['hammer_damage'], self, ability='primary', from_xy=(self.x, self.y))
            knockback(world, e, self.x, self.y, 0.6)

    def _flame(self, world):
        a = self.angle
        sp = TUNING['flame_speed']
        p = Projectile(self.x, self.y, a, sp, team=TEAM_PLAYER, damage=TUNING['flame_damage'], radius=0.35,
                       owner=self, ability='ab2', ttl=TUNING['flame_range'] / sp, z=0.4, color=(255, 120, 30),
                       core=(255, 230, 120), size=0.18, pierce=True, through_barriers=True)
        world.add_projectile(p)

    def on_ult(self, world):
        now = world.now
        self.status.add('root', TUNING['quake_root'], now)
        world.shake(12, 0.4)
        for e in cone_targets(world, self.x, self.y, self.angle, math.radians(30), TUNING['quake_len']):
            apply_damage(world, e, TUNING['quake_damage'], self, ability='ult', from_xy=(self.x, self.y))
            if e.alive:
                e.status.add('stun', TUNING['quake_stun'] * e.STUN_MULT, now)

    def think(self, world, dt):
        b = self.barrier
        sec = self.abilities['secondary']
        if self.barrier_up and not b.active:          # broken
            self.barrier_up = False
            self._lowered_at = world.now
            world.remove_barrier(b)
            sec.start_cooldown(TUNING['barrier_lockout'])
        if not self.barrier_up and sec.charges > 0 and world.now - self._lowered_at >= TUNING['barrier_regen_delay']:
            b.hp = min(b.max_hp, b.hp + TUNING['barrier_regen'] * dt)
        sec.meter = b.hp / b.max_hp

    def after_move(self, world, dt):
        if self.barrier_up:
            d = TUNING['barrier_dist']
            self.barrier.set_pose(self.x + math.cos(self.angle) * d, self.y + math.sin(self.angle) * d, self.angle)

    def on_removed(self, world):
        world.remove_barrier(self.barrier)
        self.barrier_up = False

    def restore(self, world):
        super().restore(world)
        self.barrier.hp = self.barrier.max_hp
        self.barrier.active = True

    def draw_viewmodel(self, surf, world):
        swing = world.now - self.last_fire
        off = int(max(0.0, 0.3 - swing) / 0.3 * 200) if swing < 0.3 else 0
        surf.fill((110, 110, 120), (760 - off, 560, 16, 208))
        surf.fill((150, 120, 60), (700 - off, 520, 150, 90))

    def draw_overlay(self, surf, world):
        if self.barrier_up:
            surf.fill((0, 15, 35), None, pygame.BLEND_RGB_ADD)
            b = self.barrier
            surf.fill((30, 40, 60), (412, 300, 200, 6))
            surf.fill((120, 200, 255), (412, 300, int(200 * b.hp / b.max_hp), 6))

    def draw_crosshair(self, surf, world):
        cx, cy = C.W // 2, C.H // 2
        surf.fill((255, 255, 255), (cx - 1, cy - 1, 3, 3))
        pygame.draw.arc(surf, (255, 255, 255), (cx - 60, cy - 60, 120, 120), math.radians(200), math.radians(340), 1)
