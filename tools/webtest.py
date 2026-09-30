"""Headless-browser smoke test of a pygbag build (FOUNDATION tool, not shipped).

    python -X utf8 tools/webtest.py [web_root=game/build/web] [out_prefix=tools/out/web]

Serves web_root on 127.0.0.1:8765 and opens index.html in headless Microsoft Edge (Playwright).
The game publishes its screen state as window.RWF_STATE (app.py via core.web_set: TITLE, HERO_SELECT,
COUNTDOWN, PLAYING, PAUSED, ...), and every step waits for the state it needs instead of sleeping
blindly, so it doesn't matter whether pygbag starts Python on its own or waits for a click:
    start gesture (only if needed) -> TITLE, Enter -> HERO_SELECT, Right/Left, Enter -> COUNTDOWN,
    click (pointer lock; must not fire) -> PLAYING, '0' (debug overlay: FPS, ms per system),
    W held, fire held -> screenshots, D held -> later screenshot, Esc -> PAUSED.
Saves PNGs <prefix>_0_loaded .. _6_paused and prints the state trail and the console tail.
Exit code 1 on a Python traceback in the console or when a wanted state never shows up.
Needs network access to the pygame-web CDN and `pip install playwright`.
"""
import os
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'game', 'build', 'web')
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'tools', 'out', 'web')
    os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
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
    tb = [l for l in logs if 'Traceback' in l]
    print('--- %d console lines, %d with a traceback' % (len(logs), len(tb)))
    for pr in problems:
        print('PROBLEM ' + pr)
    return 1 if (tb or problems) else 0


if __name__ == '__main__':
    sys.exit(main())
