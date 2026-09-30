"""Presentation data: theme names, words, palette and optional assets (spec 7.4).

This branch ships only the code-drawn 'omnic' theme. The interface is the full
one from the spec, so a later theme (with PNGs and a font) can be merged here
without touching gameplay code: enemy_image / backdrop / sky_strip return None
and font_path returns None while no asset exists (or RWF_NO_ASSETS=1 is set).
Gameplay code never reads this module except for display names.
"""
import os

import pygame

GAME_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSET_DIR = os.path.join(GAME_DIR, 'assets')
NO_ASSETS = os.environ.get('RWF_NO_ASSETS', '') not in ('', '0')

_THEMES = {
    'omnic': {
        'title': 'ROBOT WAVE FPS',
        'subtitle': 'HERO EDITION',
        'words': {'stage': 'STAGE', 'score': 'SCORE', 'kill': 'ELIMINATED',
                  'capture': 'CAPTURE THE POINT'},
        'names': {'trooper': 'TROOPER', 'slicer': 'SLICER', 'detonator': 'DETONATOR',
                  'eradicator': 'ERADICATOR', 'warden': 'WARDEN', 'dummy': 'DUMMY'},
        'palette': {
            'ink': (12, 16, 26), 'edge': (60, 80, 120), 'accent': (255, 150, 40),
            'accent2': (80, 190, 255), 'text': (235, 241, 237), 'muted': (140, 150, 170),
            'sky': (18, 22, 45), 'floor': (42, 36, 30),
            'wall_a': (175, 155, 135), 'wall_b': (120, 105, 90),
            'bg': (10, 10, 20), 'grid': (20, 20, 35),
        },
        'images': {},           # kind -> file name in assets/ (none for omnic)
        'backdrop': None,
        'sky': None,
        'font': None,
    },
}


def _pick_key():
    # Only 'omnic' exists in this branch. A PNG theme would be chosen here when
    # its marker asset exists and NO_ASSETS is off.
    return 'omnic'


KEY = _pick_key()
_T = _THEMES[KEY]
TITLE = _T['title']
SUBTITLE = _T['subtitle']
WORDS = dict(_T['words'])
PALETTE = dict(_T['palette'])

_img_cache = {}
_loaded = False


def enemy_name(kind):
    return _T['names'].get(kind, str(kind).upper())


def _asset(name):
    if NO_ASSETS or not name:
        return None
    path = os.path.join(ASSET_DIR, name)
    return path if os.path.exists(path) else None


def _load_image(name):
    path = _asset(name)
    if path is None:
        return None
    try:
        return pygame.image.load(path).convert_alpha()
    except Exception:
        return None


def enemy_image(kind, base_h):
    """Surface smoothscaled ONCE to base_h tall, or None (always None for omnic)."""
    key = (kind, int(base_h))
    if key in _img_cache:
        return _img_cache[key]
    img = None
    raw = _load_image(_T['images'].get(kind))
    if raw is not None:
        try:
            w = max(1, int(raw.get_width() * base_h / max(1, raw.get_height())))
            img = pygame.transform.smoothscale(raw, (w, int(base_h))).convert_alpha()
        except Exception:
            img = None
    _img_cache[key] = img
    return img


def backdrop(size):
    key = ('backdrop', tuple(size))
    if key not in _img_cache:
        raw = _load_image(_T['backdrop'])
        img = None
        if raw is not None:
            try:
                img = pygame.transform.smoothscale(raw, tuple(size)).convert()
            except Exception:
                img = None
        _img_cache[key] = img
    return _img_cache[key]


def sky_strip():
    if 'sky' not in _img_cache:
        raw = _load_image(_T['sky'])
        _img_cache['sky'] = raw.convert() if raw is not None else None
    return _img_cache['sky']


def font_path():
    return _asset(_T['font'])


def load():
    """Called by app after set_mode. Never raises; missing files simply give None."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        for kind in _T['images']:
            enemy_image(kind, 96)
        sky_strip()
    except Exception:
        pass
