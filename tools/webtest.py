"""Headless-browser smoke test of a pygbag build (FOUNDATION tool, not shipped).

    python -X utf8 tools/webtest.py [web_root=game/build/web] [out_prefix=tools/out/web]
                                    [--hero vector|flicker|rampart] [--play SECONDS]

Serves web_root on 127.0.0.1:8765 and opens index.html in headless Microsoft Edge (Playwright).
The game publishes its screen state as window.RWF_STATE (app.py via core.web_set: TITLE, HERO_SELECT,
COUNTDOWN, PLAYING, PAUSED, ...), and every step waits for the state it needs instead of sleeping
blindly, so it doesn't matter whether pygbag starts Python on its own or waits for a click:
    start gesture (only if needed) -> TITLE, Enter -> HERO_SELECT, Right/Left, Enter -> COUNTDOWN,
    click (pointer lock; must not fire) -> PLAYING, '0' (debug overlay: FPS, ms per system),
    W held, fire held -> screenshots, D held -> later screenshot, Esc -> PAUSED.
Saves PNGs <prefix>_0_loaded .. _6_paused and prints the state trail and the console tail.
Exit code 1 on a Python traceback in the console or when a wanted state never shows up.

--hero picks the hero with its number key on HERO_SELECT. --play N (integration) then plays N more seconds
before pausing: the player stays near the spawn corner, turning and holding fire, so the enemies walk up
to it. With the debug overlay on, the game publishes window.RWF_PERF twice a second (fps, ms per system,
alive enemies, nearest enemy distance); every sample is printed, plus the FPS p50 / p10 overall and with
an enemy within 4 cells ("close").
Needs network access to the pygame-web CDN and `pip install playwright`.
"""
import argparse
import os
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _perf_samples(lines):
    out = []
    for ln in lines:
        d = {}
        for tok in ln.split():
            if '=' in tok:
                k, v = tok.split('=', 1)
                try:
                    d[k] = float(v)
                except ValueError:
                    d[k] = v
        if 'fps' in d:
            out.append(d)
    return out


def _q(vals, q):
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * q))] if s else float('nan')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root', nargs='?', default=os.path.join(ROOT, 'game', 'build', 'web'))
    ap.add_argument('out', nargs='?', default=os.path.join(ROOT, 'tools', 'out', 'web'))
    ap.add_argument('--hero', default=None, choices=('vector', 'flicker', 'rampart'))
    ap.add_argument('--play', type=float, default=0.0)
    a = ap.parse_args()
    root = a.root
    out = a.out
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
    perf = []
    srv = subprocess.Popen([sys.executable, '-m', 'http.server', '8765', '--bind', '127.0.0.1'], cwd=root,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logs = []
    trail = []
    problems = []
    try:
        time.sleep(1.5)
        with sync_playwright() as p:
            b = p.chromium.launch(channel='msedge', headless=True,
                                  args=['--autoplay-policy=no-user-gesture-required'])
            pg = b.new_page(viewport={'width': 1280, 'height': 900})
            pg.on('console', lambda m: logs.append('[%s] %s' % (m.type, m.text)))
            pg.on('pageerror', lambda e: logs.append('[pageerror] %s' % e))

            def state():
                try:
                    v = pg.evaluate('() => (window.RWF_STATE === undefined ? null : String(window.RWF_STATE))')
                except Exception:
                    v = None
                if v and (not trail or trail[-1] != v):
                    trail.append(v)
                return v

            def wait(want, timeout, label):
                want = (want,) if isinstance(want, str) else tuple(want)
                t_end = time.time() + timeout
                while time.time() < t_end:
                    if state() in want:
                        return True
                    time.sleep(0.2)
                problems.append('%s: state %r never reached in %.0f s (now %r)' % (label, want, timeout, state()))
                return False

            def shot(name):
                pg.screenshot(path='%s_%s.png' % (out, name))

            pg.goto('http://127.0.0.1:8765/index.html')
            t_end = time.time() + 90
            while time.time() < t_end:
                if state() == 'TITLE' or any('ready to start' in l.lower() for l in logs):
                    break
                time.sleep(0.5)
            shot('0_loaded')
            if state() != 'TITLE':
                pg.mouse.click(640, 400)        # pygbag: the user gesture that starts Python
            ok = wait('TITLE', 60, 'boot')
            time.sleep(1.0)
            shot('1_title')
            if ok:
                pg.keyboard.press('Enter')      # TITLE -> HERO_SELECT
                ok = wait('HERO_SELECT', 10, 'title')
            if ok:
                time.sleep(0.5)
                pg.keyboard.press('ArrowRight')
                time.sleep(0.3)
                pg.keyboard.press('ArrowLeft')
                time.sleep(0.5)
                if a.hero:
                    pg.keyboard.press(str(('vector', 'flicker', 'rampart').index(a.hero) + 1))
                    time.sleep(0.5)
                shot('2_select')
                pg.keyboard.press('Enter')      # LOCK IN (VECTOR) -> COUNTDOWN
                ok = wait('COUNTDOWN', 10, 'select')
            if ok:
                time.sleep(0.3)
                pg.mouse.click(640, 400)        # pointer-lock gesture: must not fire during COUNTDOWN
                time.sleep(0.5)
                shot('3_countdown')
                ok = wait('PLAYING', 8, 'countdown')
            if ok:
                pg.keyboard.press('0')          # debug overlay (FPS, ms per system)
                pg.keyboard.down('w')
                time.sleep(1.5)
                pg.keyboard.up('w')
                pg.mouse.down()
                time.sleep(1.0)
                pg.mouse.up()
                time.sleep(2.0)
                shot('4_play')
                pg.mouse.move(700, 400)
                pg.keyboard.down('d')
                time.sleep(1.0)
                pg.keyboard.up('d')
                time.sleep(6.0)
                shot('5_later')
                if a.play > 0 and state() in ('PLAYING', 'INTERMISSION'):
                    # back toward the corner and keep turning while firing: enemies walk up to us
                    pg.keyboard.down('s')
                    time.sleep(1.0)
                    pg.keyboard.up('s')
                    t_end = time.time() + a.play
                    k = 0
                    pg.mouse.down()
                    while time.time() < t_end and state() in ('PLAYING', 'INTERMISSION'):
                        pg.mouse.move(640 + (60 if k % 2 else -60), 400)
                        time.sleep(0.5)
                        k += 1
                        try:
                            v = pg.evaluate('() => (window.RWF_PERF === undefined ? null : String(window.RWF_PERF))')
                        except Exception:
                            v = None
                        if v and (not perf or perf[-1] != v):
                            perf.append(v)
                        if k % 20 == 10:
                            shot('7_play_%02d' % (k // 20))
                    pg.mouse.up()
                    shot('8_played')
                if state() in ('PLAYING', 'INTERMISSION'):
                    pg.keyboard.press('Escape')     # pause (or pointer-lock loss -> auto-pause)
                    if wait('PAUSED', 5, 'pause'):
                        time.sleep(0.5)
                        shot('6_paused')
                else:
                    shot('6_after')
            b.close()
    finally:
        srv.terminate()
    print('\n'.join(l[:220] for l in logs[-40:]))
    print('--- state trail: %s' % ' -> '.join(trail))
    if perf:
        for ln in perf:
            print('PERF ' + ln)
        smp = [d for d in _perf_samples(perf) if d.get('st') == 'PLAYING' and d.get('fps', 0) > 0]
        close = [d for d in smp if d.get('near', 99) < 4.0]
        for label, lst in (('all', smp), ('close', close)):
            if lst:
                f = [d['fps'] for d in lst]
                t = [d['tot'] for d in lst]
                print('--- FPS %s: n %d, p50 %.1f, p10 %.1f, min %.1f; work ms p50 %.1f p90 %.1f; max enemies %d' % (
                    label, len(lst), _q(f, 0.5), _q(f, 0.1), min(f), _q(t, 0.5), _q(t, 0.9),
                    max(int(d.get('en', 0)) for d in lst)))
    tb = [l for l in logs if 'Traceback' in l]
    print('--- %d console lines, %d with a traceback' % (len(logs), len(tb)))
    for pr in problems:
        print('PROBLEM ' + pr)
    return 1 if (tb or problems) else 0


if __name__ == '__main__':
    sys.exit(main())
