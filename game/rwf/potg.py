"""Play of the Game recorder (HUD_UX owns this file). Phase 0 STUB by FOUNDATION.

record() keeps Scene references at 20 Hz of sim time in an 8 s ring (160).
best() returns None in the stub, so the app skips the POTG screen.
Final shape of best(): {'frames': [Scene], 'hero': key, 'kills': n, 'span': s, 'kill_frames': [i]}.
"""
from collections import deque

RATE = 20.0
RING = 160


class PotgRecorder:
    def __init__(self, world):
        self.world = world
        self.ring = deque(maxlen=RING)
        self._next = 0.0

    def record(self, world, scene):
        now = world.now
        if now >= self._next:
            self._next = now + 1.0 / RATE
            self.ring.append(scene)

    def best(self):
        return None
