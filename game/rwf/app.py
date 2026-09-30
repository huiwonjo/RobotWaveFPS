"""Screen state machine, main(), run_match(), pause/pointer lock, slow-mo, debug overlay (spec 6.1, 7.4, 7.6).

States inside a match: COUNTDOWN, PLAYING, PAUSED, INTERMISSION, END_BANNER, POTG, SUMMARY.
"""
import asyncio
import time
import traceback
from collections import deque, namedtuple

import pygame

from . import config as C
from . import core
from . import theme
from . import world as world_mod
from . import combat
from . import render
from . import hero_base
from . import hero_vector, hero_flicker, hero_rampart      # noqa: F401  (register heroes)
from . import enemies                                      # noqa: F401  (register enemies + painters)
from . import waves
from . import hud as hud_mod
from . import screens
from . import stats as stats_mod
from . import potg as potg_mod
from . import sfx

MatchResult = namedtuple('MatchResult', 'action world stats states frames frame_ms exception')

SIM_STATES = ('COUNTDOWN', 'PLAYING', 'INTERMISSION')
# 6.1: COUNTDOWN allows only move and look. These actions are dropped from the input before the world
# update while counting down (a key or button still held when PLAYING starts acts from then on).
COMBAT_ACTIONS = ('fire', 'alt', 'ab1', 'ab2', 'ult', 'reload', 'melee')
LIVE_HISTORY = 600          # frames of states / frame_ms kept by a live (non-harness) match
_perf = time.perf_counter
_app = {'inp': None, 'clock': None, 'sfx_init': False, 'debug': False, 'toast': ('', 0.0), 'frozen': None}


class _Quit(Exception):
    pass


def init_display():
    """pygame.init + set_mode + IME off + theme.load(). Used by main() and by tools/smoke.py."""
    pygame.init()
    screen = pygame.display.set_mode((C.W, C.H))
    pygame.display.set_caption(theme.TITLE)
    try:
        pygame.key.stop_text_input()
    except Exception:
        pass
    theme.load()
    return screen


def get_input():
    if _app['inp'] is None:
        _app['inp'] = core.InputState()
    return _app['inp']


def _clock():
    if _app['clock'] is None:
        _app['clock'] = pygame.time.Clock()
    return _app['clock']


def _toast(msg):
    _app['toast'] = (msg, core.real_time() + 1.0)


def _global_event(ev, inp):
    """Events handled the same way in every state: sfx init, mute, sensitivity."""
    t = ev.type
    if t in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN) and not _app['sfx_init']:
        _app['sfx_init'] = True
        try:
            sfx.init()
        except Exception:
            pass
    if t == pygame.KEYDOWN:
        a = C.KEYMAP.get(ev.key)
        if a == 'mute':
            sfx.set_muted(not sfx.muted)
            _toast('SOUND OFF' if sfx.muted else 'SOUND ON')
        elif a in ('sens_down', 'sens_up'):
            step = C.SENS_STEP if a == 'sens_up' else -C.SENS_STEP
            inp.sens = round(core.clamp(inp.sens + step, C.SENS_MIN, C.SENS_MAX), 2)
            _toast('SENS %.1fx' % inp.sens)


def _focus_lost(ev):
    if ev.type == getattr(pygame, 'WINDOWFOCUSLOST', -1):
        return True
    if ev.type == pygame.ACTIVEEVENT and getattr(ev, 'gain', 1) == 0 and getattr(ev, 'state', 2) & 6:
        return True
    return False


class _Match:
    def __init__(self, screen, hero_key, input_source, fixed_dt, seed, debug):
        self.screen = screen
        self.inp = get_input()
        self.inp.clear()
        self.clock = _clock()
        self.input_source = input_source
        self.fixed_dt = fixed_dt
        w = world_mod.World(hero_key, seed=seed, debug=debug)
        w.director = waves.WaveDirector(w)
        self.world = w
        self.stats = stats_mod.MatchStats(w)
        self.hud = hud_mod.HUD(w)
        self.rec = potg_mod.PotgRecorder(w)
        sfx.attach(w.bus)
        self.ult_log = []
        w.bus.on('ult_used', self._on_ult_used)
        w.bus.on('ult_ready', self._on_ult_ready)
        self.hero_key = hero_key
        self.state = 'COUNTDOWN'
        self.overlay = None
        self.resume_state = 'PLAYING'
        self.resume_overlay = None
        # the harness reads every frame's state and time; a live match keeps only a short history
        if input_source is not None or fixed_dt is not None:
            self.states = []
            self.frame_ms = []
        else:
            self.states = deque(maxlen=LIVE_HISTORY)
            self.frame_ms = deque(maxlen=LIVE_HISTORY)
        self._published = None
        self.frame_i = 0
        self.action = None
        self.done = False
        self.poll_enabled = core.IS_WEB
        self.poll_next = 0.0
        self.seen_lock = False
        if _app['frozen'] is None or _app['frozen'].get_size() != screen.get_size():
            _app['frozen'] = pygame.Surface(screen.get_size())
        self.frozen = _app['frozen']

    # --- bus ------------------------------------------------------------------------
    def _on_ult_used(self, d):
        self.world.clock.slowmo(*C.ULT_SLOWMO)
        self.world.shake(6, 0.2)

    def _on_ult_ready(self, d):
        self.ult_log.append(self.world.now)
        del self.ult_log[:-6]

    # --- transitions ----------------------------------------------------------------
    def begin(self):
        if self.world.debug.get('skip_countdown'):
            self._enter_playing()
        else:
            self.state = 'COUNTDOWN'
            self.overlay = screens.CountdownOverlay(C.COUNTDOWN)
        core.lock_mouse(True)

    def _enter_playing(self):
        self.state = 'PLAYING'
        self.overlay = None
        self.world.director.start()
        self.seen_lock = False

    def _freeze(self):
        """Copy a clean frame (world, effects, viewmodel, HUD; no overlay screen, debug overlay or
        toast) into self.frozen, for PAUSED and END_BANNER. The world is not advanced."""
        try:
            self._draw_sim(0.0, record=False)
        except Exception:
            pass
        self.frozen.blit(self.screen, (0, 0))

    def pause(self):
        if self.state not in SIM_STATES:
            return
        self.resume_state = self.state
        self.resume_overlay = self.overlay
        self._freeze()
        self.world.clock.paused = True
        self.inp.clear()
        core.lock_mouse(False)
        self.state = 'PAUSED'
        self.overlay = screens.PauseOverlay(self.world, self.stats, self.frozen)

    def resume(self):
        self.world.clock.paused = False
        self.state = self.resume_state
        self.overlay = self.resume_overlay
        core.lock_mouse(True)
        self.inp.clear()
        self.seen_lock = False

    def _end_banner(self):
        if self.state != 'PAUSED':
            self._freeze()
        self.world.clock.paused = True
        core.lock_mouse(False)
        self.state = 'END_BANNER'
        self.overlay = screens.EndBanner(self.world.victory)

    def _after_banner(self):
        best = None
        try:
            best = self.rec.best()
        except Exception:
            best = None
        if best:
            self.state = 'POTG'
            self.overlay = screens.PotgScreen(best)
        else:
            self._summary()

    def _summary(self):
        self.state = 'SUMMARY'
        self.overlay = screens.SummaryScreen(self.world, self.stats, self.world.player.KEY)

    def on_action(self, act):
        st = self.state
        if act == 'done':
            if st == 'COUNTDOWN':
                self._enter_playing()
            elif st == 'END_BANNER':
                self._after_banner()
            elif st == 'POTG':
                self._summary()
        elif act == 'skip':
            if st == 'INTERMISSION':
                self.world.director.skip_intermission()
            elif st == 'POTG':
                self._summary()
            elif st == 'END_BANNER':
                self._after_banner()
        elif act == 'resume':
            if st == 'PAUSED':
                self.resume()
        elif act == 'end_match':
            if st == 'PAUSED':
                self.world.over = True
                self._end_banner()
        elif act.startswith('swap:'):
            key = act[5:]
            if st == 'INTERMISSION' and key in core.HEROES and key != self.world.player.KEY:
                self.world.set_hero(key, C.ULT_SWAP_KEEP)
        elif act in ('again', 'select'):
            if st == 'SUMMARY':
                self.action = act
                self.done = True

    # --- frame ----------------------------------------------------------------------
    def _events(self):
        if self.input_source is not None:
            pygame.event.pump()
            evs = self.input_source.events_for_frame(self.frame_i)
        else:
            evs = pygame.event.get()
        inp = self.inp
        for ev in evs:
            if ev.type == pygame.QUIT:
                raise _Quit()
            inp.feed(ev)
            _global_event(ev, inp)
            if _focus_lost(ev):
                inp.clear()
                self.pause()
                continue
            if ev.type == pygame.KEYDOWN:
                a = C.KEYMAP.get(ev.key)
                if a == 'debug':
                    _app['debug'] = not _app['debug']
                elif a == 'pause' and self.state in SIM_STATES:
                    self.pause()
                    continue
            if self.overlay is not None:
                act = self.overlay.handle(ev, inp)
                if act:
                    self.on_action(act)

    def _poll_pointer_lock(self):
        if not (self.poll_enabled and self.state == 'PLAYING'):
            return
        now_r = core.real_time()
        if now_r < self.poll_next:
            return
        self.poll_next = now_r + 0.25
        v = core.pointer_locked()
        if v is None:
            self.poll_enabled = False
        elif v:
            self.seen_lock = True
        elif self.seen_lock:
            self.pause()

    def frame(self):
        w = self.world
        inp = self.inp
        if self.fixed_dt is not None:
            real_dt = self.fixed_dt
        else:
            real_dt = min(self.clock.tick(60) / 1000.0, 0.1)
        t0 = _perf()                    # after the frame-limiter wait: perf['total'] is work time only
        self._events()
        inp.poll_keyboard()
        if self.state == 'COUNTDOWN':
            held = inp.held
            pressed = inp.pressed
            for a in COMBAT_ACTIONS:
                held.discard(a)
                pressed.discard(a)
        kill_at = w.debug.get('kill_player_at')
        if kill_at is not None and self.frame_i == kill_at and not w.over:
            w.player.pool.health = 0.0
            w.player.pool.armor = 0.0
            w.player.pool.shields = 0.0
        t1 = _perf()
        if self.state in SIM_STATES:
            dt = w.clock.tick(real_dt)
            if dt > 0:
                w.update(dt, inp)
                self.stats.update(w, dt)
            self._poll_pointer_lock()
        t2 = _perf()
        st = self.state
        if st in SIM_STATES:
            if w.over:
                if w.debug.get('skip_end_screens'):
                    self.action = 'death'
                    self.done = True
                else:
                    self._end_banner()
            elif st == 'PLAYING' and w.director.state == 'intermission':
                self.state = 'INTERMISSION'
                self.overlay = screens.IntermissionOverlay(w)
            elif st == 'INTERMISSION' and w.director.state != 'intermission':
                self.state = 'PLAYING'
                self.overlay = None
        if self.overlay is not None and not self.done:
            act = self.overlay.update(real_dt)
            if act:
                self.on_action(act)
        t_render, t_hud = self._draw(real_dt, t2)
        try:
            sfx.update()
        except Exception:
            pass
        pygame.display.flip()
        inp.end_frame()
        t3 = _perf()
        total = (t3 - t0) * 1000.0
        self.states.append(self.state)
        self.frame_ms.append(total)
        if w.debug.get('perf') or _app['debug']:
            w.perf = {'update': (t2 - t1) * 1000.0, 'render': t_render, 'hud': t_hud, 'total': total}
        if self.state != self._published:
            self._published = self.state
            core.web_set('RWF_STATE', self.state)
        self.frame_i += 1
        return not self.done

    def _draw_sim(self, real_dt, record=True):
        """World + effect draw_screen + hero draw_overlay + viewmodel + HUD (7.6 steps 5-7), without the
        overlay screen. Returns the perf_counter time at which the world render ended."""
        scr = self.screen
        w = self.world
        scene = render.render_frame(scr, w)
        if record:
            self.rec.record(w, scene)
        t1 = _perf()
        for ef in w.effects:
            ef.draw_screen(scr, w)
        p = w.player
        p.draw_overlay(scr, w)
        p.draw_viewmodel(scr, w)
        self.hud.update(w, real_dt)
        self.hud.draw(scr, w)
        return t1

    def _draw(self, real_dt, t_start):
        scr = self.screen
        st = self.state
        t_render = t_hud = 0.0
        if st in SIM_STATES:
            t1 = self._draw_sim(real_dt)
            t_render = (t1 - t_start) * 1000.0
            if self.overlay is not None:
                self.overlay.draw(scr)
            t_hud = (_perf() - t1) * 1000.0
        elif st == 'END_BANNER':
            scr.blit(self.frozen, (0, 0))
            self.overlay.draw(scr)
        elif self.overlay is not None:
            self.overlay.draw(scr)
        if _app['debug'] and st != 'SUMMARY':
            render.draw_debug(scr, self._debug_lines())
        msg, until = _app['toast']
        if msg and core.real_time() < until:
            render.draw_toast(scr, msg)
        return t_render, t_hud

    def _debug_lines(self):
        w = self.world
        pf = w.perf or {}
        if self.fixed_dt is None:
            fps = self.clock.get_fps()
        else:
            ms = self.frame_ms[-30:]
            fps = 1000.0 * len(ms) / sum(ms) if ms and sum(ms) > 0 else 0.0
        d = w.director
        p = w.player
        gaps = ['%.0f' % (b - a) for a, b in zip(self.ult_log, self.ult_log[1:])]
        return ['FPS %.0f  %s' % (fps, self.state),
                'upd %.1f  ren %.1f  hud %.1f  tot %.1f ms' % (pf.get('update', 0), pf.get('render', 0),
                                                           pf.get('hud', 0), pf.get('total', 0)),
                'enemies %d  proj %d  part %d  fx %d  bar %d' % (
                    len(w.alive_enemies()), len(w.projectiles), len(w.particles), len(w.effects), len(w.barriers)),
                'stage %d wave %d %s %s left %d' % (d.stage, d.wave, d.kind, d.state, d.remaining),
                'ult %.0f/%d  ready at %s' % (p.ult_charge, p.ULT_COST, ' '.join('%.0f' % t for t in self.ult_log)),
                'ult gaps %s  sens %.1f' % (' '.join(gaps) or '-', self.inp.sens)]


async def run_match(screen, hero_key, *, input_source=None, fixed_dt=None, max_frames=None, seed=None,
                    debug=None, setup=None, on_frame=None):
    """One match from COUNTDOWN to SUMMARY. The harness drives it with input_source/fixed_dt."""
    m = None
    exc = None
    try:
        m = _Match(screen, hero_key, input_source, fixed_dt, seed, debug)
        if setup is not None:
            setup(m.world)
        m.begin()
        while True:
            if max_frames is not None and m.frame_i >= max_frames:
                break
            cont = m.frame()
            if on_frame is not None and on_frame(m.world, m.frame_i - 1, m.state) == 'stop':
                break
            if not cont:
                break
            await asyncio.sleep(0)
    except _Quit:
        if m is not None:
            m.action = 'quit'
    except Exception:
        exc = traceback.format_exc()
    core.lock_mouse(False)
    if m is None:
        return MatchResult(None, None, None, [], 0, [], exc)
    return MatchResult(m.action, m.world, m.stats, list(m.states), m.frame_i, list(m.frame_ms), exc)


async def _run_screen(screen, scr, clock, name):
    inp = get_input()
    core.lock_mouse(False)
    core.web_set('RWF_STATE', name)
    while True:
        real_dt = min(clock.tick(60) / 1000.0, 0.1)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return 'quit'
            inp.feed(ev)
            _global_event(ev, inp)
            act = scr.handle(ev, inp)
            if act:
                inp.end_frame()
                return act
        inp.poll_keyboard()
        act = scr.update(real_dt)
        scr.draw(screen)
        msg, until = _app['toast']
        if msg and core.real_time() < until:
            render.draw_toast(screen, msg)
        try:
            sfx.update()
        except Exception:
            pass
        pygame.display.flip()
        inp.end_frame()
        if act:
            return act
        await asyncio.sleep(0)


async def main():
    """TITLE -> HERO_SELECT -> matches. PLAY AGAIN ('again' on SUMMARY) replays with the hero the match
    ENDED with, i.e. the one the summary shows (it differs from the locked-in hero after an intermission
    swap); H - HERO SELECT opens the select screen with that hero highlighted."""
    screen = init_display()
    clock = _clock()
    hero_key = core.HERO_ORDER[0]
    mode = 'title'
    while mode != 'quit':
        if mode == 'title':
            act = await _run_screen(screen, screens.TitleScreen(), clock, 'TITLE')
            mode = 'quit' if act == 'quit' else 'select'
        elif mode == 'select':
            act = await _run_screen(screen, screens.HeroSelectScreen(hero_key), clock, 'HERO_SELECT')
            if act == 'quit':
                mode = 'quit'
            elif act.startswith('lock:') and act[5:] in core.HEROES:
                hero_key = act[5:]
                mode = 'match'
        else:
            res = await run_match(screen, hero_key)
            if res.world is not None and res.world.player is not None:
                hero_key = res.world.player.KEY
            if res.exception:
                print(res.exception)
                mode = 'title'
            elif res.action == 'quit':
                mode = 'quit'
            elif res.action == 'select':
                mode = 'select'
            else:
                mode = 'match'
        await asyncio.sleep(0)
    pygame.quit()
