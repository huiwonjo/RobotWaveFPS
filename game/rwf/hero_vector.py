"""VECTOR (HERO_A owns this file). Phase 0 STUB by FOUNDATION.

Final class attributes (spec 3.4) and working slots; the real kit (spread,
sprint latch rules, Heal Field effect, Lock-On, heal_pylon painter, proper
viewmodel and icons) is HERO_A's job.
"""
import math

import pygame

from . import config as C
from . import core
from .combat import Projectile, heal
from .config import TEAM_PLAYER
from .hero_base import Ability, Hero

TUNING = {
    'rifle_damage': 19.0, 'rifle_interval': 0.111,
    'helix_direct': 40.0, 'helix_center': 80.0, 'helix_edge': 40.0, 'helix_radius': 1.5,
    'helix_speed': 16.0, 'helix_cd': 6.0, 'sprint_mult': 1.5, 'heal_cd': 15.0, 'lockon_time': 6.0,
}


@core.register_hero
class Vector(Hero):
    KEY = 'vector'
    NAME = 'VECTOR'
    ROLE = 'DAMAGE'
    DIFFICULTY = 1
    COLOR = (80, 150, 255)
    BLURB = 'Versatile rifleman. Rockets, sprint, self-heal.'
    KIT = (('LMB', 'PULSE RIFLE', 'Full-auto hitscan rifle.'),
           ('RMB/F', 'HELIX ROCKETS', 'Three rockets with splash.'),
           ('SHIFT', 'SPRINT', 'Run faster while moving forward.'),
           ('E', 'HEAL FIELD', 'Drop a field that heals you.'),
           ('Q', 'LOCK-ON', 'Your shots auto-aim for 6 s.'))
    LABELS = {'primary': 'PULSE RIFLE', 'secondary': 'HELIX', 'ult': 'LOCK-ON', 'melee': 'MELEE'}
    HEALTH = 200
    ARMOR = 0
    SHIELDS = 0
    SPEED = 4.2
    ULT_COST = 1500
    ULT_NAME = 'LOCK-ON'
    ULT_CALLOUT = 'LOCKED ON!'
    ULT_DURATION = TUNING['lockon_time']
    MAX_AMMO = 30
    RELOAD_TIME = 1.5
    HUD_ORDER = ('ab1', 'ab2', 'secondary')

    def __init__(self, world):
        super().__init__(world)
        self.abilities = {
            'secondary': Ability(self, 'secondary', 'HELIX ROCKETS', 'RMB', TUNING['helix_cd']),
            'ab1': Ability(self, 'ab1', 'SPRINT', 'SHIFT', 0.0),
            'ab2': Ability(self, 'ab2', 'HEAL FIELD', 'E', TUNING['heal_cd']),
        }
        self.sprinting = False
        self._next_shot = 0.0

    def on_input(self, inp, world):
        if inp.hit('ab1') and self.abilities['ab1'].use(world):
            self.sprinting = not self.sprinting
            if self.sprinting:
                self.cancel_reload()
        if self.sprinting and (not inp.down('fwd') or inp.down('fire') or inp.hit('alt')
                               or inp.hit('ab2') or inp.hit('ult')):
            self.sprinting = False
        self.abilities['ab1'].active_left = 1.0 if self.sprinting else 0.0
        if self.sprinting:
            self.speed_mult = TUNING['sprint_mult']
        if inp.hit('alt') and self.abilities['secondary'].use(world):
            self._fire_rocket(world)
        if inp.hit('ab2') and self.abilities['ab2'].use(world):
            healed = heal(world, self, 80.0, self, 'ab2')      # stub: instant heal
            self.add_ult(healed)
        if inp.down('fire') and not self.sprinting:
            self._fire(world)

    def _fire(self, world):
        now = world.now
        if now < self._next_shot or self.reloading:
            return
        if self.ult_active_left <= 0 and not self.use_ammo():
            return
        self._next_shot = now + TUNING['rifle_interval']
        self.fire_hitscan(world, TUNING['rifle_damage'])

    def _fire_rocket(self, world):
        a = self.angle
        p = Projectile(self.x + math.cos(a) * 0.3, self.y + math.sin(a) * 0.3, a, TUNING['helix_speed'],
                       team=TEAM_PLAYER, damage=TUNING['helix_direct'], radius=0.2, owner=self,
                       ability='secondary', ttl=1.5, z=0.4, color=(255, 140, 40), core=(255, 230, 160),
                       size=0.08, splash_r=TUNING['helix_radius'], splash_center=TUNING['helix_center'],
                       splash_edge=TUNING['helix_edge'])
        world.add_projectile(p)

    def draw_viewmodel(self, surf, world):
        kick = 10 if world.now - self.last_fire < 0.08 else 0
        low = 60 if self.sprinting else 0
        x = 640
        y = 610 + kick + low
        surf.fill((40, 46, 60), (x, y, 300, 70))
        surf.fill((80, 150, 255), (x, y + 18, 300, 6))
        surf.fill((30, 34, 44), (x + 180, y + 60, 50, 110))
        if world.now - self.last_fire < 0.05:
            surf.fill((120, 100, 40), (x - 18, y + 10, 24, 24), pygame.BLEND_RGB_ADD)

    def draw_crosshair(self, surf, world):
        cx, cy = C.W // 2, C.H // 2
        col = (255, 80, 80) if self.ult_active_left > 0 else (255, 255, 255)
        surf.fill(col, (cx - 1, cy - 1, 2, 2))
        pygame.draw.circle(surf, col, (cx, cy), 10, 1)
