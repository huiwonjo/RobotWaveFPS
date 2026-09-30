"""FLICKER (HERO_B owns this file). Phase 0 STUB by FOUNDATION.

Final class attributes (spec 3.4) and working slots; the real kit (falloff
pistols with accumulator, blink visuals, Rewind buffer, sticky Pulse Bomb,
ported twin-pistol viewmodel, icons) is HERO_B's job.
"""
import math

import pygame

from . import config as C
from . import core
from .combat import Projectile, splash
from .config import TEAM_PLAYER
from .hero_base import Ability, Hero
from .world import dash_target

TUNING = {
    'pistol_damage': 12.0, 'pistol_interval': 0.05, 'pistol_falloff': (5.0, 10.0, 0.5),
    'pistol_spread': 0.014, 'blink_dist': 3.5, 'blink_cd': 3.0, 'rewind_cd': 12.0,
    'bomb_speed': 12.0, 'bomb_damage': 350.0, 'bomb_edge': 105.0, 'bomb_radius': 2.5,
}


@core.register_hero
class Flicker(Hero):
    KEY = 'flicker'
    NAME = 'FLICKER'
    ROLE = 'DAMAGE'
    DIFFICULTY = 3
    COLOR = (255, 150, 40)
    BLURB = 'Blink through fights, rewind mistakes.'
    KIT = (('LMB', 'TWIN PISTOLS', 'Rapid-fire pistols, falloff past 5 m.'),
           ('RMB/F', 'BLINK (3 CHARGES)', 'Or SHIFT. Teleport a short distance.'),
           ('E', 'REWIND', 'Jump back to where you were 3 s ago.'),
           ('V', 'QUICK MELEE', 'A quick punch.'),
           ('Q', 'PULSE BOMB', 'Sticky bomb, huge blast.'))
    LABELS = {'primary': 'PISTOLS', 'ult': 'PULSE BOMB', 'melee': 'MELEE'}
    HEALTH = 150
    ARMOR = 0
    SHIELDS = 0
    SPEED = 4.6
    ULT_COST = 1100
    ULT_NAME = 'PULSE BOMB'
    ULT_CALLOUT = 'BOMB AWAY!'
    ULT_DURATION = 0.0
    MAX_AMMO = 40
    RELOAD_TIME = 1.0
    HUD_ORDER = ('ab1', 'ab2')

    def __init__(self, world):
        super().__init__(world)
        self.abilities = {
            'ab1': Ability(self, 'ab1', 'BLINK', 'SHIFT', TUNING['blink_cd'], charges=3),
            'ab2': Ability(self, 'ab2', 'REWIND', 'E', TUNING['rewind_cd']),
        }
        self._shot_acc = 0.0
        self._gun = 0
        self.last_blink = -9.0

    def on_input(self, inp, world):
        if (inp.hit('ab1') or inp.hit('alt')) and self.abilities['ab1'].use(world):
            self._blink(world)
        if inp.hit('ab2') and self.abilities['ab2'].use(world):
            self.status.add('invuln', 0.5, world.now)            # stub: no position rewind yet
        if inp.down('fire') and not self.reloading:
            self._shot_acc += world.dt
            while self._shot_acc >= TUNING['pistol_interval']:
                self._shot_acc -= TUNING['pistol_interval']
                if not self.use_ammo():
                    self._shot_acc = 0.0
                    break
                self._gun ^= 1
                self.fire_hitscan(world, TUNING['pistol_damage'], spread=TUNING['pistol_spread'],
                                  falloff=TUNING['pistol_falloff'])
        else:
            self._shot_acc = min(self._shot_acc, TUNING['pistol_interval'])

    def _blink(self, world):
        f, r = self.move_fwd, self.move_right
        if not f and not r:
            f = 1
        ang = self.angle + math.atan2(r, f)
        self.x, self.y = dash_target(self.x, self.y, ang, TUNING['blink_dist'])
        self.last_blink = world.now
        world.bus.emit('sfx', name='blink', vol=1.0)

    def on_ult(self, world):
        a = self.angle
        p = Projectile(self.x, self.y, a, TUNING['bomb_speed'], team=TEAM_PLAYER, damage=0.0, radius=0.25,
                       owner=self, ability='ult', ttl=0.5, z=0.35, color=(80, 170, 255), core=(255, 255, 255),
                       size=0.08, splash_r=TUNING['bomb_radius'], splash_center=TUNING['bomb_damage'],
                       splash_edge=TUNING['bomb_edge'])
        p.on_expire = lambda w, pr: _bomb_blast(w, pr)
        world.add_projectile(p)

    def draw_viewmodel(self, surf, world):
        since = world.now - self.last_fire
        kick_r = 30 if (since < 0.06 and self._gun == 0) else 0
        kick_l = 30 if (since < 0.06 and self._gun == 1) else 0
        surf.fill((38, 42, 55), (700, 640 + kick_r, 150, 60))
        surf.fill((0, 180, 230), (700, 652 + kick_r, 150, 6))
        surf.fill((38, 42, 55), (174, 640 + kick_l, 150, 60))
        surf.fill((0, 180, 230), (174, 652 + kick_l, 150, 6))
        if world.now - self.last_blink < 0.12:
            surf.fill((0, 30, 60), None, pygame.BLEND_RGB_ADD)

    def draw_crosshair(self, surf, world):
        cx, cy = C.W // 2, C.H // 2
        gap = 8 + (6 if world.now - self.last_fire < 0.1 else 0)
        col = (255, 255, 255)
        surf.fill(col, (cx - gap - 7, cy, 7, 2))
        surf.fill(col, (cx + gap, cy, 7, 2))
        surf.fill(col, (cx, cy - gap - 7, 2, 7))
        surf.fill(col, (cx, cy + gap, 2, 7))


def _bomb_blast(world, pr):
    splash(world, pr.x, pr.y, pr.splash_r, pr.splash_center, pr.splash_edge, pr.owner, TEAM_PLAYER, 'ult',
           ignore_barriers=True)
    world.burst(pr.x, pr.y, 0.4, 24, (120, 190, 255), 3.0, 0.5, 3)
    world.shake(8, 0.3)
