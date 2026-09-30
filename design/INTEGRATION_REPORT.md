# INTEGRATION REPORT (Phase 2, spec 7.3 / 9.6)

Branch `overwatch`, built on the frozen FOUNDATION commit 7dbe4bb. Branch overrides applied: omnic theme only,
no `game/assets`, standard pygbag packing of `game/`, presentation code kept in the presentation files.

## 1. Merge

The five builder branches were merged with `--no-ff`, in this order, with **no conflicts** (each touched only its
own files):

| Branch | Builder commit(s) | Merge commit |
|---|---|---|
| ow-vector | bbb9d56 | ad27668 |
| ow-flicker | 780c517 | 543dcec |
| ow-rampart | 0023833 | 53d39d7 |
| ow-enemies | acb862f | b1cf7ad |
| ow-hud | f48e8cb, d87e52e | 12cceef |

Right after the merge, `--suite all` (110 checks), `--suite all --no-assets` and `--suite perf` all passed. No
cross-file breakage showed up. The only warning was the stale `game.apk`, which the rebuild in section 5 fixed.

## 2. CORE REQUESTs

| From | Request | What was done |
|---|---|---|
| ENEMIES | `render.build_scene` draws every barrier with a fixed blue edge and no hit feedback | `combat.Barrier` now takes `edge`, `color_hit`/`edge_hit`, `color_low`/`edge_low` and `z1`, all optional. `render._barrier_look` applies three rules to every world barrier: a 0.08 s hit flash, a tint below 30% HP, and a fade within 1.2 cells of the camera. The Eradicator's `_EnemyBarrier` subclass (`owner_view_only`) and its hand-drawn segment were removed. It is now a plain `Barrier` with red-orange colours, and the renderer draws it. Checked visually for base, flash and low HP. |
| ENEMIES (minor) | `Enemy.fire_bolt` hard-codes `ability='bolt'`, the core colour and the size | `fire_bolt(..., *, ability='bolt', core=..., size=0.08, z=0.45)`. `enemies._Robot.shoot` is now a thin wrapper over it. |
| ENEMIES (minor) | Can't tell "blocked by the barrier" apart from god mode | New `combat.player_barrier_between(world, ax, ay, bx, by)` returns `(t, barrier)` or None. `enemy_hits_player` uses it, and so does `enemies._crosses_player_barrier`, which is now 2 lines. |
| FLICKER | Rewind sends `sfx` blink with `variant='rewind'` | `sfx._on_sfx` resolves a variant in this order: the variant's own name if it has a recipe (`rewind`, which already existed), then `<name>_<variant>`, else the plain name. |
| FLICKER (non-blocking) | A reload finishes one frame early (29 frames for 1.0 s) | `Hero.start_reload` records the frame it starts in, and `update` skips that frame's dt. A float epsilon was added at the end of the reload. Reloads now take exactly 30 / 45 frames (1.0 / 1.5 s). Checks: FLICKER 1.00 s auto and manual; VECTOR 45 frames. |
| RAMPART (optional) | `h.spawn_at(world, kind, x, y, **attrs)` | Added to `tools/smoke.py`. It refuses a spot inside a wall. `check_rampart.py` uses it, and its `_spawn_at` workaround is gone. |
| VECTOR / RAMPART notes | The `heal` sfx is unmapped; there is no low hammer | New `heal` and `hammer_low` recipes. RAMPART's charge impact now emits `hammer` with `variant='low'`. |
| VECTOR / HUD notes | Ult drain, `minimap_ring` | Already handled by HUD_UX. Verified only. |

A new foundation check, `check_integration_core_requests`, covers every item above.

## 3. Other integration changes

- **`tools/autoplay.py`:** the balance bot (section 4).
- **Balance levers (spec 9.6):**
  - `ULT_COST` +10%.
  - Enemy damage to the player -15%, via `enemies.TUNING['player_damage_scale'] = 0.85`, applied through `_pd()` to bolts, melee, the lunge, the detonator blast and chain, and the stomp. Enemy-on-enemy blast damage is not scaled.
  - The checks that pin those numbers (`check_foundation`, `check_vector`, `check_flicker` attrs, and the damage asserts in `check_enemies`) now follow the lever.
- **`app.py`:** on the web only, while the debug overlay (key 0) is on, it publishes `window.RWF_PERF` twice a second: fps, ms per system, enemies, nearest-enemy distance, HP.
- **`tools/webtest.py`:** new `--hero` and `--play N` options.
  - It samples `RWF_PERF` for the whole match and prints FPS overall and with an enemy within 4 cells.
  - After a death it follows END_BANNER -> POTG -> SUMMARY.

## 4. Balance

### Method

`python -X utf8 tools/autoplay.py --heroes vector,flicker,rampart --stages 1,2,3 --seeds 1,2,3 [--profile good|average] --json out.json`

**How the bot plays**
- It uses the real game loop through the Harness: `app.run_match` with an input source that emits real KEYDOWN/KEYUP, mouse-button and MOUSEMOTION events.
- No god mode and no debug help. Only `skip_countdown`, `perf`, `skip_end_screens` and `start_wave` are set; the last one picks the stage.
- Each run is one hero x one stage (5 waves) x one seed. The run ends at `stage_clear` or at death, so every stage gets measured even when a hero dies early.

**Bot policy**
- **Targeting:** the nearest visible enemy (LOS), with arming Detonators and close Slicers first.
- **Aim:** mouse turning is capped at 8 rad/s. Aim error is an Ornstein-Uhlenbeck process: 6 deg / 70 px when a new target is acquired, settling to 3 deg / 40 px. Tracking lags 0.13 s, and the first shot waits 0.18 s after acquiring a target. The bot fires only while the crosshair is on or near the body.
- **Movement:** BFS pathing. It holds a range band (VECTOR 4.5-8.5, FLICKER 3-5.5; RAMPART closes in) and strafes inside it. It walks in past an Eradicator's barrier, backs off an armed Detonator or a Warden stomp, and takes cover from the Warden's sentry mode.
- **Objectives and packs:** it stands on the capture point during capture waves, and goes for health packs below 40% (RAMPART 35%).
- **Ult:** used when ready and at least 3 enemies are in view. RAMPART counts enemies in its 8-cell cone. FLICKER counts enemies within 7 cells and throws at the densest cluster.
- **Abilities:**
  - VECTOR: Helix on cooldown, Heal Field below 60%, Sprint while travelling.
  - FLICKER: Blink to escape or travel, Rewind below 35%, quick melee at point-blank range.
  - RAMPART: Barrier toward ranged enemies while closing in, Charge a pinnable target 2.5-7 cells ahead, Flame Strike on target.

**Profiles and what is recorded**
- `good` bot: weapon accuracy 55-61%, crit/hit 17-24%, roughly a silver-to-gold medal player.
- `average` bot: slower turns (5 rad/s) and reactions (0.3 s), a wider error, and a longer lag.
- Charge time is measured from the previous `ult_used` (or the run start) to `ult_ready`. Ult-to-ult is the time between uses and includes the bot waiting for 3 enemies.
- Ult sources are each ult point attributed to its spec 5.9 source at the moment it was gained.
- 108 runs in total: 2 tunings x 2 profiles x 27 runs, about 3.9 hours of simulated play.

### Results (before = spec numbers, after = ULT_COST +10% and enemy damage -15%)

| tuning | bot | hero | charge med s | ult-to-ult med s | ults used / wave (w3+) | ults ready / wave (w3+) | % of w3+ waves with an ult | assault med s | capture med s | boss wave med s | Warden spawn-kill med s | Warden engage-kill med s | deaths / runs | stages cleared | captures | acc % | crit/hit % | frame p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| before | good | VECTOR | 27 | 37 | 0.67 | 0.67 | 61 | 26 | 14 | 47 | 47 | 30 | 6/9 | 3/9 | 9/9 | 57 | 20 | 4.8 |
| before | good | FLICKER | 16 | 23 | 0.76 | 0.82 | 59 | 23 | 13 | 52 | 52 | 35 | 5/9 | 4/9 | 8/8 | 55 | 26 | 4.5 |
| before | good | RAMPART | 16 | 30 | 0.52 | 0.67 | 44 | 14 | 14 | 37 | 37 | 25 | 0/9 | 9/9 | 9/9 | - | - | 4.7 |
| before | average | VECTOR | 32 | 43 | 0.57 | 0.86 | 50 | 29 | 14 | 50 | 50 | 32 | 6/9 | 3/9 | 8/8 | 55 | 16 | 3.6 |
| before | average | FLICKER | 20 | 35 | 0.67 | 0.44 | 44 | 32 | 13 | - | - | - | 9/9 | 0/9 | 6/6 | 50 | 27 | 3.7 |
| before | average | RAMPART | 17 | 30 | 0.52 | 0.72 | 44 | 16 | 13 | 40 | 40 | 29 | 1/9 | 8/9 | 9/9 | - | - | 3.7 |
| **after** | good | VECTOR | 31 | 36 | 0.78 | 1.00 | 65 | 25 | 14 | 53 | 53 | 38 | 2/9 | 7/9 | 9/9 | 61 | 20 | 4.9 |
| **after** | good | FLICKER | 13 | 19 | 1.00 | 1.10 | 70 | 23 | 14 | 56 | 56 | 39 | 4/9 | 5/9 | 8/8 | 55 | 24 | 5.1 |
| **after** | good | RAMPART | 18 | 31 | 0.67 | 0.85 | 52 | 14 | 14 | 39 | 39 | 26 | 0/9 | 9/9 | 9/9 | - | - | 5.5 |
| **after** | average | VECTOR | 33 | 43 | 0.86 | 0.86 | 67 | 35 | 14 | 68 | 68 | 44 | 3/9 | 6/9 | 9/9 | 53 | 17 | 4.6 |
| **after** | average | FLICKER | 26 | 30 | 0.60 | 0.93 | 47 | 36 | 14 | 62 | 62 | 43 | 6/9 | 3/9 | 7/7 | 51 | 26 | 4.9 |
| **after** | average | RAMPART | 18 | 28 | 0.67 | 0.74 | 56 | 16 | 13 | 41 | 41 | 28 | 0/9 | 9/9 | 9/9 | - | - | 5.4 |

**Notes on the columns**
- Boss-wave length equals the Warden's spawn-to-kill time, because the wave clears when the boss dies (its escort usually dies first).
- A dash means no stage-1 boss was reached (every run died first).
- `frame p95` is the median of the per-run desktop p95 frame times. It includes render and HUD, with 6 bot processes sharing 8 cores; the per-run maximum was 5.9 ms.

**Where the ult charge came from, after tuning (both profiles pooled, in %)**

| Hero | damage | ult damage | ability heal | barrier | passive | capture |
|---|---|---|---|---|---|---|
| VECTOR | 63 | 0 | 10 | 14 | 8 | 5 |
| FLICKER | 57 | 18 | 0 | 12 | 8 | 5 |
| RAMPART | 76 | 8 | 0 | 6 | 5 | 6 |

**Deaths after tuning (stage/seed, wave, seconds into the wave, what hit last)**
- VECTOR, good bot:
  - s2/1 w9 +20 s, bolt
  - s3/1 w14 +21 s, melee
- VECTOR, average bot:
  - s2/1 w9 +44 s, melee
  - s3/1 w14 +22 s, lunge
  - s3/3 w14 +22 s, bolt
- FLICKER, good bot:
  - s1/3 w5 +27 s, sentry
  - s2/1 w9 +21 s, melee
  - s3/1 w11 +15 s, bolt
  - s3/2 w15 +41 s, recon
- FLICKER, average bot:
  - s1/2 w5 +47 s, sentry
  - s2/1 w9 +24 s, melee
  - s2/2 w6 +21 s, bolt
  - s3/1 w14 +18 s, melee
  - s3/2 w15 +62 s, stomp
  - s3/3 w11 +20 s, melee
- RAMPART: none in 18 runs.

### Against the 9.6 targets

| Target | After tuning | Verdict |
|---|---|---|
| Median time between ults: FLICKER ~40 s, RAMPART ~55 s, VECTOR ~60 s | Charge time: FLICKER 13-26 s, RAMPART 18 s, VECTOR 31-33 s. Ult to ult (bot waits for 3 in view): 19-30 / 28-31 / 36-43 s | **Far too fast (x1.5 to x3), even with the +10% cap.** |
| At least 1 ult per wave from wave 3 | Ults ready per wave: VECTOR 0.86-1.00, FLICKER 0.93-1.10, RAMPART 0.74-0.85. Share of waves with an ult used: 47-70% | Roughly met for charge, borderline for use. Capture waves only last ~14 s, and RAMPART's "3 in the cone" is rare. |
| Wave length 30-60 s | Assault: good bot 23-25 s (VECTOR/FLICKER), average bot 35-36 s, RAMPART 14-16 s. Capture ~14 s. Boss 39-68 s | **Short** for strong play and for RAMPART. Capture waves are structurally ~13 s. |
| WARDEN fight 25-40 s | From the first damage on the Warden: 26-28 s (RAMPART), 38-44 s (VECTOR), 39-43 s (FLICKER). From its spawn: 39-68 s, which includes the walk from the far corner and the escort | Met measured from engagement; long measured from spawn for the DPS heroes. |

### What was tuned, and why nothing else was

**Tuned**
- **`ULT_COST` +10% on all three heroes** (VECTOR 1500 -> 1650, FLICKER 1100 -> 1210, RAMPART 1400 -> 1540). Every hero charges 1.5-3x faster than its target, so the largest allowed step in that direction was taken.
- **Enemy damage to the player -15%** (the largest allowed step). Before, the good bot died in 6/9 VECTOR runs and 5/9 FLICKER runs, and the average bot in 6/9 and 9/9. VECTOR is the difficulty-1 hero and could clear stage 3 in 0 of 6 attempts. After, the good bot dies in 2/9 (VECTOR) and 4/9 (FLICKER) runs, and stage clears rose from 3/9 to 7/9 (VECTOR) and from 4/9 to 5/9 (FLICKER). RAMPART was already safe (1 death in 18 runs) and is now at 0/18.

**Too far off target to fix with the allowed levers (reported, not retuned)**
1. **Ult pace follows kill speed.** About 60-75% of ult charge comes from damage dealt, and assault waves end in 14-36 s instead of 30-60 s.
   - The two 9.6 targets only agree if waves last about 60 s: "at least 1 ult per wave" asks for a charge time of 30 s or less with the waves as they are now, while the charge-time targets ask for 40-60 s.
   - Options, which are spec changes:
     - a. Make waves longer or tougher (enemy pools or counts): this moves both targets together.
     - b. Or raise ULT_COST about x1.7 (VECTOR ~2600, FLICKER ~2000, RAMPART ~2800) and accept fewer than 1 ult per wave.
   - Option a is recommended.
2. **Ult damage refills the next ult.** FLICKER's Pulse Bomb (18% of its charge) and RAMPART's Quake (8%) count toward their next ult, because the 5.9 lock only covers `ult_active_left > 0` and those ults have a duration of 0. Overwatch gives no charge for ult damage. Recommendation: skip `add_ult` when `ability == 'ult'` in `combat.apply_damage`, which would slow FLICKER by about 20%.
3. **Hero survivability is lopsided.** Even after the -15% damage change:
   - FLICKER (150 HP) still dies in 10 of 18 stage runs, several within 15-25 s of a stage-2/3 wave 1 or 4.
   - RAMPART (500 pool + 600-HP barrier + one-shot hammer on 75-HP troopers) died in 1 of 36 runs over both tunings, and clears assault waves in about 14 s.
   - Hero-specific numbers are outside the integrator's levers. The candidates are FLICKER health 150 -> 175, or RAMPART hammer 80 -> 70 (troopers would take 2 swings).
4. **Capture waves last about 13-15 s.** The 12 s capture finishes before the trickle can contest, because enemies chase the player rather than the point (a known ENEMIES gap). The wave then ends because every remaining enemy self-destructs.
5. The bot is not a human, so treat these numbers as relative:
   - Its aim is at medal level (55-61% accuracy).
   - It knows where every enemy is, which is also on the minimap.
   - Its movement is simple: it rarely uses cover apart from the Warden's sentry mode.
   - The manual 5-minute desktop playtest per hero (9.6 item 4) was not possible in this headless session.

## 5. Suites, web build and performance

### Suites (desktop: Python 3.14, pygame-ce 2.5.8), final tree

| Command | Result |
|---|---|
| `--suite all` | OK: 111 passed, 0 failed. The apk matches all 20 game files. |
| `--suite all --no-assets` | OK: 111 passed, 0 failed |
| `--suite all --shots` | OK: 111 passed |
| `--suite perf` | check_perf: total p50 2.20 / p95 3.40 ms (update 0.26, render 2.64, hud 0.49 at p95), 0 big surfaces, 10/10 visible. check_perf_close: p50 1.65 / p95 2.34 ms. |
| HUD budget (check_hud_perf) | p50 0.52 / p95 0.88 ms (limit 1.5) |

### Web

**Build**
- `python -m pygbag --build game` packs 21 files.
- `game/build/web/game.apk` holds `assets/main.py`, `assets/favicon.png` and all 20 `assets/rwf/*.py`.

**Browser test** (`tools/webtest.py --hero <key> --play 40`)
- Setup: headless Edge, pygbag 0.9.3, CPython 3.12 wasm, pygame-ce 2.5.7.
- Every hero ran TITLE -> HERO_SELECT -> COUNTDOWN -> PLAYING -> death. RAMPART went on through END_BANNER -> POTG -> SUMMARY.
- There were **0 tracebacks** in the console.
- `RWF_PERF` samples during PLAYING ("close" = nearest enemy within 4 cells; the enemies reached 0.5 cells):

| Hero | Samples (close) | FPS p50 / p10 / min | Work ms per frame p50 / p90 | Max enemies alive |
|---|---|---|---|---|
| VECTOR | 23 (15) | 59.9 / 59.9 / 55.2 | 7.6 / 9.0 (close 7.5 / 9.0) | 6 |
| FLICKER | 24 (17) | 59.9 / 59.9 / 59.5 | 6.8 / 8.3 (close 6.7 / 7.6) | 6 |
| RAMPART | 80 (72) | 60.2 / 59.9 / 59.5 | 9.8 / 14.5 (close 10.6 / 14.5) | 6 |

- The browser is capped at 60 fps by the display. At 7-15 ms of work per frame there is 2-4x headroom to the 30-fps target.
- The passive test player dies in wave 1, so the browser never saw more than 6 enemies. For heavier scenes, the desktop perf scenario (10 enemies, 30 bolts, 2 barriers, p95 3.4 ms) scaled by the observed browser/desktop ratio (about 3-4x) gives about 12-14 ms, still above 60 fps.
- No section 8 lever was needed; COLS stays 320.
- Screenshots: `tools/out/web_<hero>_*.png`.

## 6. Known issues, most severe first

1. **Balance, ult pace (high):** see 4.1. The charge-time targets can't be met with ULT_COST +-10%; it needs a spec decision (longer waves recommended).
2. **Balance, hero parity (high):** see 4.3. FLICKER is fragile and RAMPART dominant. This needs hero-number changes outside the allowed levers.
3. **Ult damage feeds the next ult (medium):** see 4.2. FLICKER and RAMPART. Overwatch does not work this way.
4. **Capture waves (medium):** about 14 s long and almost never contested (enemies don't path to the point).
5. **No human playtest (medium):** the numbers come from a bot, and the browser test only covered wave-1 scenes.
6. **Small gameplay gaps (low):**
   - Ability recharges still count the frame they start in, so a cooldown ends 1 frame (33 ms) early. The reload was fixed, but builders' checks pin the ability timing.
   - VECTOR's Lock-On caches LOS for 0.1 s.
   - Heal Field emits 30 `heal` events a second.
   - RAMPART can quick-melee with the barrier up.
   - RAMPART's barrier overlay doesn't follow pitch.
7. **Presentation (low, deferred to the UI pass):**
   - Code-drawn placeholders for the viewmodels, icons, pylon and enemies.
   - FLICKER's guns overlap the lower HUD.

## 7. Commits on `overwatch`

- bc08d77: CORE REQUESTs
- 5006ced: autoplay bot, balance pass, web perf hook
- the final commit: webtest sampling, spec notes, this report

Nothing was pushed or deployed. The build output stays in the ignored `game/build/`.
