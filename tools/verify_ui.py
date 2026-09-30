"""Render UI previews and exercise the real pause/resume event loop headlessly."""
import os
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import asyncio
from pathlib import Path
import sys
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'game'))
import main as game

out = root / 'qa'
out.mkdir(exist_ok=True)
screen = game.pygame.display.set_mode((game.W, game.H))
game.load_assets()
assert len(game.ASSETS) == 4, 'Missing game art'
for rank in ('normal', 'elite', 'boss'):
    assert game.ASSETS['dokkaebi-'+rank].get_at((0, 0)).a == 0, 'Sprite background is opaque'
game.draw_title_scene(screen)
game.pygame.image.save(screen, out / 'title.png')
player = game.Player()
player.x, player.y, player.angle = 1.5, 5.5, 0
wave = game.WaveManager()
wave.wave = 3
wave.robots = [game.Robot(4.5, 5.6, 'normal'), game.Robot(7, 5.3, 'elite'), game.Robot(10, 5.7, 'boss')]
game.render_world(screen, player.x, player.y, player.angle, player.pitch, wave.robots, [])
game.draw_hud(screen, player, wave)
game.pygame.image.save(screen, out / 'gameplay.png')
game.draw_pause_overlay(screen)
game.pygame.image.save(screen, out / 'pause.png')
game.draw_game_over_scene(screen, 27, 1825, 5, 1)
game.pygame.image.save(screen, out / 'results.png')
start = time.perf_counter()
for _ in range(30):
    game.render_world(screen, player.x, player.y, player.angle, player.pitch, wave.robots, [])
print('World render mean:', round((time.perf_counter()-start)*1000/30, 2), 'ms')

class ObservedWave(game.WaveManager):
    updates = 0
    def update(self, player, dt):
        ObservedWave.updates += 1
        super().update(player, dt)

game.WaveManager = ObservedWave

async def verify_inputs():
    task = asyncio.create_task(game.run_game())
    try:
        await asyncio.sleep(.1)
        game.pygame.event.post(game.pygame.event.Event(game.pygame.KEYDOWN, key=game.pygame.K_RETURN))
        await asyncio.sleep(.2)
        assert ObservedWave.updates > 0, 'Enter did not start game'
        game.pygame.event.post(game.pygame.event.Event(game.pygame.KEYDOWN, key=game.pygame.K_ESCAPE))
        await asyncio.sleep(.1)
        paused_count = ObservedWave.updates
        await asyncio.sleep(.2)
        assert ObservedWave.updates == paused_count, 'Simulation advanced during ESC pause'
        game.pygame.event.post(game.pygame.event.Event(game.pygame.KEYDOWN, key=game.pygame.K_ESCAPE))
        await asyncio.sleep(.15)
        assert ObservedWave.updates > paused_count, 'ESC did not resume simulation'
        game.pygame.event.post(game.pygame.event.Event(game.pygame.WINDOWFOCUSLOST))
        await asyncio.sleep(.1)
        focus_count = ObservedWave.updates
        await asyncio.sleep(.15)
        assert ObservedWave.updates == focus_count, 'Focus loss did not pause simulation'
        print('PASS: title start, ESC pause, ESC resume, focus-loss pause')
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    game.pygame.event.post(game.pygame.event.Event(game.pygame.KEYDOWN, key=game.pygame.K_RETURN))
    assert await asyncio.wait_for(game.game_over_screen(screen, game.pygame.time.Clock(), 27, 1825, 5, 1), .5)
    print('PASS: result screen restart')

asyncio.run(verify_inputs())
game.pygame.quit()
