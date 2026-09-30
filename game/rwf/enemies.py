"""Enemy kinds and painters (ENEMIES owns this file). Phase 0 STUB by FOUNDATION.

All 5 kinds are registered with the spec 4.2 stats. They share a stub AI (flow
chase + melee through enemy_hits_player; troopers, eradicators and the warden
also fire bolts) and coloured-box painters. The real state machines (4.4) are
the ENEMIES builder's job.
"""
import math

import pygame

from . import config as C
from . import core
from .combat import Enemy
from .render import register_painter

TUNING = {}


class _StubEnemy(Enemy):
    COLOR = (200, 200, 200)
    MELEE = (10.0, 1.0, 1.0)            # damage (stage 1), interval s, reach
    BOLT = None                          # (every, speed, damage, radius, color, ttl)
    MOVE_STATE = 'move'
    ATTACK_STATE = 'attack'

    def __init__(self, world, x, y, elite=False):
        super().__init__(world, x, y, elite)
        self._melee_next = 0.0
        self._bolt_next = world.now + 1.0 + (self.id % 5) * 0.3

    def update(self, world, dt):
        p = world.player
        now = world.now
        d = self.dist_to_player(world)
        dmg, every, reach = self.MELEE
        if d > reach * 0.9:
            self.move_toward(world, p.x, p.y, dt)
            self.vstate = self.MOVE_STATE
        else:
            self.face_player(world)
            self.vstate = self.ATTACK_STATE
            if now >= self._melee_next and self.can_attack(world):
                self._melee_next = now + every
                self.melee(world, dmg)
        if self.BOLT is not None and now >= self._bolt_next:
            b_every, speed, bdmg, rad, col, ttl = self.BOLT
            if d < speed * ttl and self.has_los(world) and self.can_attack(world):
                self._bolt_next = now + b_every
                a = self.face_player(world) + world.rng.uniform(-0.035, 0.035)
                self.fire_bolt(world, a, speed, bdmg, rad, col, ttl)
            else:
                self._bolt_next = now + 0.2

    def update_disabled(self, world, dt):
        self.vstate = 'stun'

    def on_death(self, world, source, ability):
        world.burst(self.x, self.y, self.height * 0.5, 10, self.COLOR, 2.5, 0.5, 2)


@core.register_enemy
class Trooper(_StubEnemy):
    KIND = 'trooper'
    SCORE = 10
    BASE_HEALTH = 75
    BASE_SPEED = 1.8
    radius = 0.25
    height = 0.70
    width = 0.44
    head_band = (0.00, 0.20)
    COLOR = (80, 170, 90)
    MELEE = (10.0, 1.0, 1.0)
    BOLT = (2.0, 8.0, 10.0, 0.12, (255, 70, 50), 1.25)


@core.register_enemy
class Slicer(_StubEnemy):
    KIND = 'slicer'
    SCORE = 15
    BASE_HEALTH = 40
    BASE_SHIELDS = 40
    BASE_SPEED = 3.4
    radius = 0.22
    height = 0.46
    width = 0.36
    head_band = (0.00, 0.30)
    COLOR = (200, 60, 60)
    MELEE = (12.0, 0.8, 0.9)
    ATTACK_STATE = 'lunge'


@core.register_enemy
class Detonator(_StubEnemy):
    KIND = 'detonator'
    SCORE = 15
    BASE_HEALTH = 100
    BASE_ARMOR = 100
    BASE_SPEED = 1.6
    radius = 0.30
    height = 0.58
    width = 0.56
    head_band = (0.30, 0.55)
    COLOR = (230, 150, 40)
    MELEE = (20.0, 1.5, 1.2)
    ATTACK_STATE = 'armed_a'


@core.register_enemy
class Eradicator(_StubEnemy):
    KIND = 'eradicator'
    SCORE = 30
    BASE_HEALTH = 150
    BASE_SHIELDS = 100
    BASE_SPEED = 1.3
    radius = 0.35
    height = 0.80
    width = 0.66
    head_band = (0.00, 0.18)
    COLOR = (90, 110, 200)
    MELEE = (15.0, 1.0, 1.0)
    BOLT = (3.0, 9.0, 10.0, 0.12, (255, 120, 40), 1.3)


@core.register_enemy
class Warden(_StubEnemy):
    KIND = 'warden'
    SCORE = 150
    BOSS = True
    PINNABLE = False
    STUN_MULT = 0.4
    BASE_HEALTH = 800
    BASE_ARMOR = 600
    BASE_SPEED = 1.1
    radius = 0.45
    height = 1.00
    width = 0.90
    head_band = (0.35, 0.55)
    COLOR = (180, 60, 220)
    MELEE = (25.0, 1.2, 1.4)
    BOLT = (0.6, 10.0, 15.0, 0.15, (220, 80, 255), 1.4)
    MOVE_STATE = 'recon'
    ATTACK_STATE = 'recon_attack'


# ============================ painters (coloured boxes) ======================
_HOT = ('windup', 'sentry_windup', 'stomp_windup', 'armed_a')
_FIRE = ('attack', 'lunge', 'recon_attack', 'sentry', 'armed_b')


def _box_painter(body, visor):
    def fn(surf, state, elite):
        w, h = surf.get_size()
        b = body
        v = visor
        if state in _HOT:
            v = (255, 255, 255)
        elif state in _FIRE:
            v = (255, 60, 40)
        if state == 'stun':
            b = (body[0] // 2, body[1] // 2, body[2] // 2)
            v = (90, 90, 90)
        top = int(h * 0.12) if state in ('windup', 'stomp_windup') else 0
        head = pygame.Rect(int(w * 0.25), top, int(w * 0.5), int(h * 0.25))
        torso = pygame.Rect(int(w * 0.12), head.bottom, int(w * 0.76), int(h * 0.45) - top // 2)
        pygame.draw.rect(surf, b, head, border_radius=4)
        surf.fill(v, (head.x + 3, head.y + head.h // 3, head.w - 6, max(2, head.h // 4)))
        pygame.draw.rect(surf, b, torso, border_radius=4)
        surf.fill((b[0] // 2 + 20, b[1] // 2 + 20, b[2] // 2 + 20),
                  (torso.x + 4, torso.y + 6, torso.w - 8, max(2, torso.h // 6)))
        leg_w = max(3, int(w * 0.16))
        surf.fill((b[0] * 2 // 3, b[1] * 2 // 3, b[2] * 2 // 3), (int(w * 0.28), torso.bottom, leg_w, h - torso.bottom))
        surf.fill((b[0] * 2 // 3, b[1] * 2 // 3, b[2] * 2 // 3), (int(w * 0.72) - leg_w, torso.bottom, leg_w, h - torso.bottom))
        if elite:
            pygame.draw.rect(surf, C.COL_ELITE, torso, 2, border_radius=4)
            pygame.draw.rect(surf, C.COL_ELITE, head, 2, border_radius=4)
    return fn


register_painter('trooper', _box_painter(Trooper.COLOR, (180, 255, 80)), 48, 96)
register_painter('slicer', _box_painter(Slicer.COLOR, (255, 200, 200)), 40, 80)
register_painter('detonator', _box_painter(Detonator.COLOR, (255, 240, 120)), 64, 80)
register_painter('eradicator', _box_painter(Eradicator.COLOR, (140, 220, 255)), 72, 112)
register_painter('warden', _box_painter(Warden.COLOR, (255, 120, 255)), 96, 128)
