"""Synthesised sound effects (HUD_UX owns this file). Phase 0 STUB by FOUNDATION: all no-ops.

Final contract: init() after the first input (never raises), attach(bus) maps
bus events to sounds, play(name, vol) is a no-op for unknown names or when
disabled/muted, update() synthesises at most one sound per call.
"""
enabled = False
muted = False


def init():
    global enabled
    enabled = False


def attach(bus):
    pass


def play(name, vol=1.0):
    pass


def set_muted(on):
    global muted
    muted = bool(on)


def update():
    pass
