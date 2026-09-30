# Review findings (Phase 3, partial)

Status: **not fixed yet.** The Phase 3 review was stopped early at the user's request after the bug and feel reviews and their verification finished.
The web/perf long-session review, the balance analysis and the fix pass did not run. Code state: `1183fd8`.

Each finding was checked by an independent verifier that tried to refute it. Full repro steps and suggested fixes are below each table.

## Confirmed (fix these next)

| id | severity | finding | file |
|---|---|---|---|
| feel-02 | high | Hit flash turns the target into a solid white silhouette that never ends under FLICKER fire: telegraphs, the white crosshair and body hitmarkers disappear on it | `game/rwf/render.py` |
| bug-2 | medium | A flanking Slicer (odd id) can wedge on a wall corner for good, just outside its 3.0 lunge range, and never attack | `game/rwf/enemies.py` |
| feel-04 | medium | Lock-On brackets are drawn at the previous frame's positions on every shot frame, so while turning they jump ~130 px off the targets and land on walls | `game/rwf/hero_vector.py` |
| feel-06 | medium | Hero select cards truncate 9 of 15 ability descriptions with '...', so a first-time player cannot read what the kit does | `game/rwf/screens.py` |
| feel-07 | medium | VECTOR's Heal Field pylon sprite covers the crosshair and lower view while you stand next to it, which is how the ability is used | `game/rwf/hero_vector.py` |
| feel-08 | medium | TROOPER windup telegraph is too subtle: the visor shifts lime to pale yellow and a ~7 px ring appears, while every other enemy's warning uses red | `game/rwf/enemies.py` |
| bug-3 | low | INTEGRATION_REPORT gets the boss-wave mechanism wrong: the wave does not clear when the Warden dies (escort and phase-2 summons must die too) | `design/INTEGRATION_REPORT.md` |
| bug-4 | low | Known issue #4 misstates why capture waves are short: contesters do arrive, but Detonator friendly fire and hold ranges end the contest, so an idle player captures in about 13 s | `design/INTEGRATION_REPORT.md` |
| bug-5 | low | RAMPART can quick-melee during Charge (spec: 'no swings while charging'), and the melee can hit the pinned target | `game/rwf/hero_base.py` |
| bug-7 | low | Known issue #6 timing items are imprecise: at the harness's 30 fps no measured cooldown ends early, and Heal Field emits one heal per frame (60/s on web) | `design/INTEGRATION_REPORT.md` |
| bug-8 | low | Spec decision 18 says clearing stage 3 'awards a medal', but no victory medal exists | `game/rwf/stats.py` |
| feel-09 | low | WARDEN stomp ring cannot be seen from inside the danger zone: the r 3.0 ring's near edge is behind or beside the camera when the stomp triggers (<= 2.5 cells) | `game/rwf/enemies.py` |
| feel-10 | low | Summary medals are labelled G/S/B, the same letters as the RANK grades (S/A/B/C) on the same screen | `game/rwf/screens.py` |
| feel-12 | low | During Lock-On the ult ring shows a big 'V', which reads as the quick-melee key V | `game/rwf/hud.py` |
| feel-13 | low | Title screen shows difficulty as asterisks and leaves SHIFT/SPACE and E unlabeled in the control hint | `game/rwf/screens.py` |
| feel-14 | low | Killing the WARDEN boss gets the same feedback as a trooper kill | `game/rwf/hud.py` |
| feel-15 | low | DEFEAT banner gives no cause of death | `game/rwf/screens.py` |

## Real behaviour, but written into the spec (decide whether to change the spec)

| id | severity | finding | file |
|---|---|---|---|
| feel-01 | high | One LMB click (fire) or Space (ability 1) skips the whole INTERMISSION: the stage-clear panel, the VICTORY! screen and the hero-swap window vanish in 1 frame | `game/rwf/screens.py` |
| feel-03 | medium | Clicking through death skips POTG and the summary: a player still firing sees POTG for 0.13 s and the summary for 0.43 s, then a new match starts | `game/rwf/screens.py` |
| feel-05 | medium | FLICKER viewmodel collides with the HUD (grips behind the hero plate and the SHIFT tile, blink pips on the gun, kick and muzzle flash over the plate), and the side-on guns point at each other rather than at the crosshair | `game/rwf/hero_flicker.py` |
| feel-11 | low | Headshot (crit) hitmarker is nearly the same as a body hit, and headshot kills look identical to body kills at the crosshair and in the pop-up | `game/rwf/hud.py` |
| bug-1 | medium | A single LMB click, or Space (the Blink/Sprint/Charge key), ends the 8 s intermission at once and closes the hero-swap window | `game/rwf/screens.py` |

## Unclear

| id | severity | finding | file |
|---|---|---|---|
| bug-6 | low | TIME PLAYED (and the per-minute medal rates) counts the countdown, the wave-clear delays and the intermissions | `game/rwf/app.py` |

## Still open from INTEGRATION_REPORT.md

- Ult charge is 1.5-3x faster than the 9.6 targets because waves end early (planned direction: ult damage gives no ult charge, longer/tougher waves, enemies contest the capture point, then retune ULT_COST per hero).
- Hero parity: FLICKER dies far more often than RAMPART in autoplay (check the bot policy first).
- No human playtest yet.

## Details

### feel-02: Hit flash turns the target into a solid white silhouette that never ends under FLICKER fire: telegraphs, the white crosshair and body hitmarkers disappear on it

- **Severity:** high  **File:** `game/rwf/render.py`
- **Verdict:** confirmed
- **Repro:** combat.py:253 sets FLAG_FLASH while now-last_hit < 0.06. render.paint_base variant 'f' (render.py:86) does fill((255,255,255), BLEND_RGB_MAX), which makes the sprite pure white. FLICKER fires every 0.05 s, so the flash is refreshed before it expires. Script scratchpad/flash.py holds fire on a 5000-HP target: FLICKER vs trooper at 5 cells is white in 116/145 frames (80%), and all 34/34 windup/attack frames are white. FLICKER vs an armed detonator at 3 cells: 37/37 frames white, 24/24 armed frames white (out_flash/flash_flicker_detonator_armed_a_0018.png: no blinking core, only the thin floor ring). VECTOR vs trooper: 42% white. In the crop of that detonator frame (crop_flash_c.png) the crosshair cannot be seen at all: it is white on white, and so are the white body hitmarkers. The telegraphs the player most needs (trooper windup, detonator fuse) are hidden exactly while the player is shooting that enemy.
- **Suggested fix:** Rate-limit and soften the flash. Keep a per-entity last_flash and set FLAG_FLASH only if now - last_flash >= 0.15 s, so there is at most one 60 ms flash every 150 ms. Make variant 'f' an additive tint, e.g. fill((110,110,110), BLEND_RGB_ADD), so the painted state (visor, core blink) stays readable. Give hero crosshairs and HUD hitmarkers a 1 px dark underlay (draw each line once in (0,0,0) offset by 1 px, then in colour) so they survive on white flashes and light walls.
- **Verifier evidence:** Reproduced with scratchpad/vf/flash.py: FLICKER vs trooper 116/145 frames flagged (80%), 34/34 windup/attack frames. FLICKER vs detonator 37/37, 24/24 armed. VECTOR vs trooper 42%. Slicer 9%. Code: combat.py:253 sets FLAG_FLASH while now-last_hit<0.06. render.paint_base variant 'f' does fill((255,255,255), BLEND_RGB_MAX), which turns every opaque pixel pure white. FLICKER pistol_interval is 0.05 s, shorter than the 0.06 s flash, so sustained hits keep the target permanently white. vf/out/flash_flicker_detonator_armed_a_0018.png: the detonator is a solid white blob with no visible core blink, and FLICKER's white crosshair (hero_flicker.py:338, col (255,255,255)) is invisible at screen centre. Spec 6.4 asks for a 60 ms white flash per hit. It does not ask for a permanent silhouette that hides telegraphs, so this is emergent, not by design.

### bug-2: A flanking Slicer (odd id) can wedge on a wall corner for good, just outside its 3.0 lunge range, and never attack

- **Severity:** medium  **File:** `game/rwf/enemies.py`
- **Verdict:** confirmed
- **Repro:** Script: <scratch>/rv/p14.py. It runs H.run with god mode and no director.
- Setup: player placed at (3.47, 10.4) facing 1.95 rad. Slicer spawn_at (8.5, 9.5) with an odd id.
- The slicer walks around, then sticks at x=6.22, y 8.90-9.11. The footprint corner touches wall cell (5,8).
- Its _flank target stays (4.03, 9.01) and its mode stays 'chase'.
- Distance to the player holds at 3.04-3.13, so the lunge (3.0) and melee (0.9) never trigger.
- Frames 60, 300, 600 and 899 all show the same spot. player_hurt = 0 over 30 s.

Cause:
- enemies.py:405-413 picks the flank point with LOS checked from the PLAYER.
- enemies.py:429-432 then steers the slicer in a straight line at that point, bypassing the flow field and steer_dir.
- The ±0.4 zig-zag never lifts it past the corner (it would need y >= 9.22).

Frequency (fuzz p9c.py, 1500 random approaches with forced odd ids): 2/1500 stick while the player keeps a fixed facing; 0/1500 when the player faces the slicer. A stuck slicer holds up the wave clear until the player finds it.
- **Suggested fix:** Steer toward the flank point with the flow field / steer_dir instead of the raw vector. Or accept the flank only when los(slicer, flank) passes a footprint-aware check. Also add a progress watchdog: if the slicer moved less than 50% of its expected distance for about 0.5 s, clear _flank and chase the player (steer_dir(p.x, p.y)).
- **Verifier evidence:** Reproduced with p14.py: the slicer sits at (6.22, 8.92-9.01), dist 3.08-3.12, mode 'chase', flank (4.03, 9.01) at frames 60/300/600/899, and player_hurt = 0. p14 changes e.id after __init__, so I checked separately (v2b.py) with naturally odd ids, reached by pre-spawning dummy enemies (make_world, seed 3, same setup). Ids 35, 65, 77, 135, 275, 405, 495, 665 and 779 all wedge at x = 6.22, y 8.90-9.11, dist 3.04-3.13, 'chase', with no hurt over 30 s, so it depends on the zig-zag phase and not on the id hack. The code path matches: enemies.py:405-413 checks the flank point's LOS from the player (world.los_budgeted(p.x, p.y, fx, fy)). Lines 429-432 then steer straight at the flank point (ux = fx - self.x), bypassing steer_dir. The lunge needs d <= slicer_lunge_range 3.0, and wall cell (5,8) is present. The spec (line 361) only says to steer for the point 1.5 behind the player and gives no stuck handling. An enemy that never attacks is a real AI defect.

### feel-04: Lock-On brackets are drawn at the previous frame's positions on every shot frame, so while turning they jump ~130 px off the targets and land on walls

- **Severity:** medium  **File:** `game/rwf/hero_vector.py`
- **Verdict:** confirmed
- **Repro:** _lock_targets (hero_vector.py:387-411) caches [(enemy, ScreenBox)] per world.frame. On a shot frame it is first called during update, before render, and uses last frame's world.projection. draw_overlay (line 470-473) then reuses those stale boxes. Script scratchpad/lockon.py (3 dummies, ult, hold fire, 95 px look per frame, about 4 rad/s): the bracket-to-sprite offset is 0 px on non-shot frames and 125-131 px on every shot frame (frames 21, 25, 28, 31, 35, 38). out_lock/lock_stale_0021.png shows the thick 'current target' bracket around empty wall at the crosshair and no bracket on the left dummy. In real bot play (feelplay.py vector 2 1, frame 786, 0.27 rad turn) the brackets sat 255 px away on a bare wall (out_play/g_vector_s2_ultused0_00786.png, confirmed by the dumped ScreenBoxes of frames 785/786). The result is jittery, detached brackets during the ult's signature visual.
- **Suggested fix:** In Vector.draw_overlay, re-read each cached enemy's current box: b = world.projection.get(e.id), and draw only if b and b.visible. Alternatively invalidate _lt_frame after render (e.g. key the cache on id(world.projection)). The targeting logic can keep using the cached list.
- **Verifier evidence:** Reproduced with scratchpad/vf/lockon.py. Bracket-to-sprite offset is 0 px on non-shot frames and 125-131 px on frames 21, 25, 28, 31, 35 and 38. Code: Vector._lock_targets (hero_vector.py:387-411) caches per world.frame, and world.frame is incremented in world.update (world.py:547). On a shot frame the first call happens during update (line 360), using world.projection from the previous render (render.py:586 assigns the new projection only during render). draw_overlay (line 470-473) then reuses those stale ScreenBoxes. vf/out/lock_stale_0021.png shows the thick current-target bracket around empty wall at the crosshair, and no bracket on the leftmost dummy. This is a presentation bug, not spec behaviour.

### feel-06: Hero select cards truncate 9 of 15 ability descriptions with '...', so a first-time player cannot read what the kit does

- **Severity:** medium  **File:** `game/rwf/screens.py`
- **Verdict:** confirmed
- **Repro:** HeroSelectScreen._card (screens.py:355-357) draws row[2] at x=84 with _fit(..., cw-94 = 206 px). Measured with the game font (scratchpad/kitfit.py). Truncated: VECTOR 'Full-auto hitscan rifle. Headshots...', 'Three rockets that burst on impa...', 'Press to run faster while moving f...', 'For 6 s every shot hits the target...'; FLICKER 'Or SHIFT. Zip 7 m the way you mo...', 'Jump back 3 s. Health and ammo...'; RAMPART 'Wide swing that hits everything i...', '600 HP shield that blocks enemy...', 'Rush forward, pin an enemy, sla...'. Visible in out/screen_HeroSelectScreen.png and in the web build (tools/out/web_flicker_2_select.png). The pause screen shows the full text, so the information exists but is cut on the screen where heroes are chosen.
- **Suggested fix:** Draw the description line at x=16 with max width cw-32 = 268 px. Measured: 13/15 then fit (widest 241 px). Shorten the two that do not: LOCK-ON (294 px, e.g. 'For 6 s, shots snap to the nearest target.') and CHARGE (274 px, e.g. 'Rush forward, pin and slam an enemy.').
- **Verifier evidence:** Measured with the game font (scratchpad/vf/kitfit2.py) at the card width of cw-94 = 206 px. 9 of 15 descriptions are truncated, exactly the 9 listed (for example LOCK-ON is 294 px and CHARGE is 274 px). With 268 px, 13 of 15 fit, and the widest is LOCK-ON at 294. Code: HeroSelectScreen._card draws row[2] at x=84 with _fit(..., cw-94) (screens.py:355-357). The pause kit uses k.w-346 = 374 px, so the full text shows there. Spec 6.2 requires only key and name on the card, so the truncated description line is an implementation detail, not a design decision.

### feel-07: VECTOR's Heal Field pylon sprite covers the crosshair and lower view while you stand next to it, which is how the ability is used

- **Severity:** medium  **File:** `game/rwf/hero_vector.py`
- **Verdict:** confirmed
- **Repro:** HealField.emit_visuals (hero_vector.py:217) always emits the 0.35 x 0.2 'heal_pylon' sprite. At 0.6-1.0 cells it renders 270-450 px tall with a large lime glow orb. Bot play shows the orb right on the crosshair during a fight (scratchpad/out_play/g_vector_s2_tel_slicer_windup0_00170.png: orb centred at about (560,430), pylon x 460-700). The same happens in g_vector_s2_crit0_00182.png (pylon x 210-440 beside the crosshair) and out/vector_draw_0142.png (lime blob over the ult ring). World barriers already fade near the camera (render.BARRIER_NEAR = 1.2); the pylon has no equivalent.
- **Suggested fix:** In HealField.emit_visuals, skip the pylon sprite when hypot(self.x-cam.x, self.y-cam.y) < ~1.2 (or emit it with a dim/NOSHADE variant). Keep the floor ring and the screen-edge glow, which already tell the player they are inside.
- **Verifier evidence:** HealField.emit_visuals (hero_vector.py:217) always emits the 0.35x0.2 'heal_pylon' sprite with FLAG_NOSHADE. There is no near-camera fade like render.BARRIER_NEAR=1.2. Projected height is 0.35*768/d, about 269-448 px at d 1.0-0.6. The bot frame out_play/g_vector_s2_tel_slicer_windup0_00170.png shows the lime orb right next to the crosshair and the pylon filling the lower centre during a fight. One nuance: the sprite top is at horizon+115/d (horizon = 384+pitch). At pitch 0 it stays below y≈499 within 1 cell, so it only reaches the crosshair when the player looks down (by about 115 px or more at 1 cell), as in the bot frame. The lower-view occlusion happens regardless. The spec requires the sprite but says nothing about near-camera behaviour, so this is emergent.

### feel-08: TROOPER windup telegraph is too subtle: the visor shifts lime to pale yellow and a ~7 px ring appears, while every other enemy's warning uses red

- **Severity:** medium  **File:** `game/rwf/enemies.py`
- **Verdict:** confirmed
- **Repro:** _paint_trooper (enemies.py:945-958): windup visor (255,255,200) vs idle (180,255,80), plus circle radius 7 width 2 at the muzzle. At the trooper's own hold range (5.5 cells) the sprite is about 1:1 scale, so the cue is a 26x5 px visor tint change and an ~8 px hollow ring (scratchpad/crop_tw.png, 4x zoom of out_play/g_flicker_s2_tel_trooper_windup0_00201.png; out/enemies_gallery.png row 1). Slicer, Warden and Detonator warnings are red. Troopers are the most common ranged damage source (bolt deaths in INTEGRATION_REPORT 4), so their 0.4 s warning should be the easiest to read.
- **Suggested fix:** Use the shared 'hot' language. Windup visor red (255,40,30), plus a filled additive muzzle glow of radius ~10-12 base px, or reuse the _HOT treatment (the red ring plus BLEND_RGB_ADD (60,0,0)) that _paint_image already applies for the PNG theme.
- **Verifier evidence:** _paint_trooper (enemies.py:945-958): windup visor (255,255,200) against idle (180,255,80), plus circle((70,42), r 7, width 2). tools/out/enemies_gallery.png shows 'trooper idle' and 'trooper windup' nearly identical. Slicer windup (red visor, raised blades), detonator armed (red ring) and warden windups (red outline) are all clearly red. The 4x crop scratchpad/crop_tw.png confirms a pale visor and a small hollow ring. The spec (4.4) asks only for a 'bright visor' and does not set the colour or subtlety, so the weak contrast is an implementation choice, not a design decision.

### bug-3: INTEGRATION_REPORT gets the boss-wave mechanism wrong: the wave does not clear when the Warden dies (escort and phase-2 summons must die too)

- **Severity:** low  **File:** `design/INTEGRATION_REPORT.md`
- **Verdict:** confirmed
- **Repro:** Report line 96: 'Boss-wave length equals the Warden's spawn-to-kill time, because the wave clears when the boss dies'. The results table also lists identical 'boss wave med s' and 'Warden spawn-kill med s' in all 12 rows.

Code: WaveDirector clears only when _count_remaining (waves.py:218) reaches 0. That counts every alive enemy, including summoned slicers, and the Warden's on_death does not remove its summons.

Evidence:
- p1.py: Warden pushed to phase 2, then killed at frame 13. 200 frames later the director is still 'active' with remaining 6 (3 troopers, 1 detonator, 2 summoned slicers).
- tools/autoplay.py, FLICKER stage 2 seed 7 (ap.json): the boss wave ran from t=90.6 to 150.3 (59.7 s), while the Warden's spawn->kill was 45.2 s.
- aggregate() computes the two columns separately (wave_by_kind['boss'] vs boss_median), so they need not match.
- **Suggested fix:** Correct the note and re-check the table, which should show both measured columns. If the design intends a boss wave to end with the boss, add a spec decision and remove the Warden's summons silently (no score) on its death.
- **Verifier evidence:** INTEGRATION_REPORT.md:96 says 'Boss-wave length equals the Warden's spawn-to-kill time, because the wave clears when the boss dies'. The code disagrees. waves.py:330-333 clears only when _count_remaining == 0, and _count_remaining (line 218) counts every alive enemy, summons included. Warden has no on_death that removes its summons. Running p1.py (Warden killed in phase 2 at frame 13): 200 frames later the director is still 'active' with remaining 6 (3 troopers, 1 detonator, 2 summoned slicers). The scratch ap.json has FLICKER s2 seed 7 with a boss wave of 90.58->150.26 (59.7 s) against a spawn_to_kill of 45.21 s. autoplay.aggregate computes wave_by_kind['boss'] (wave_start->wave_clear) and boss_median (boss_spawn->boss kill) separately. In ap.json the two coincide for VECTOR (85.54/85.54) and RAMPART (35.07/35.04), so identical medians are possible, but the stated mechanism is wrong.

### bug-4: Known issue #4 misstates why capture waves are short: contesters do arrive, but Detonator friendly fire and hold ranges end the contest, so an idle player captures in about 13 s

- **Severity:** low  **File:** `design/INTEGRATION_REPORT.md`
- **Verdict:** confirmed
- **Repro:** Script p3.py: god mode, a player who never shoots, standing on (10,10), start_wave 3/8/13.
- Captured at 14.3 / 12.9 / 12.9 s, contested only 71 / 28 / 28 frames.
- Standing at (4.5,4.5) instead: 'failed' at 90 s as expected.

Trace p3b.py (stage 1): contested from 10.5 s by 2 slicers and a detonator. At 12.0 s the Detonator arms and its self-blast (120 to enemies) kills both Slicers (80 pool), and capture resumes.

In the same trace:
- The Trooper holds at 6.0-6.5 cells from the point centre and the Eradicator closes only to about 4.5 (both well outside r 1.8), so neither contests.
- The trickle spawns at most 1 enemy per 2.5 s.

Report lines 157 and 204 say 'enemies chase the player rather than the point' and 'enemies don't path to the point'. But the player is on the point, and the chasers do reach it.
- **Suggested fix:** Rewrite the cause in sections 4.4 and 6.4: sparse trickle, Trooper/Eradicator hold bands of 4-7 cells, and Detonator blasts that kill the contesters. Design options: during capture waves, make ranged units hold relative to the objective; lower or skip Detonator blast damage to enemies inside the point; or start the trickle earlier and faster.
- **Verifier evidence:** Reproduced with p3.py (god mode, idle player on (10,10)): captured at 14.3 / 12.9 / 12.9 s for waves 3/8/13, contested 71 / 28 / 28 frames. At (4.5,4.5) it went neutral, then 'failed' at 90 s. The p3b.py trace: a slicer reaches 0.5 cells at 10.5 s ('contested'); at 12.0 s the detonator is 'armed' 1.4 cells away; at 12.5 s both slicers and the detonator are gone and capture resumes. The trooper holds at 6.0-6.5 cells and the eradicator at about 4.5-5.4, never inside r 1.8. Friendly fire is real: Detonator.explode calls splash(... det_enemy_dmg 120 ...) (enemies.py:538, spec line 425), and the slicer pool is 40+40. The report says 'enemies chase the player rather than the point' (line 157) and 'enemies don't path to the point' (line 204). But the bot and the player stand on the point, so chasing the player does reach it, and contesting does happen. The stated cause is wrong. The Detonator blast damage itself is by spec; this is a documentation error.

### bug-5: RAMPART can quick-melee during Charge (spec: 'no swings while charging'), and the melee can hit the pinned target

- **Severity:** low  **File:** `game/rwf/hero_base.py`
- **Verdict:** confirmed
- **Repro:** Script p13.py: RAMPART at (8.5,7.5) facing east, trooper at (11.5,7.5). Timeline: tap ab1 at frame 10, tap melee at frame 14.

Observed: ability_used 'melee' at frame 14 while p.charging is True.

Cause: Hero.handle_input (hero_base.py:210) calls quick_melee whenever can_act. Rampart gates the hammer and barrier on self.charging but has no way to gate V. So the cone (reach 1.5, ±30 deg) can hit the carried enemy at 0.7 in front and knock it back 0.3.

Spec 3.3 CHARGE: 'No barrier and no swings while charging.' Known issue #6 lists only 'quick-melee with the barrier up'.
- **Suggested fix:** Add a hook on Hero, e.g. melee_allowed(world) returning True by default, and check it in Hero.quick_melee. Rampart overrides it with `not self.charging and not self.barrier_up`, which also fixes known issue #6. Or list the charge case as a known issue.
- **Verifier evidence:** p13.py shows ability_used 'melee' at frame 14 while p.charging is True. My variant v5.py taps melee at frames 22 and 26, after the pin (pinned frames 19/20-40). It gives damage (22, 40.0, 'melee', 'trooper') and (26, 40.0, 'melee', 'trooper') on the carried target. In the code, Hero.handle_input (hero_base.py:209-210) calls quick_melee whenever can_act. quick_melee (299-311) has no hook. Rampart gates the hammer (line 337) and the barrier on self.charging, but nothing gates V. Spec 3.3 CHARGE says 'No barrier and no swings while charging.' 'Swings' could be read as hammer-only. However, the report's known issue #6 already treats the analogous 'quick-melee with the barrier up' as a violation of 'No swings while raised', so by the project's own reading this is a gap too.

### bug-7: Known issue #6 timing items are imprecise: at the harness's 30 fps no measured cooldown ends early, and Heal Field emits one heal per frame (60/s on web)

- **Severity:** low  **File:** `design/INTEGRATION_REPORT.md`
- **Verdict:** confirmed
- **Repro:** Script p5.py: tap each ability at frame 10 and read the ability_ready frame.
- VECTOR Helix 6 s: 180 frames. Heal Field 15 s: 450.
- FLICKER Blink 3 s: 90. Rewind 12 s: 360.
- RAMPART Flame Strike 6 s: 180. So none ended early at 30 fps.

Pure arithmetic with the same decrement loop:
- At dt=1/30, float residue adds a decrement (for example 6.0 needs 181), which cancels the start-frame decrement.
- At dt=1/60, 12 s and 15 s end 1 frame early while 3/5/6/7 s are exact.

RAMPART Charge is never early: its cooldown starts in think after the abilities update (228 frames = 0.6 s charge + 7.0 s).

HealField.update calls combat.heal every frame, so it emits 30/s at 30 fps and 60/s at the browser's 60 fps, not '30 a second'.
- **Suggested fix:** Rephrase item 6: 'a cooldown can end 1 frame early depending on frame rate and float round-off (not at 30 fps in the harness; e.g. 12/15 s at 60 fps)' and 'Heal Field emits one heal event per frame'. Or fix the root cause the same way as reloads: record the start frame in Ability.use/start_cooldown and skip that frame's dt in Ability.update.
- **Verifier evidence:** p5.py with the ability used at frame 10: VECTOR secondary 6 s = 180 frames, Heal Field 15 s = 450; FLICKER Blink 3 s = 90, Rewind 12 s = 360; RAMPART Flame Strike 6 s = 180. None ends early at 30 fps. RAMPART Charge is 228 frames (7.0 s cooldown after the charge ends, so never early). Replaying the Ability.update loop (hero_base.py:103-104) gives 91/151/181/211/361/451 decrements at dt=1/30 for 3/5/6/7/12/15 s, so the float residue cancels the start-frame decrement. At dt=1/60 it gives 181/301/361/421/720/900, so 12 s and 15 s end 1 frame early. Report line 207 ('a cooldown ends 1 frame (33 ms) early') is therefore wrong for the 30 fps harness. HealField.update (hero_vector.py:193-206) calls combat.heal every frame while inside and healing > 0, and heal emits once per call (combat.py ~576). That is one event per frame, 60/s at the browser's 60 fps, not a fixed '30 heal events a second' (report line 209).

### bug-8: Spec decision 18 says clearing stage 3 'awards a medal', but no victory medal exists

- **Severity:** low  **File:** `game/rwf/stats.py`
- **Verdict:** confirmed
- **Repro:** design/OVERWATCH_SPEC.md:64 (decision 18): 'Clearing stage 3 shows a VICTORY banner and awards a medal.'

stats.MEDALS (stats.py:12) holds only the 6 stat medals from the 6.2 table, and MatchStats subscribes to no 'victory' event. In the long endless run (p4.py), world.victory was True from stage 3 on, but medals() can never return a victory entry.

The spec contradicts itself (the decision table vs the 6.2 medal table). The code follows 6.2.
- **Suggested fix:** Decide in the spec. Either add a 'VICTORY' medal: MatchStats subscribes to 'victory' and medals() prepends ('VICTORY', 'gold', 'STAGE 3'), still capped at 6. Or remove the medal clause from decision 18.
- **Verifier evidence:** OVERWATCH_SPEC.md:64 (decision 18) says 'Clearing stage 3 shows a VICTORY banner and awards a medal.' stats.MEDALS (stats.py:11-18) holds only the 6 stat medals from the 6.2 table. MatchStats subscribes to damage/kill/shot/heal/barrier_damage/wave_clear/wave_start/player_death/ult_used (stats.py:61-69), with no 'victory'. medals() (151-162) only builds entries from MEDALS thresholds. No other module mentions medals except the summary drawing (screens.py:751-757). So a victory never produces a medal. This is a spec self-contradiction that the code resolves in favour of the 6.2 table, and neither the report nor the spec notes the gap.

### feel-09: WARDEN stomp ring cannot be seen from inside the danger zone: the r 3.0 ring's near edge is behind or beside the camera when the stomp triggers (<= 2.5 cells)

- **Severity:** low  **File:** `game/rwf/enemies.py`
- **Verdict:** confirmed
- **Repro:** Warden.emit_visuals (enemies.py:888-892) draws scene.ring(r=3.0, width 3) plus an inner expanding ring. The stomp only starts with the player within 2.5, i.e. inside the ring. At 1.7 cells, only ring points at depth >= 3.77 fall inside the 60 deg FOV, and those are behind the Warden sprite. What shows is short thin segments at the screen edges and the small inner ring (out_play/g_rampart_s3_tel_warden_stomp_windup0_03033.png, out/warden_stomp_0008.png). The only readable cue is the red outline on the Warden, with no sense of which way or how far to move in the 0.6 s windup.
- **Suggested fix:** While a Warden is in stomp_windup and the player is within ward_stomp_r, show a screen-space warning. Cheapest: reuse the cached low-HP vignette strips in red, pulsing, for the 0.6 s. Or add a 'STOMP' status chip. The spec 4.4 ring can stay.
- **Verifier evidence:** Warden.emit_visuals (enemies.py:884-892) draws ring r=3.0 plus an expanding inner ring. The stomp starts at d <= ward_stomp_range 2.5. Geometry check: with the player 1.7 from the Warden, the smallest ring depth inside the ±30° FOV is 3.77 (screen y≈486). The nearer part of the ring is behind or beside the camera, and the far part is behind the Warden sprite. Both frames show it: tools/out/warden_stomp_0008.png (only faint line fragments) and out_play/g_rampart_s3_tel_warden_stomp_windup0_03033.png (only the small orange inner ring and the Warden's red outline). The finding leaves out that SFX 'warn' also plays, but the visual claim holds. This is emergent; the spec ring stays.

### feel-10: Summary medals are labelled G/S/B, the same letters as the RANK grades (S/A/B/C) on the same screen

- **Severity:** low  **File:** `game/rwf/screens.py`
- **Verdict:** confirmed
- **Repro:** screens.py:761 blits tier[:1].upper() inside each medal disc. out/screen_summary.png (RAMPART): five 'S' discs and one 'G', then 'RANK A'. out_play/g_vector_flow_s2_SUMMARY_02831.png: two 'B' medal discs next to 'RANK B'. A first-time player reads the discs as grades ('S rank in eliminations').
- **Suggested fix:** Drop the letter, since the disc colour already encodes gold/silver/bronze, or draw a small star or ribbon glyph. Or print the tier word ('GOLD') in the tier colour above the stat name.
- **Verifier evidence:** screens.py:761 blits tier[:1].upper() inside each medal disc. With TIER_COLORS keys gold/silver/bronze this gives G/S/B. The rank letters are S/A/B/C/D (config.RANKS). tools/out/screen_summary.png shows five 'S' discs and one 'G' on the same page as 'RANK A'. Spec 6.2 describes coloured circles with the stat name and value. It never asks for a letter, so the collision comes from the implementation.

### feel-12: During Lock-On the ult ring shows a big 'V', which reads as the quick-melee key V

- **Severity:** low  **File:** `game/rwf/hud.py`
- **Verdict:** confirmed
- **Repro:** _draw_ult_ring (hud.py:1025) draws hs.name[:1] while ult_active_frac > 0, so VECTOR shows 'V' in the centre of the ring (out/hud_vector_0100.png, out_play/g_vector_s2_ultused0_00786.png). V is listed as QUICK MELEE in the kit and on the title hint. The ready state shows 'Q', so a letter in that ring is read as a key prompt.
- **Suggested fix:** Show the seconds left (ceil(ult_active_left)) or the cached ult icon (icon(cls,'ult',...)) instead of the hero initial.
- **Verifier evidence:** hud.py:1022-1025 draws core.text(hs.name[:1], 'l', WHITE) while ult_active_frac > 0, so VECTOR shows 'V'. It is visible in scratchpad/vf/out/lock_stale_0021.png. V is the global quick-melee key (hero_base.py:210 inp.hit('melee') for every hero, and 'V MELEE' in the title hint). The ready state shows 'Q', a real key prompt, in the same ring. Spec 6.3 only says 'While active, the ring drains in white' and does not specify the centre text, so the initial letter is an implementation choice.

### feel-13: Title screen shows difficulty as asterisks and leaves SHIFT/SPACE and E unlabeled in the control hint

- **Severity:** low  **File:** `game/rwf/screens.py`
- **Verdict:** confirmed
- **Repro:** screens.py:238 renders 'DAMAGE  *', 'DAMAGE  ***', 'TANK  **' (out/screen_TitleScreen.png), which reads like footnote marks. The hero select screen draws real stars with _star(). screens.py:252 hint: '... RMB/F ALT   SHIFT/SPACE   E   Q ULT ...': SHIFT/SPACE and E have no verb, unlike every other entry.
- **Suggested fix:** Use _star() (as in HeroSelectScreen._card) under each title portrait. Change the hint to '... SHIFT/SPACE + E ABILITIES   Q ULT ...'.
- **Verifier evidence:** screens.py:238 renders '%s  %s' % (cls.ROLE, '*' * int(cls.DIFFICULTY)), which gives e.g. 'DAMAGE  *'. HeroSelectScreen._card draws real stars with _star(). The screens.py:252 hint reads '... RMB/F ALT   SHIFT/SPACE   E   Q ULT   V MELEE ...', so SHIFT/SPACE and E are the only entries without a verb. The spec's TITLE contents do not prescribe either, so both are implementation text.

### feel-14: Killing the WARDEN boss gets the same feedback as a trooper kill

- **Severity:** low  **File:** `game/rwf/hud.py`
- **Verdict:** confirmed
- **Repro:** HUD._on_kill (hud.py:509-518) has no boss branch. Killing the Warden produces the usual 22 px 'ELIMINATED WARDEN +450' pop-up and a feed row, then the generic 'WAVE CLEAR' banner (out_play/g_rampart_s3_bosskill_late0_03749.png). There is no slow-mo, shake or banner, unlike ult_used, which gets slow-mo, shake and a callout. The climax of every stage lands flat.
- **Suggested fix:** On kill with d['boss'] set self.banner = ([(name + ' DESTROYED', 'xl', KIND_COLORS['warden'])], ...) and have app apply world.clock.slowmo(*C.ULT_SLOWMO) plus a shake on the same event, as _Match._on_ult_used does.
- **Verifier evidence:** HUD._on_kill (hud.py:509-518) has no boss branch: the same feed row, pop-up and 'kill' hitmarker. Warden has no on_death override (the class list in enemies.py shows on_death only at _Robot:275, Detonator:547 and Eradicator:696). It gets the generic _Robot burst of 10 debris particles, with no shake or slow-mo. sfx.attach has no boss-kill hook, and app only applies slowmo and shake on ult_used (_Match._on_ult_used). The stat and POTG code do count d['boss'], so the data exists. The spec never asks for special boss-kill feedback, so the missing climax is a real gap rather than a design decision.

### feel-15: DEFEAT banner gives no cause of death

- **Severity:** low  **File:** `game/rwf/screens.py`
- **Verdict:** confirmed
- **Repro:** EndBanner(victory) (screens.py:552+) only draws DEFEAT/VICTORY. In bot deaths (INTEGRATION_REPORT: bolt, melee, lunge, stomp, sentry) the frozen frame often does not show the killer (out_play/g_vector_flow_s2_END_BANNER_02591.png: close-range blob, no attribution). New players cannot tell what to avoid.
- **Suggested fix:** Have the HUD remember the last player_hurt (ability plus source KIND), and pass it to EndBanner to draw a small 'ELIMINATED BY DETONATOR (BLAST)' line under the band.
- **Verifier evidence:** EndBanner.draw (screens.py:570-581) draws only the band and 'VICTORY'/'DEFEAT'. There is no cause-of-death anywhere: HUD._on_kill returns early for the player's own death (hud.py:511-512), so no kill-feed row names the killer either. The frozen frame keeps any recent damage arc (direction only). Spec 6.2 describes the banner minimally but does not rule out an attribution line, so this is a valid (low-severity) addition rather than a contradiction of the spec.

### feel-01: One LMB click (fire) or Space (ability 1) skips the whole INTERMISSION: the stage-clear panel, the VICTORY! screen and the hero-swap window vanish in 1 frame

- **Severity:** high  **File:** `game/rwf/screens.py`
- **Verdict:** refuted
- **Repro:** IntermissionOverlay.handle (screens.py:504-505) returns 'skip' on _click(ev) or _confirm(ev). _confirm includes K_SPACE, which KEYMAP also maps to 'ab1' (sprint, blink or charge). The mouse is locked here and LMB is primary fire, so the player is still in combat mode. Script scratchpad/inter.py uses h.run('vector', debug start_wave=15, autokill=1.0) and taps 'fire' on the first INTERMISSION frame. No input: INTERMISSION lasts 241 frames (8.03 s). One fire tap: 1 frame (0.03 s). A bot run (feelplay.py rampart 3 1) logged stage_clear stage 3 at 127.0 s and the stage-4 wave_start at 127.1 s, so the VICTORY!/ENDLESS MODE header was on screen for about 0.1 s because the bot was firing. Expected: the 8 s panel stays up until a deliberate confirm.
- **Suggested fix:** In IntermissionOverlay.handle, skip only on K_RETURN/K_KP_ENTER. Drop _click and K_SPACE, since both are combat inputs while the mouse is locked. Optionally add a 1.0 s guard like EndBanner.SKIP_AFTER. Change the hint at p.y+232 to 'ENTER - SKIP'. The spec 2/6.2 table ('Click' skips the intermission) conflicts with 6.1 (mouse locked in INTERMISSION) and should be amended the same way.
- **Verifier evidence:** The mechanism is real. I re-ran scratchpad/vf/inter.py: with no input INTERMISSION lasts 241 frames (8.03 s); one 'fire' tap on the first frame ends it after 1 frame. Space also skips, because screens._confirm includes K_SPACE. The harness 'ab1' tap sends LSHIFT, so that run did not skip. But this is the specified design. Spec section 2 input table: 'Skip intermission / POTG | Enter or Space | Click'. Spec 6.2 INTERMISSION: 'Enter or Space skips.' The panel also advertises it ('ENTER / SPACE / CLICK - SKIP', screens.py:543). The finding admits this and asks for a spec amendment. The 'still in combat' premise is also overstated: waves.py:334-347 starts INTERMISSION only after the 3.0 s WAVE_CLEAR_DELAY that follows the last kill (my repro tapped on the first frame after that empty delay). The bot log timing reflects the bot's constant firing. The one real design wrinkle is that Space is also ab1 while the world is live in INTERMISSION. Changing that is a spec change, not a defect fix.

### feel-03: Clicking through death skips POTG and the summary: a player still firing sees POTG for 0.13 s and the summary for 0.43 s, then a new match starts

- **Severity:** medium  **File:** `game/rwf/screens.py`
- **Verdict:** refuted
- **Repro:** Guards: PotgScreen.handle (screens.py:613-615) skips on any KEYDOWN or click with no guard. EndBanner has SKIP_AFTER 0.6. SummaryScreen has INPUT_GUARD 0.35 and a click anywhere means PLAY AGAIN. Script scratchpad/deathmash.py: VECTOR ults 3 weak dummies (so a POTG exists), kill_player_at=150, and taps fire every 4 frames (7.5 clicks/s, typical when dying mid-fight). State sequence: PLAYING 150, END_BANNER 18, POTG 4, SUMMARY 13, then action 'again'. The POTG, medals and rank are effectively never seen.
- **Suggested fix:** PotgScreen: ignore input for the first ~1.0 s and skip only on Enter/Space/Esc, not LMB or movement keys. SummaryScreen: raise INPUT_GUARD to ~1.0 s and require Enter, or a click inside an explicit PLAY AGAIN button rect, instead of a click anywhere. EndBanner: keep SKIP_AFTER but accept only confirm keys.
- **Verifier evidence:** The sequence reproduces with scratchpad/vf/deathmash.py: PLAYING 150, END_BANNER 18, POTG 4, SUMMARY 13, action 'again'. But the repro clicks at 7.5 Hz from frame 100 to 400, which means clicking continuously for at least 1.17 s after death. EndBanner.SKIP_AFTER=0.6 already absorbs the realistic post-death reaction window. Every skip input involved is specified. Spec 6.1: 'POTG(<=6s, any key skips...)' and 'SUMMARY --Enter/click--> COUNTDOWN'. Spec 6.2 POTG: 'Any key or click skips'. The spec 2 table also lists Click for the POTG skip. The mouse is unlocked in these states, so the clicks are not combat inputs there. A short POTG input guard would be spec-compatible polish, but the behaviour described is by design.

### feel-05: FLICKER viewmodel collides with the HUD (grips behind the hero plate and the SHIFT tile, blink pips on the gun, kick and muzzle flash over the plate), and the side-on guns point at each other rather than at the crosshair

- **Severity:** medium  **File:** `game/rwf/hero_flicker.py`
- **Verdict:** refuted
- **Repro:** Constants GUN_Y=590, GUN_H=130, GUN_RIGHT_X=668, kick_px=+30 (downward). Left grip is at x 234-266, y 650-720, under the hero plate (x 8-400, y 656-764, alpha 170), so it shows through between 'FLICKER' and the HP number. It is also visible in the browser build (tools/out/web_flicker_4_play.png). Right grip x 758-790, y 650-720 sits directly behind the SHIFT tile (x 760-812). The blink pips (x 774-798, y 676) always sit on the grip, and an empty pip (60,64,76) on the gun body (38,42,55) is nearly invisible (scratchpad/crop_fl_pips.png). On each shot the gun drops 30 px into the HUD band, and the left muzzle flash is centred at (359, 642) with 48 px spikes over the plate's top edge next to the HP bar (crop_fl_left.png, from out/fl_vis_0027.png). The guns are side-profile rectangles with barrels facing each other horizontally (y ~600-620), so they read as aimed at each other, not at the target. Tracer's pistols point forward and in.
- **Suggested fix:** Cheap layout pass. Raise GUN_Y to ~520 (grip bottom 650 < plate top 656; barrels stay below the 200x200 crosshair box, which ends at y 484). Make the kick upward/back (kick_px -10 or smaller +8). Rotate each gun ~15-20 deg toward the screen centre once in _assets() with pygame.transform.rotate (the rotated sprite is cached, so no per-frame cost). In hud._draw_tiles, draw empty pips brighter, e.g. (130,136,150) with a 1 px dark border, so they read on any viewmodel.
- **Verifier evidence:** The geometry is accurate. Right gun at x 668, y 590. Grip rect (90,60,32,70) gives screen x 758-790, y 650-720. The mirrored left grip is at x 234-266. The left muzzle is at x 359, y 612 (+30 kick = 642). Flash spikes reach r*2.2 = 48 px. But the complained-about look is specified. Spec line 256: 'Port the existing twin-pistol viewmodel (draw_gun), with each gun kicking 30 px on its own shot.' Spec line 224: 'The HUD is drawn on top of it.' The original draw_gun (git 40cb4f3 game/main.py) uses the same side-on barrels facing each other and a downward recoil (+55 px) at y H-80, even lower than now. The code comment at hero_flicker.py:494 says the grips intentionally 'run into' the HUD band. The only non-spec residue is minor: empty charge pips (60,64,76) drawn over the dark grip (hud.py _draw_tiles) have low contrast.

### feel-11: Headshot (crit) hitmarker is nearly the same as a body hit, and headshot kills look identical to body kills at the crosshair and in the pop-up

- **Severity:** low  **File:** `game/rwf/hud.py`
- **Verdict:** refuted
- **Repro:** HITMARKS body (10 px, 2 px wide, white) vs crit (14 px, 2 px wide, white with 5 px COL_CRIT tips) at hud.py:815-820. Zoomed crop scratchpad/crop_crit_fl.png (from out_play/g_flicker_s2_crit0_00184.png): the crit reads as a slightly longer white X. During FLICKER's 20 Hz body markers it is lost. A crit kill shows the plain red kill X. The pop-up's crit accent bar is COL_CRIT (255,60,40) vs the normal FEED_VICTIM (255,90,80), which look the same. Only the 14 px skull in the kill feed differs.
- **Suggested fix:** Draw the crit marker entirely in COL_CRIT (or gold) at 3 px width. For a crit kill, add the small skull (hud._draw_skull) under the X, or use a clearly different pop-up accent (e.g. gold) and a 'HEADSHOT' suffix in the pop-up.
- **Verifier evidence:** The marker geometry matches the spec exactly. Spec 6.3: 'Body: white, length 10, 0.12 s. Crit: length 14 with red tips, 0.18 s, SFX crit. Kill: red X of length 18.' hud.py:54 and 814-820 implement exactly that, and a crit kill using the kill X also follows the spec. The finding also leaves out the distinct 'crit' ding (spec 6.4). Its claim that crits get 'lost' among FLICKER's 20 Hz body markers is wrong: HUD._on_damage (hud.py:502-507) keeps the stronger marker (crit over body) for its full 0.18 s life. The only non-spec residue is minor: the pop-up accent colours COL_CRIT (255,60,40) and FEED_VICTIM (255,90,80) are close. The crit skull in the kill feed does distinguish crits.

### bug-1: A single LMB click, or Space (the Blink/Sprint/Charge key), ends the 8 s intermission at once and closes the hero-swap window

- **Severity:** medium  **File:** `game/rwf/screens.py`
- **Verdict:** refuted
- **Repro:** Script: <scratch>/rv/p8.py. Start with start_wave=5 and autokill 0.5 on FLICKER, then send one input on the first INTERMISSION frame.

Observed:
- 'fire' tap (MOUSEBUTTONDOWN 1): INTERMISSION lasts 1 frame (frames 106->107). The director is then stage 2, wave 1, 'active'.
- Space KEYDOWN: also 1 frame, and a Blink fires on the same frame (ability_used ab1 = 1).
- No input: 241 frames (8 s).

Cause: IntermissionOverlay.handle (screens.py:504) has `if _confirm(ev) or _click(ev): return 'skip'`, and _confirm includes K_SPACE, which KEYMAP also maps to 'ab1'.

Why it matters:
- Spec 6.1 says 'Enter skip'. Spec 6.2 says 'Enter or Space skips'. A mouse click is not in either.
- The mouse stays locked during INTERMISSION and the hero can act, so a reflexive shot, a Blink, a Sprint or a Charge instantly spawns the next stage.
- The player also loses the only 1/2/3 swap window.

Expected: the intermission runs its 8 s unless the player deliberately confirms.
- **Suggested fix:** Remove `_click(ev)` from IntermissionOverlay.handle and skip only on K_RETURN / K_KP_ENTER; drop Space, because it is 'ab1' for all 3 heroes. Update the footer 'ENTER / SPACE / CLICK - SKIP' and spec 6.2 to match.
- **Verifier evidence:** The behaviour reproduces: p8.py gives an INTERMISSION of 1 frame (106->107) after an LMB tap or a Space press, versus 241 frames with no input, and Space also fires a Blink on that frame. But it is by design. The spec's section 2 controls table (OVERWATCH_SPEC.md:175) reads '| Skip intermission / POTG | Enter or Space | Click |'. Its third column is 'Browser-safe fallback / note', so a click is an explicitly specified way to skip. Section 6.2 (line 719) also lists Space, and line 162 makes Space the ab1 fallback. So the Space/ab1 overlap and click-to-skip are both written into the spec. The finding's premise ('A mouse click is not in either') missed section 2. screens.py:504 (_confirm or _click) and the footer 'ENTER / SPACE / CLICK - SKIP' implement the spec as written. At most this is a design concern for the spec, not a code bug.

### bug-6: TIME PLAYED (and the per-minute medal rates) counts the countdown, the wave-clear delays and the intermissions

- **Severity:** low  **File:** `game/rwf/app.py`
- **Verdict:** unclear
- **Repro:** Script p11.py: H.run(vector, 95 frames) with skip_countdown False and the director on.
- States: 90 COUNTDOWN + 5 PLAYING.
- stats.time_played = 3.167 s, although only 5 frames were played.

Cause: app.py:321 calls self.stats.update(w, dt) in every SIM state (COUNTDOWN, PLAYING, INTERMISSION).

Effect: over 3 stages about 3 s + 14 x 3 s clear delays + 2 x 8 s intermissions (~61 s) of non-combat time goes into mins. That deflates ELIMINATIONS/min, DAMAGE/min and SUPPORT/min, and shows a TIME PLAYED that includes the 'MATCH STARTS IN' countdown.
- **Suggested fix:** Accumulate time_played only while state == 'PLAYING' (or while director.in_combat for the rate stats), or call stats.update only outside COUNTDOWN. Document the choice in spec 6.2.
- **Verifier evidence:** The facts reproduce. p11.py gives 90 COUNTDOWN + 5 PLAYING frames and time_played = 3.167 s. app.py:318-321 calls self.stats.update(w, dt) for every SIM_STATES entry ('COUNTDOWN', 'PLAYING', 'INTERMISSION'; app.py:30), and stats.update adds dt unconditionally (stats.py:122). But no spec text defines time_played as combat-only. Section 6.2 only says 'Rate stats use minutes = max(1, time_played / 60)', and the 6.1 table says the world updates during COUNTDOWN and INTERMISSION. The only combat-only rule (line 660, in_combat) covers passive ult, not stats. Overwatch's own TIME PLAYED includes non-combat time. Whether this is a defect is a design choice the spec leaves open.
