"""Headless-browser smoke test of a pygbag build (FOUNDATION tool, not shipped).

    python -X utf8 tools/webtest.py [web_root=game/build/web] [out_prefix=tools/out/web]

Serves web_root on 127.0.0.1:8765, opens index.html in headless Microsoft Edge
(Playwright), then drives: pygbag start click -> TITLE click -> HERO SELECT Enter
-> COUNTDOWN click (pointer lock) -> PLAYING with '0' (debug overlay: FPS), W and
fire held. Saves PNGs <prefix>_0_loaded .. _5_later and prints the console log.
Exit code 1 if the console shows a Python traceback.
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
    try:
        time.sleep(1.5)
        with sync_playwright() as p:
            b = p.chromium.launch(channel='msedge', headless=True,
                                  args=['--autoplay-policy=no-user-gesture-required'])
            pg = b.new_page(viewport={'width': 1280, 'height': 900})
            pg.on('console', lambda m: logs.append('[%s] %s' % (m.type, m.text)))
            pg.on('pageerror', lambda e: logs.append('[pageerror] %s' % e))
            pg.goto('http://127.0.0.1:8765/index.html')
            for _ in range(90):
                time.sleep(1)
                if any('ready to start' in l.lower() for l in logs):
                    break
            pg.screenshot(path=out + '_0_loaded.png')
            pg.mouse.click(640, 400)            # pygbag: user gesture starts python
            time.sleep(6)
            pg.screenshot(path=out + '_1_title.png')
            pg.mouse.click(640, 400)            # TITLE -> HERO SELECT
            time.sleep(1.5)
            pg.keyboard.press('ArrowRight')
            time.sleep(0.3)
            pg.keyboard.press('ArrowLeft')
            time.sleep(0.5)
            pg.screenshot(path=out + '_2_select.png')
            pg.keyboard.press('Enter')          # LOCK IN -> COUNTDOWN
            time.sleep(1.0)
            pg.mouse.click(640, 400)            # pointer lock gesture (never fires)
            time.sleep(0.5)
            pg.screenshot(path=out + '_3_countdown.png')
            time.sleep(3.0)
            pg.keyboard.press('0')              # debug overlay (FPS)
            pg.keyboard.down('w')
            time.sleep(1.5)
            pg.keyboard.up('w')
            pg.mouse.down()
            time.sleep(1.0)
            pg.mouse.up()
            time.sleep(2.0)
            pg.screenshot(path=out + '_4_play.png')
            pg.mouse.move(700, 400)
            pg.keyboard.down('d')
            time.sleep(1.0)
            pg.keyboard.up('d')
            time.sleep(6.0)
            pg.screenshot(path=out + '_5_later.png')
            b.close()
    finally:
        srv.terminate()
    print('\n'.join(l[:220] for l in logs[-60:]))
    bad = [l for l in logs if 'Traceback' in l or 'Error:' in l and 'python' in l.lower()]
    print('--- %d console lines, %d suspicious' % (len(logs), len(bad)))
    return 1 if any('Traceback' in l for l in logs) else 0


if __name__ == '__main__':
    sys.exit(main())
