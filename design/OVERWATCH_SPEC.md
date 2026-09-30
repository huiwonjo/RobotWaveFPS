# OVERWATCH_SPEC: the Overwatch-style upgrade (build spec v1)

This is the single source of truth for this build: 1 FOUNDATION agent, then 5 parallel builders (HERO_A, HERO_B, HERO_C, ENEMIES, HUD_UX), then 1 integrator.

- Every number in this file is final for v1.
- Each builder copies its numbers into a `TUNING` block at the top of the files it owns.
- The integrator may retune them after playtesting.

Conventions:
- Distances are in map cells. Displayed metres = cells x 2.
- Times are in seconds of simulation time. Angles are in degrees unless marked rad.
- Screen coordinates are for the 1024x768 window.

---

## 0. Read this first

### 0.1 Baseline, and a concurrent change you must know about

This spec was synthesised from three proposals written against the 883-line "Robot Wave FPS" `game/main.py`. While the spec was being written, another session reskinned the working tree into **"DOKKAEBI: NIGHTFALL"**, a Seoul night-watch theme.

**Reskin changes found in the working tree:**
- `game/main.py`: 971 lines, uncommitted.
- `game/assets/`: `dokkaebi-normal/elite/boss.png`, `seoul-night.png` and `NotoSansKR.ttf`. About 20 MB in total.
- `tools/build_web.py`: a custom packer. It packs only `main.py`, `favicon.png` and `assets/*`.
- `index.html` and `loader.js`: a Korean boot screen, with a web bundle of about 15.7 MB.

**Consequences for this build:**

1. **Snapshot the start point.** FOUNDATION ports from whatever `game/main.py` exists when it starts. Record the git blob hash in the FOUNDATION report.
   - If the file changes again during Phase 1, only presentation changes are merged, by the integrator, into `theme.py` and `render.py`.
   - Gameplay code in the old `main.py` is superseded by this spec.
2. **Presentation is data.** `rwf/theme.py` picks the `seoul` theme when `game/assets/dokkaebi-normal.png` exists, and the `omnic` theme otherwise. Gameplay code only ever uses internal kind keys: `trooper`, `slicer`, `detonator`, `eradicator`, `warden`. Nothing in gameplay depends on the theme.
3. **Assets are optional.** Every PNG and the font must be optional.
   - Each enemy painter has a code-drawn fallback.
   - The smoke suite runs once with `RWF_NO_ASSETS=1`.
4. **The packer must learn the package.** `tools/build_web.py` must also pack `game/rwf/*.py` (FOUNDATION owns this change). Otherwise the web build ships without the game code.
5. **On-screen text stays ASCII/English**, which is a hard constraint.
   - `core.font()` uses `NotoSansKR.ttf` when it is present, so the reskin's typography survives. Latin glyphs render fine with it.
   - The reskin's Korean `tr()` labels are replaced by the new English screens.
   - A Korean string table is OUT for v1; see 1.2.

### 0.2 Decision log (conflicts between proposals, and what was chosen)

| # | Topic | Chosen | Why (one line) |
|---|---|---|---|
| 1 | Hero and enemy names | Original names (VECTOR / FLICKER / RAMPART, WARDEN); the kits stay Overwatch-faithful | The build is public on GitHub Pages. The kits carry the Overwatch identity; the names don't have to. |
| 2 | Code layout | Package `game/rwf/` with registries (tech lens) | A unique package name can't shadow the stdlib or pygbag's `platform` module, and it allows one owner per file. |
| 3 | Armor rule | Flat 30% reduction per hit (OW2) instead of OW1's "-5 or halve" | 2 of 3 lenses chose it. It is linear, so the tables scale predictably from 12-damage bullets to 350-damage bombs. |
| 4 | Roster | Trooper, Slicer, Detonator, Eradicator, plus the Warden boss (Bastion-style recon/sentry modes) | The boss's sentry mode already delivers the turret fantasy. A separate Sentry unit would need a nest system and adds little new play. |
| 5 | Alive cap | 10, plus 2 boss summons (tech/game-feel) instead of 12 | Browser frame budget: each visible enemy is a scaled sprite blit. |
| 6 | Rampart barrier | 600 HP, regenerates 150/s (game-feel) instead of 1200 | Enemy DPS here is about 1/5 of PvP, so a 1200-HP barrier would never break. |
| 7 | Enemy HP and damage | Game-feel TTK targets (Trooper 75 HP = 4 VECTOR body shots) instead of fidelity's 150 | The game-feel lens owns tuning. |
| 8 | Stage scaling | +15% pools and damage per stage; +5% speed per stage, capped at x1.3 | Today's +15% speed per stage makes melee packs unfair by stage 3. |
| 9 | Sprint | Latch (press once) instead of hold | Holding Shift for a long time triggers Windows FilterKeys. Space mirrors Shift to avoid the Sticky Keys prompt. |
| 10 | Pause | Esc and P, plus auto-pause on focus loss or pointer-lock loss | Browsers swallow Esc while the pointer is locked. |
| 11 | Input source | KEYDOWN/KEYUP events OR'd with `key.get_pressed()` | Events make the harness deterministic; `get_pressed` survives a Korean IME left in Hangul mode. |
| 12 | FLICKER right mouse | Blink (the Overwatch default); V is quick melee for every hero | Identity (fidelity and game-feel lenses) over the tech lens's quick-melee proposal. |
| 13 | Rewind travel time | 0.5 s (game-feel) instead of 1.0 s | Less dead time. The 12 s cooldown is still the limit. |
| 14 | Ult charge | 1 point per damage actually dealt (no overkill). 1 per HP healed by abilities. 0.5 per HP absorbed by your barrier or dealt to enemy barriers. +5/s while in combat. No bonus per elimination. | Tech lens's rule plus fidelity's sources. With no kill bonus, hammer cleave doesn't snowball. |
| 15 | Health packs | Small (75 HP, 10 s respawn) and large (250 HP, 15 s respawn), picked up only when hurt | Overwatch rule (fidelity). Hero pools are larger now. |
| 16 | Floating damage numbers | None | Overwatch has none (fidelity), and it saves HUD budget. |
| 17 | Ult feedback | 0.3 s of slow-mo at 35% speed, a callout and screen shake | Game-feel lens. It costs one multiply. |
| 18 | End of run | Endless, as today. Clearing stage 3 shows a VICTORY banner and awards a medal. The summary header reads VICTORY or DEFEAT. | Keeps what works and adds a goal. |
| 19 | Hero swap | Only in the 8 s stage intermission; keep min(ult%, 30%) | Both lenses agree. Swapping mid-wave would trivialise the kits. |
| 20 | Enemy ranged attacks | Projectiles only, no enemy hitscan | Every attack can be dodged or blocked, which is what gives Barrier, Rewind and Blink their value. |
| 21 | Quake Slam | 120 damage + 2.5 s stun, stopped by enemy barriers | Kills stage-1 fodder but not armored units. The barrier rule keeps the Overwatch identity. |
| 22 | Theme | `theme.py` switch: `seoul` when its assets exist, `omnic` otherwise | Don't destroy the concurrent reskin, and don't make gameplay depend on it. |
| 23 | Language | ASCII only in v1 | Hard constraint. The ASCII static check stays simple. |
| 24 | Play of the Game | Record the render `Scene` objects at 20 Hz (tech) and score highlights the game-feel way | Replay costs one normal frame and needs no re-simulation. |
| 25 | Minimap | Top-left, walls drawn once | Today it overlaps the ammo counter (all lenses). |
| 26 | Crits | x2 for hitscan only, with per-type head (or core) bands | All lenses agree. Projectiles, splash and melee never crit. |

---

## 1. Scope

### 1.1 IN (must ship)

**Foundation (M0)**
- Split into the `game/rwf/` package.
- Sim clock with pause/auto-pause and slow-mo; `InputState`; `EventBus`.
- Damage pipeline with health/armor/shield pools; statuses; knockback.
- Hitscan with a real vertical test and head bands; projectiles; barriers.
- Flow-field pathing.
- Sprite painter cache with z-buffered span blits; floor rings; orbs; barrier segments.
- Cached minimap and overlays; the texture-wall performance fix.
- Health packs; theme table; debug hooks.
- Headless smoke harness; packer update.

**Heroes**
- VECTOR, FLICKER and RAMPART, each with a full kit: primary, secondary, Shift, E, Q.
- Ult charge.
- Hero select, and hero swap in the stage intermission.
- Quick melee (V) for every hero.

**Enemies**
- Trooper, Slicer, Detonator, Eradicator and the Warden boss (2 phases, sentry mode, stomp).
- Elite modifier; stage scaling.
- Trickle spawning under the alive cap.
- Wave table with a capture objective on wave 3 of every stage.

**HUD**
- Segmented health bar by pool type; hero portrait.
- Ability tiles with cooldown sweeps, numbers and charge pips; ult ring with ready pulse; ammo and reload.
- Hero crosshairs; hitmarkers (body, crit, kill); ELIMINATED pop-ups; kill feed.
- Damage-direction arcs; low-HP vignette; enemy health bars after damage; boss bar.
- Objective widget and through-wall marker; wave banners; minimap; score.
- Debug overlay (key 0).

**Screens**
- Title, hero select, countdown, pause, stage intermission (with swap).
- End banner; Play of the Game replay (static-card fallback); match summary with medals and the S-D rank.

**Audio**
- Synthesised SFX set. Lazy init after the first input; silent on any failure; M mutes.

### 1.2 OUT (explicitly cut)

- **Modes:** payload/escort waves; PvP, networking, bots; skins, loot, per-hero challenges, localStorage best scores.
- **Content:**
  - the Sentry enemy type;
  - a 4th hero and all supports (Ana, Mercy, Lucio);
  - overhealth pools and burn or other damage-over-time.
- **Movement and view:** vertical movement (jump, fly, crouch, wall-ride); scoped zoom or any FOV change.
- **HUD and screens:** floating damage numbers; a Tab scoreboard or hold-X stats panel (stats are on the pause screen instead).
- **Assets:** music, voice lines, any new asset file (existing optional assets may be used).
- **Rendering:** floor/ceiling textures, per-pixel fog, dynamic resolution. COLS stays 320; dropping it to 240 is an emergency lever for the integrator only.
- **Language and hero changes:**
  - a Korean string table / localisation (follow-up: `rwf/strings_ko.py` plus a `core.tr()` lookup);
  - real Overwatch names, logos or text;
  - hero swap mid-wave or on the pause screen.

### 1.3 Cut order if time runs out (integrator decides)

1. POTG replay: fall back to the static best-moment card.
2. Medals: keep the plain stats.
3. Warden stomp.
4. Rampart Charge pin/carry: becomes a dash that deals 225 to the first enemy it hits.
5. Capture objective: wave 3 becomes an assault wave.
6. Detonator chain credit.
7. SFX.

**Never cut:**
- the sim clock and pause;
- the damage pipeline and pools;
- the hitscan vertical fix;
- 3 heroes with ults;
- the 4 regular enemies and the boss;
- the HUD core (health segments, ability tiles, ult ring, hitmarkers, kill feed, ELIMINATED pop-ups);
- the performance rules in section 8.

---

## 2. Controls

| Action | Primary | Browser-safe fallback / note |
|---|---|---|
| Move | W A S D | Arrow keys |
| Look | Mouse (yaw 0.0014 rad/px, pitch 0.55 px/px, pitch clamp +-220 px) | Needs pointer lock; see "Pointer lock" below |
| Primary fire | LMB (hold) | none needed (left click never opens a menu) |
| Secondary fire | RMB | **F**. Every RMB action works on F. Barrier: hold F. |
| Ability 1 | Left Shift | **Space**; Right Shift also works. Never require a long Shift hold (see Sprint). |
| Ability 2 | E | |
| Ultimate | Q | |
| Reload | R | Also automatic when the mag is empty and fire is held |
| Quick melee | V | |
| Pause | Esc | **P**. The game also auto-pauses on focus loss or pointer-lock loss. |
| Resume | Left click | The click is the user gesture the browser needs to re-lock the pointer. That click never fires. |
| Mute | M | |
| Mouse sensitivity | `[` / `]` | Steps of 10%, range 0.4x to 2.5x. Toast "SENS 1.2x" for 1 s. |
| Debug overlay | 0 | FPS, ms per system, entity counts, ult-ready log |
| Hero pick | 1 / 2 / 3, or Left/Right arrows | Click a card |
| Lock in / confirm | Enter or Space | Click the LOCK IN button, or click the highlighted card again |
| Skip intermission / POTG | Enter or Space | Click |
| Summary screen | Enter or click: PLAY AGAIN (same hero); H: HERO SELECT | |
| End match | X (only on the pause screen) | Goes to the end banner, POTG and summary |

**Never bound:**
- Ctrl (Ctrl+W closes the tab).
- Alt and Cmd/Meta.
- Tab (it moves browser focus).
- F1-F12.
- Any modifier combination.

The static check enforces this (section 9.5).

### 2.1 Input implementation (FOUNDATION)

- **Actions, not keys.** `InputState` maps pygame keys and mouse buttons to action strings using `config.KEYMAP` and `MOUSEMAP`.
- **Two sources, OR'd.** It tracks held, pressed and released sets from events. Each frame it also ORs in `pygame.key.get_pressed()` for every keyboard-mapped action, generating edges from its own previous snapshot. Mouse buttons come from events only; never use `pygame.mouse.get_pressed()`.
- **IME.** Call `pygame.key.stop_text_input()` once after `set_mode`, inside try/except.
- **Focus loss.** `InputState.clear()` runs on `WINDOWFOCUSLOST`, on `ACTIVEEVENT` with gain 0, and on pause, so no key stays stuck.

### 2.2 Pointer lock (FOUNDATION)

- **Lock and unlock.** `core.lock_mouse(on)` is `pygame.event.set_grab(on)` plus `pygame.mouse.set_visible(not on)`. pygame's virtual input mode becomes pointer lock in the browser. This is what the shipped build already does.
- **Where the mouse is locked.** COUNTDOWN, PLAYING and INTERMISSION. Everywhere else it is unlocked.
- **Browser check.** On `sys.platform == "emscripten"`, app polls `platform.window.document.pointerLockElement` every 0.25 s of real time while PLAYING, inside try/except. If it reads falsy, the game pauses.
  - The first exception disables polling for the session.
  - If the value is still falsy 1.0 s after a resume click, disable polling too, in case pygbag doesn't use real pointer lock. Pause then falls back to Esc/P and focus events.

---

## 3. Heroes

### 3.0 Rules shared by all heroes

- **Pools.** Heroes have `HEALTH`, `ARMOR` and `SHIELDS`; no hero in v1 has shields.
  - Healing fills health first, then armor.
  - Stage clear restores all pools to full, resets ability cooldowns and charges, and refills ammo. Ult charge is kept.
- **Body.** Collision radius is 0.25 with axis-separated wall sliding (`world.move_slide`). Eye height is `EYE_Z` = 0.5.
- **Quick melee (V).**
  - 40 damage, reach 1.5 (centre distance minus enemy radius), cone +-30 deg, needs line of sight.
  - Cooldown 0.8 s. No crit. Knockback 0.3 on non-boss targets.
  - Emits `ability_used` with slot `melee`.
- **Reload.** Primary fire does nothing while reloading. When the mag hits 0 and fire is held, reload starts on its own. Pressing R with a full mag is a no-op.
- **Ultimate.**
  - Q uses it when `ult_charge >= ULT_COST`, or always with `debug['inf_ult']`. Charge drops to 0.
  - `ult_used` is emitted. App applies slow-mo (0.35x for 0.3 s real time) and a 6 px shake for 0.2 s. The HUD shows the hero's `ULT_CALLOUT` for 1.2 s.
  - No ult charge is gained while `ult_active_left > 0`.
- **Primary events.** Every primary shot or swing emits `ability_used` with slot `primary`. Every hitscan trace also emits `shot`.
- **Knockback immunity.** Heroes are knockback-immune only while RAMPART is charging.
- **Viewmodel.** Drawn by the hero, between y 480 and 768. The HUD is drawn on top of it. Keep the central 200x200 box around the crosshair clear, except for muzzle flashes and tracers.
- **Muzzle flashes.** Pre-rendered once, in 3 sizes, at first use. Never allocate them per frame.
- **Icons.** Each hero class draws its portrait and its ability icons with code (`draw_icon`, a classmethod). The HUD caches the results.

### 3.1 VECTOR (HERO_A): Soldier-style all-rounder

- **Role and difficulty:** DAMAGE, difficulty 1.
- **Colour:** (80, 150, 255).
- **Pools:** 200 health.
- **Move speed:** 4.2 cells/s.
- **Ult cost:** 1500.
- **Blurb:** "Versatile rifleman. Rockets, sprint, self-heal."

| Slot | Keys | Ability | Numbers | Behaviour | Drawn as |
|---|---|---|---|---|---|
| Primary | LMB hold | PULSE RIFLE | Hitscan. 19 damage, crit x2 = 38. 9 shots/s (0.111 s). Mag 30, reload 1.5 s. No falloff. | Full auto. The first 3 shots of a burst are exact. After that, spread grows +0.3 deg per shot up to 1.5 deg (0.026 rad), as random yaw +-spread and pitch jitter +-(spread x 768) px. The burst resets 0.3 s after the last shot. | Rifle bottom-right, body 300x110 px. 10 px recoil kick that recovers over 0.08 s. Cached muzzle flash for 50 ms. Pale-blue tracer line (muzzle to crosshair, 2 px) for 40 ms. Crosshair: 2 px dot plus a 1 px circle of radius 10 + spread_rad x 400. |
| Secondary | RMB / F | HELIX ROCKETS | 40 direct + splash 80 at the centre falling linearly to 40 at r 1.5. Projectile speed 16, radius 0.2. Cooldown 6.0 s. No ammo cost. | Explodes on an enemy, a wall or an enemy barrier (the barrier takes direct + splash). Splash needs LOS from the blast point. No self-damage. Knockback 0.4 on non-boss enemies in the splash. | 3 small orange orbs in a triangle (radius 0.06 each). Explosion: 14 orange particles, a floor ring flash of r 1.5 for 0.25 s, 4 px shake for 0.15 s. Launcher flash on the viewmodel. |
| Shift | LShift / Space | SPRINT | x1.5 speed (6.3 cells/s). No cooldown. | Latch: press to start. It continues while W is held and ends on W release, fire, RMB/F, E, Q, V, or pressing Shift/Space again. Starting a sprint cancels an in-progress reload. | Viewmodel lowered 60 px with 2x bob speed. The SHIFT tile shows as active. |
| E | E | HEAL FIELD | 40 HP/s for 5.0 s, radius 2.5. Cooldown 15 s, starting on deploy. | Dropped at your feet. Heals the player while inside. Healed HP gives ult charge 1:1. Emits `heal` with ability `ab2`. | World sprite `heal_pylon` (height 0.35, width 0.2; HERO_A registers the painter). Pulsing yellow-green floor ring of r 2.5. While inside: green edge glow (cached strips, `BLEND_RGB_ADD`). |
| Q | Q | LOCK-ON (ult) | Lasts 6.0 s. Refills the clip on activation. Uses no ammo while active. 19 damage per shot, never crits. Still 9 shots/s. | Each shot hits the enemy nearest the crosshair among those with `ScreenBox.visible` and LOS (angle within HALF_FOV = 30 deg). If none is valid, the shot is a normal manual one. Kills during the ult count as ult kills. | Red crosshair. Red corner brackets (4 L-shapes, 2 px) on every valid target, 3 px on the current target. The ult ring drains. Callout "LOCKED ON!". |

### 3.2 FLICKER (HERO_B): Tracer-style flanker

- **Role and difficulty:** DAMAGE, difficulty 3.
- **Colour:** (255, 150, 40).
- **Pools:** 150 health.
- **Move speed:** 4.6 cells/s.
- **Ult cost:** 1100.
- **Blurb:** "Blink through fights, rewind mistakes."

| Slot | Keys | Ability | Numbers | Behaviour | Drawn as |
|---|---|---|---|---|---|
| Primary | LMB hold | TWIN PISTOLS | Hitscan. 12 damage, crit x2 = 24. 20 shots/s (0.05 s), guns alternating. Mag 40, reload 1.0 s. Falloff: full damage up to 5 cells, then linear to 50% at 10 cells, and 50% beyond. | Spread is random yaw +-0.8 deg (0.014 rad) and pitch jitter +-11 px. Fire with an accumulator so frame rates below 20 fps still give 20 shots/s (several traces per frame). | Port the existing twin-pistol viewmodel (`draw_gun`), with each gun kicking 30 px on its own shot. Cached muzzle flash. Crosshair: 4 lines, gap 8 (+6 px while firing), length 7. |
| Secondary | RMB / F | BLINK | Shares the Shift ability and its charges | The same action as Shift, as in Overwatch. There is no separate `secondary` ability entry, so the HUD shows 2 tiles. | See Shift. |
| Shift | LShift / Space | BLINK | 3 charges, 1 charge per 3.0 s, recharged one after another. Distance 3.5. | Direction comes from the WASD input relative to the view; with no input it is forward. Instant. The path is stepped 0.1 at a time with `world.dash_target` and stops 0.3 short of any wall. Passes through enemies. Not usable during Rewind. | For 0.12 s: 16 radial light-blue speed lines from the screen edge toward the centre, plus a `BLEND_RGB_ADD` (0, 30, 60) fill. 3 pips above the SHIFT tile. SFX `blink`. |
| E | E | REWIND | Cooldown 12 s. Ring buffer of 30 samples at 10 Hz: (x, y, angle, health). | Travels back through the samples, newest to oldest, over 0.5 s, with position interpolated along the path. `invuln` status for 0.5 s; can't act. At the end: health = max(current, oldest sample), ammo = 40, reload cancelled. Cooldowns and ult are untouched. The buffer is cleared afterwards. With fewer than 30 samples, use the oldest one available. | Blue `BLEND_RGB_ADD` (0, 25, 60) tint, plus a cached additive scanline surface (a 1 px line every 6 px). Viewmodel hidden. SFX `blink`, played pitched down (use the separate `rewind` sound if you have time). |
| Q | Q | PULSE BOMB (ult) | Thrown at 12 cells/s, radius 0.25, max range 6. Fuse 1.0 s, starting when it sticks or lands. Explosion radius 2.5: the stuck target takes 350; everything else takes 350 at the centre falling linearly to 105 at the edge. | Sticks to the first enemy within 0.25 + its radius. Otherwise it sticks to a wall on contact, or drops at max range. Once stuck it follows the target; if the target dies it stays where it was. Needs LOS from the bomb (walls block); ignores barriers. No self-damage. | Blue orb with a white core, drawn at the target's mid-height when stuck. Floor ring of r 2.5 blinking at 8 Hz. SFX `beep` every 0.2 s. Explosion: 24 blue and white particles, a ring flash and an 8 px shake for 0.3 s. Callout "BOMB AWAY!". |

### 3.3 RAMPART (HERO_C): Reinhardt-style tank

- **Role and difficulty:** TANK, difficulty 2.
- **Colour:** (230, 180, 60).
- **Pools:** 300 health + 200 armor.
- **Move speed:** 3.9 cells/s.
- **Ult cost:** 1400.
- **Ammo:** none. `MAX_AMMO = 0`, and the HUD shows the text "MELEE" instead of an ammo count.
- **Blurb:** "Hold the line. Hammer, shield, charge."

| Slot | Keys | Ability | Numbers | Behaviour | Drawn as |
|---|---|---|---|---|---|
| Primary | LMB hold | ROCKET HAMMER | 80 damage to every enemy in the arc. Reach 2.5 (centre distance minus enemy radius). Arc +-45 deg. One swing per 0.9 s. No crit. Knockback 0.6 on non-boss enemies. | Resolves instantly when the swing starts. Needs LOS per target (`cast_ray` distance >= target distance). Also hits enemy barriers whose midpoint is in the arc, for 80 each. Enemy barriers don't block the hammer. Can't swing while the barrier is raised or while charging. | Hammer head 150x90 px on a handle at the right. The swing is a 0.3 s sweep from right to left: the polygon rotates about the grip, with a 3-line motion streak. On hit: 6 sparks per target and a 3 px shake. Crosshair: a dot plus a 60 px-radius arc below the centre. |
| Secondary | RMB hold / F hold | BARRIER | 600 HP. A world segment 1.0 in front of you, half-width 1.2, turning with your view. Move speed x0.7 while held. Regenerates 150 HP/s once it has been lowered for 2.0 s. When broken it is forced down, with a 5.0 s lockout, and then regenerates from 0. You can raise it whenever hp >= 1. | A `Barrier` in `world.barriers` while raised, removed when lowered, keeping its hp. It blocks enemy projectiles physically. Enemy melee and explosions are redirected to it when the source-to-player segment crosses it (`combat.enemy_hits_player`). Absorbed damage gives ult at 0.5 per HP (handled in core). No swings while raised. | A cached hex-grid RGB surface of 880x480 blitted centred with `BLEND_RGB_ADD`, plus a faint (0, 15, 35) additive fill. A 200x6 HP bar at y = 300. The hex lines brighten for 0.08 s when hit, and the tint shifts to orange below 30%. The tile shows the barrier HP as a meter. |
| Shift | LShift / Space | CHARGE | Cooldown 7.0 s, starting when the charge ends. Speed 9 for up to 1.5 s. Steering limited to 90 deg/s. Pin impact 225. A brushed enemy takes 50 plus knockback 1.5. Hitting the boss deals 100 to it and ends the charge. | Moves forward automatically and ignores WASD. Press Shift/Space again after 0.2 s to cancel. The first pinnable enemy within its radius + 0.45 ahead is pinned (status `pinned`) and carried 0.7 in front. When the next step would put the pinned enemy (or, with nothing pinned, Rampart) within its radius of a wall, the pinned enemy takes 225 and the charge ends. Other enemies within 0.8 of the path take 50 and knockback 1.5 sideways, once each per charge. Rampart is knockback-immune while charging. Passes through enemy barriers. No barrier and no swings while charging. | 16 speed lines, a continuous 2 px shake, and the hammer tucked low. On impact: a 10 px shake for 0.3 s and 12 particles. SFX `hammer` (low). |
| E | E | FLAME STRIKE | 90 damage. 2 charges, 6.0 s recharge each. Projectile speed 14, radius 0.35, range 12. | Pierces every enemy, each hit once. Passes through enemy barriers. Stops at walls. | A big orange orb (radius 0.18) plus 2 trailing orbs, and ember particles (at most 4 per frame). A hammer flick on the viewmodel. 2 pips over the E tile. |
| Q | Q | QUAKE SLAM (ult) | Cone +-30 deg, length 8. The wave front travels at 20 cells/s. Each enemy reached takes 120 damage and a 2.5 s stun (x `STUN_MULT`, so 1.0 s for the boss). Rampart is rooted for 0.6 s. | An enemy is hit when the front's distance passes its own, if it has LOS from the origin and the origin-to-enemy segment doesn't cross an enemy barrier. Blocked enemies aren't hit, and the barrier takes no damage. Kills count as ult kills. | A 12 px shake for 0.4 s. Brown rock orbs (at most 24) spawn along the cone at z = 0.05 as the front advances, and fade over 0.6 s. Stunned enemies are drawn at 60% height with 3 yellow stars (renderer `FLAG_STUN`). Callout "QUAKE!". |

### 3.4 Class attributes the select screen and HUD read

| Attr | VECTOR | FLICKER | RAMPART |
|---|---|---|---|
| `KEY` | `vector` | `flicker` | `rampart` |
| `NAME` | VECTOR | FLICKER | RAMPART |
| `ROLE` / `DIFFICULTY` | DAMAGE / 1 | DAMAGE / 3 | TANK / 2 |
| `HEALTH` / `ARMOR` / `SHIELDS` | 200 / 0 / 0 | 150 / 0 / 0 | 300 / 200 / 0 |
| `SPEED` | 4.2 | 4.6 | 3.9 |
| `ULT_COST` / `ULT_NAME` / `ULT_CALLOUT` | 1500 / LOCK-ON / "LOCKED ON!" | 1100 / PULSE BOMB / "BOMB AWAY!" | 1400 / QUAKE SLAM / "QUAKE!" |
| `MAX_AMMO` / `RELOAD_TIME` | 30 / 1.5 | 40 / 1.0 | 0 / 0 |
| `KIT` rows `(key, name, one-line)` | LMB PULSE RIFLE; RMB/F HELIX ROCKETS; SHIFT SPRINT; E HEAL FIELD; Q LOCK-ON | LMB TWIN PISTOLS; RMB/F or SHIFT BLINK (3 charges); E REWIND; V QUICK MELEE; Q PULSE BOMB | LMB ROCKET HAMMER; RMB/F BARRIER (hold); SHIFT CHARGE; E FLAME STRIKE; Q QUAKE SLAM |
| `LABELS` (for the kill feed) | primary PULSE RIFLE, secondary HELIX, ult LOCK-ON | primary PISTOLS, ult PULSE BOMB | primary HAMMER, ab1 CHARGE, ab2 FLAME STRIKE, ult QUAKE |
| HUD tile order (left to right) | ab1 SPRINT, ab2 HEAL FIELD, secondary HELIX | ab1 BLINK, ab2 REWIND | ab1 CHARGE, ab2 FLAME STRIKE, secondary BARRIER (meter) |

`LABELS` also maps `melee` to MELEE for every hero. `chain` (Detonator chain blast) is labelled with `theme.enemy_name('detonator')`.

---

## 4. Enemies

### 4.1 Kinds and theme names

| kind key | Role (fidelity inspiration) | `omnic` display name | `seoul` display name | Optional image (`seoul` only) |
|---|---|---|---|---|
| `trooper` | Ranged line unit (Null Sector Trooper) | TROOPER | CHEONGGWI | `dokkaebi-normal` |
| `slicer` | Fast lunging flanker (Slicer) | SLICER | JEOKGWI | `dokkaebi-elite` |
| `detonator` | Armored walker that explodes (Detonator) | DETONATOR | HWAGWI | none (code-drawn) |
| `eradicator` | Barrier-holding tank (Eradicator) | ERADICATOR | JANGSEUNG | none (code-drawn) |
| `warden` | Boss with recon/sentry modes (Bastion) | WARDEN | SPIRIT KING | `dokkaebi-boss` |
| `dummy` | Test target only; never spawned by waves | DUMMY | DUMMY | none |

### 4.2 Stats (stage 1, before scaling)

| kind | Pools | Speed | radius | height | width | head band (v0, v1) | Score | Pinnable / STUN_MULT / knockback |
|---|---|---|---|---|---|---|---|---|
| trooper | 75 health | 1.8 | 0.25 | 0.70 | 0.44 | (0.00, 0.20) | 10 | yes / 1.0 / yes |
| slicer | 40 health + 40 shields | 3.4 | 0.22 | 0.46 | 0.36 | (0.00, 0.30) | 15 | yes / 1.0 / yes |
| detonator | 100 health + 100 armor | 1.6 (rush 2.6) | 0.30 | 0.58 | 0.56 | core (0.30, 0.55) | 15 | yes / 1.0 / yes |
| eradicator | 150 health + 100 shields; barrier 400 | 1.3 (turn 90 deg/s) | 0.35 | 0.80 | 0.66 | (0.00, 0.18) | 30 | yes / 1.0 / yes |
| warden | 800 health + 600 armor (+300 shields in phase 2) | 1.1 | 0.45 | 1.00 | 0.90 | core (0.35, 0.55) | 150 | no / 0.4 / no |
| dummy | 1000 health (settable) | 0 | 0.30 | 0.70 | 0.44 | (0.00, 0.20) | 0 | yes / 1.0 / yes |

Head bands are fractions of the sprite height measured from the top. The same geometry drives drawing and hit tests (section 5.4).

### 4.3 Scaling and elites

- **Stage scaling.** With k = stage - 1:
  - pools x (1 + 0.15k);
  - all damage x (1 + 0.15k);
  - speed x min(1 + 0.05k, 1.3).
  - Apply these at spawn, in `Enemy.__init__`.
- **Elites.** Every non-boss spawn has an elite chance of min(0.15k, 0.45); none in stage 1.
  - Elites get pools x1.6, speed x1.2 and score x2.
  - Painters receive `elite=True` and add cyan trim (0, 220, 255).
  - The minimap dot is cyan.

### 4.4 Behaviours (ENEMIES implements; 2-4 lines per state machine)

These rules apply to every enemy type:
- Decisions such as state changes and LOS checks tick every 0.2 s, staggered by `id % 5 * 0.04`. Movement runs every frame.
- LOS goes through `world.los_budgeted`.
- Normal movement is `world.flow.toward(x, y)` blended with direct steering when LOS is true and the enemy is within 3 cells.
- No attack starts while the player has status `invuln`.
- Stunned or pinned enemies don't run `update`; core calls `update_disabled` instead.
- Face the player when attacking, otherwise face the direction of movement.
- The `vstate` string drives the painter.

**TROOPER** (painter states: idle, move, windup, attack, stun)
- ADVANCE along the flow until the player is within 7 cells with LOS.
- Then HOLD at 4-7 cells:
  - if closer than 3.5, back away along `flow.away`;
  - otherwise strafe sideways at 60% speed, flipping direction every 1.5 +- 0.5 s or when it hits a wall.
- Fire cycle every 2.0 s, needing LOS:
  1. WINDUP for 0.4 s (bright visor, state `windup`).
  2. Fire one bolt at the player's current position, with +-2 deg jitter.
- If LOS has been lost for more than 1.0 s, go back to ADVANCE.
- Melee for 10 every 1.0 s when within 1.0.

**SLICER** (painter states: idle, move, windup, lunge, stun)
- CHASE along the flow with a zig-zag of +-0.4 lateral offset at 2 Hz.
- Flanking: when within 5 cells with LOS, odd-id slicers steer for the point 1.5 behind the player (player position minus facing x 1.5), and even-id slicers go straight in.
- Lunge, when within 3.0 with LOS and the 3.0 s lunge cooldown is ready:
  1. WINDUP for 0.35 s: stops, crouches, visor flashes red.
  2. LUNGE toward the player's position at windup start, at 9 cells/s for up to 2.5 cells, stopping at walls. If it passes within 0.7 of the player, it deals 20 once, through `enemy_hits_player`, so a barrier can block it.
  3. RECOVER for 0.4 s.
- Melee for 12 every 0.8 s when within 0.9.

**DETONATOR** (painter states: idle, move, armed_a, armed_b, stun)
- WALK along the flow. Within 4 cells with LOS, rush at 2.6.
- At 1.5 or closer it ARMs: stops and runs a 0.8 s fuse, blinking between `armed_a` and `armed_b` at 8 Hz with SFX `beep` every 0.2 s. Then it EXPLODEs:
  - 60 to the player, falling to 30 at r 2.0, through `enemy_hits_player` with LOS;
  - 120 to other enemies within 2.0 (source None: no credit, no score);
  - it dies with no score.
- A stun during the fuse cancels it (via `update_disabled`).
- **When the player kills it:** 0.25 s later it detonates as a chain blast: 120 to enemies within 2.0 (credited to the player, ability `chain`) and 30 to the player if within 2.0.

**ERADICATOR** (painter states: idle, move, attack, stun)
- MOVE along the flow until within 6 cells with LOS, then HOLD at 5-7 cells, strafing at 0.5 speed.
- Turns toward the player at no more than 90 deg/s, which is what makes flanking work.
- **Barrier:** a `Barrier(team=TEAM_ENEMY, max_hp=400, half_width=1.0)` posed each frame 0.9 in front along its facing.
  - Deploys when the player is within 10 with LOS.
  - Lasts up to 8 s, then an 8 s cooldown, which also starts if the barrier breaks.
  - No regen while it is up.
- **Burst:** 3 bolts, 0.15 s apart, every 3.0 s with LOS.
- Melee for 15 every 1.0 s when within 1.0.
- **What its barrier blocks** (enemy barriers are ignored by enemy bolts):
  - blocks player hitscan, player projectiles (except Flame Strike) and Quake Slam;
  - does not block the hammer, Pulse Bomb splash or Charge.

**WARDEN** (boss; painter states: recon, recon_attack, sentry_windup, sentry, stomp_windup, stun)
- **RECON:**
  - Moves along the flow to within 8 cells with LOS, then holds.
  - One bolt every 0.6 s with LOS (every 0.45 s in phase 2).
- **SENTRY:**
  - Every 12 s (first at 6 s after spawn), when it has LOS and the player is within 12.
  - SENTRY_WINDUP for 0.8 s: red glow and SFX `warn`.
  - SENTRY for 4.0 s: stationary, 10 bolts/s aimed at the player with +-6 deg jitter.
  - Then 1.0 s recovering (state `recon`, not firing).
- **STOMP:**
  - When the player is within 2.5, the 6 s cooldown is ready and it isn't in SENTRY.
  - STOMP_WINDUP for 0.6 s: red floor ring of r 3.0 and SFX `warn`.
  - Then 40 damage to the player within 3.0, knockback 1.5 away, and `slow` (mag 0.6) for 1.5 s.
- **PHASE 2:**
  - Once, when health + armor <= 50% of their maximum.
  - `pool.add_max_shields(300)`.
  - Summons 2 slicers at open cells 1-3 from the warden. Summons may exceed the alive cap by up to 2.
  - Fire interval drops to 0.45 s. Emits `boss_phase`.
- Not pinnable, stun x0.4, knockback-immune.

### 4.5 Enemy attacks (projectile specs)

All enemy ranged attacks are `Projectile(team=TEAM_ENEMY)`. They fly at z = 0.45 (visual only; collisions are 2D) and die on walls. Enemy bolts pass through enemy barriers (team rule). Up to 6 bolts per frame get a spark particle on impact.

| Source | Speed | radius | Damage (stage 1) | Cadence | TTL / range | Colour |
|---|---|---|---|---|---|---|
| Trooper bolt | 8 | 0.12 | 10 | 1 per 2.0 s, after a 0.4 s windup | 1.25 s / 10 | (255, 70, 50), white core |
| Eradicator bolt | 9 | 0.12 | 10 x 3 (0.15 s apart) | every 3.0 s | 1.3 s / 12 | (255, 120, 40) |
| Warden recon bolt | 10 | 0.15 | 15 | 0.6 s (0.45 s in phase 2) | 1.4 s / 14 | (220, 80, 255) |
| Warden sentry bolt | 12 | 0.10 | 6 | 10/s for 4.0 s | 1.2 s / 14 | (255, 220, 60) |

Area attacks that aren't projectiles:

| Source | Area | Damage (stage 1) | Warning |
|---|---|---|---|
| Detonator blast | r 2.0 | player 60 to 30; enemies 120 | 0.8 s blink and beep |
| Detonator chain (killed) | r 2.0 | enemies 120 (player credit); player 30 | 0.25 s |
| Warden stomp | r 3.0 | 40, knockback 1.5, slow 40% for 1.5 s | 0.6 s red floor ring |

### 4.6 Wave and stage composition

**Wave kinds:** ASSAULT (kill everything), CAPTURE (section 4.7), BOSS (the Warden plus an escort). The stage-1 target wave length is 30-60 s.

- **Spawning:**
  - At wave start, spawn up to `CAP_ALIVE` = 10 enemies, then 1 every 1.5 s while alive < 10.
  - Order: shuffled with `world.rng`, except that Eradicators go in the first batch.
  - Spawn cells are open cells at least 7 from the player (fallback >= 5, then >= 3).
  - The boss spawns at the reachable open cell with the largest `flow.dist`.
- **Pacing:** 3.0 s after a wave clears, the next wave starts. After wave 5 comes the stage intermission (section 6.2).

| Stage | W1 ASSAULT | W2 ASSAULT | W3 CAPTURE | W4 ASSAULT | W5 BOSS |
|---|---|---|---|---|---|
| 1 | T4 S2 | T4 S3 D2 | E1 at start + trickle of 12 | T4 S3 D2 E2 | WARDEN + T3 D2 (+S2 summoned) |
| 2 | T5 S3 E1 | T5 S4 D2 E1 | E2 at start + trickle of 14 | T5 S4 D3 E3 | WARDEN + T4 D2 E1 |
| 3 | T6 S4 E1 | T6 S5 D2 E1 | E3 at start + trickle of 16 | T6 S5 D3 E3 | WARDEN + T5 D2 E1 |
| n >= 4 (endless) | Stage 3 row + (n-3) T and (n-3) S per assault wave | same | trickle 16 + 2(n-3); E3 | same | Stage 3 row + (n-3) T |

(T = trooper, S = slicer, D = detonator, E = eradicator.)

- **Trickle mix:** 45% T, 35% S, 20% D, one every 2.5 s while fewer than 8 are alive.
- **Stage 3 clear:** emits `victory` once and sets `world.victory = True`. Play then continues into stage 4.

### 4.7 Capture objective (wave 3 of every stage)

- **Point:** centre (10.0, 10.0), radius 1.8. That covers the 12 open cells of the centre room, including the two small health packs.
- **Progress:** fills at 1/12 per second (12 s total) while the player is inside and no alive enemy is inside. It holds when the player leaves; it never decays.
- **States:**
  - `neutral` (player outside);
  - `capturing`;
  - `contested` (player and at least one enemy inside);
  - `overtime`;
  - `captured`;
  - `failed`.
- **Time limit:** 90 s from wave start. At 0 s:
  - if the player is inside, OVERTIME runs for as long as the player stays inside, with progress continuing when not contested;
  - leaving for more than 0.5 s during overtime, or being outside at 0 s, means FAILED.
- **Captured:**
  - Every remaining enemy self-destructs: dies with no score, 8 particles each, source None.
  - Reward: +100 x stage score, and +20% of `ULT_COST` added to ult charge. This bonus ignores the ult-active lock but is capped at the cost.
  - Emits `objective` with state `captured`.
- **Failed:** the trickle stops. Remaining enemies must be killed to clear the wave. No reward.
- **Visuals:**
  - The director emits a floor ring at the point (width 3). Colour by state: neutral (235, 241, 237), capturing (80, 170, 255), contested (255, 150, 40), overtime (255, 70, 60).
  - The HUD draws the widget and the through-wall marker (section 6.3).
- **Theme words:** omnic "CAPTURE THE POINT", seoul "SEAL THE GATE". The letter on the widget is "A".

### 4.8 Health packs (FOUNDATION, `world.py`)

- **Positions:**
  - large (heal 250, respawn 15 s): (1.5, 9.5), (18.5, 9.5), (5.5, 14.5), (14.5, 5.5);
  - small (heal 75, respawn 10 s): (5.5, 5.5), (9.5, 9.5), (10.5, 10.5), (14.5, 14.5), (1.5, 14.5), (18.5, 5.5).
- **Pickup:** within 0.75, and only if the player is missing health or armor. Heals health first, then armor. Emits `pack_pickup` and `heal` (ability `pack`, no ult charge).
- **Drawing:** a small pack is 0.30 tall and a large one 0.45 tall.
  - Omnic theme: a white box with a blue cross.
  - Seoul theme: the reskin's gold charm with a red cross.
  - Bobbing +-3 px uses the sim clock.
- **Minimap:** a green dot while active.

### 4.9 Score

`world.score` is added to by core `apply_damage` on a credited kill:
- base: `SCORE` x (2 if elite) x stage;
- plus 5 x stage for a crit kill.

The capture reward is added by the director. Rank letters are unchanged: S >= 5000, A >= 2000, B >= 800, C >= 300, D below that.

---

## 5. Combat systems

### 5.1 World geometry

- **Heights.** Floor z = 0, ceiling z = 1, eye `EYE_Z` = 0.5.
- **Depth.** For a point (x, y) seen from camera (cx, cy, a):
  - depth `d = dx*cos(a) + dy*sin(a)`, which is the perpendicular distance, the same value stored in the wall z-buffer;
  - lateral `l = -dx*sin(a) + dy*cos(a)`.
- **Column.** `col = (0.5 + atan2(l, d) / FOV) * COLS`. Screen x = col x 1024 / 320.
- **Vertical.** Horizon = 384 + pitch. A point at height z has screen y = horizon + (EYE_Z - z) x 768 / d.
- **Sprites.** A sprite has its bottom at z = z0 (0 for everything standing) and height h:
  - top_y = horizon + (0.5 - z0 - h) x 768 / d;
  - pixel height h x 768 / d;
  - column width = width / (d x FOV) x COLS.
- **Walls.** Unchanged: height 768 / d, centred on the horizon.

### 5.2 Damage pipeline: `combat.apply_damage` (FOUNDATION)

```python
def apply_damage(world, target, amount, source=None, *, ability='primary', crit=False,
                 from_xy=None) -> float:
    # 1. reject: target dead or dying, amount <= 0
    # 2. if target.status.taken_mult(now) == 0 -> return 0            (invuln, e.g. Rewind)
    # 3. if target is world.player and world.debug['god']:
    #        emit 'player_hurt'(amount raw, from_xy, ability); return 0
    # 4. dealt = target.pool.absorb(amount, world.now)                  (5.3; crit x2 is applied by the CALLER before this)
    # 5. target.last_hit = now; target.on_damaged(world, dealt, source, crit, ability)
    # 6. if source is world.player: source.add_ult(dealt)               (no gain while ult active; 5.9)
    # 7. emit 'damage'{target, source, amount: dealt, raw: amount, crit, ability, killed, x, y, to_player}
    #    if target is world.player: emit 'player_hurt'{amount: dealt, from_x, from_y, ability}
    # 8. if target.pool.dead: target.alive = False; target.dying_until = now + 0.3
    #        target.on_death(world, source, ability)
    #        credited = source is world.player
    #        if credited and target is an Enemy: world.score += score (4.9)
    #        emit 'kill'{target, name, source, killer, ability, label, crit, score, boss, ult, x, y}
    # return dealt
```

- `ult` in the `kill` event is True when `ability == 'ult'`, or when the source hero has `ult_active_left > 0`.
- `killer` is the hero's NAME, or `theme.enemy_name(kind)` for environment kills. Environment kills aren't shown in the kill feed.
- `label` is `source.LABELS.get(ability, ability.upper())`.

**Enemy damage on the player:**
- Melee and area damage always goes through `combat.enemy_hits_player(world, source, amount, from_xy, ability)`. If an active player-team barrier crosses the segment from `from_xy` to the player, the barrier takes the damage (`Barrier.take`) and the function returns 0. Otherwise it calls `apply_damage`.
- Enemy projectiles hit barrier segments physically (section 5.5).
- Enemies never subtract player HP directly.

### 5.3 Pools: armor, shields, health and healing (`combat.HealthPool`)

```python
def absorb(self, amount, now):          # order: shields -> armor -> health
    self.last_damage = now; dealt = 0.0; r = amount
    if self.shields > 0:
        a = min(self.shields, r); self.shields -= a; r -= a; dealt += a
    if r > 0 and self.armor > 0:        # armor: every raw point landing on armor deals 0.7
        eff = r * (1 - ARMOR_REDUCTION); a = min(self.armor, eff)
        self.armor -= a; dealt += a; r -= a / (1 - ARMOR_REDUCTION)
    if r > 1e-9 and self.health > 0:
        a = min(self.health, r); self.health -= a; dealt += a
    return dealt                        # dealt excludes overkill; drives ult + stats
```

- `dead` means `health <= 1e-6`.
- **Shields** regenerate 30/s once 3.0 s have passed since `last_damage` (`update(dt, now)`).
- **Armor and health never regenerate.**
- **`heal(amount)`** fills health, then armor, and returns the amount actually healed.
- **`add_max_shields(n)`** raises both the max and the current shields.
- **`scale(mult)`** is used for stage and elite scaling.
- **Displayed numbers** are rounded up (ceil), so a living target never shows 0.

Test vectors (FOUNDATION must assert both):
- `HealthPool(100, 50, 50).absorb(100)` gives shields 0, armor 15, health 100, dealt 85.
- `.absorb(200)` on a fresh pool gives shields 0, armor 0, health about 21.43, dealt about 178.57.

### 5.4 Hitscan and headshots: `combat.hitscan` (FOUNDATION)

```python
hit = hitscan(world, shooter, angle, pitch, max_range=MAX_DEPTH)
```

1. **Wall.** `wall_d` = `cast_ray(x, y, angle)[0]`.
2. **Barriers.** For each active barrier whose team differs from the shooter's, intersect the ray with the segment. The nearest hit is a candidate.
3. **Enemies.** For each alive, non-dying enemy of the other team:
   - `proj = dx*cos + dy*sin` must be > 0.1.
   - `perp = |dx*sin - dy*cos|` must be <= width/2 + `HIT_PAD` (0.08).
   - If `proj` is the nearest so far:
     - `z_aim = EYE_Z + pitch * proj / 768`;
     - `h = height * height_mult`;
     - it is a hit when `z0 - 0.03 <= z_aim <= z0 + h + 0.03`;
     - it is a crit when `z0 + h*(1 - v1) <= z_aim <= z0 + h*(1 - v0)`.
4. **Result.** Return `Hit(kind, target, dist, x, y, z, crit)` for the nearest of wall, barrier and enemy.
   - `kind` is one of `'enemy' | 'barrier' | 'wall' | 'none'`.
   - Aiming at the sky or the floor past the sprite is a miss. This fixes the existing bug.

- The hero applies falloff, then crit x2 (`CRIT_MULT`), then calls `apply_damage(..., crit=hit.crit)`.
- A barrier hit calls `Barrier.take(amount)`, with no hitmarker and a blue spark.
- Every trace emits `shot{hero, hit: kind == 'enemy', crit, kind, x, y}`.
- **Geometry check:** a trooper-sized dummy (height 0.70, head band (0, 0.2)) 5 cells ahead must give:
  - pitch 0: body hit;
  - pitch +20 px: crit;
  - pitch +60 px: miss (above);
  - pitch -120 px: miss (below).

### 5.5 Projectiles (`combat.Projectile`, updated by core)

- **Motion.** Movement uses substeps of <= 0.25 cells.
- **Collision order per substep:**
  1. **Wall:** calls `on_hit(world, proj, None, x, y)` if set; otherwise the default impact. Then the projectile dies.
  2. **Barrier of another team,** unless `through_barriers`: `barrier.take(damage + splash center)`, then it dies. Player projectiles can damage enemy barriers; enemy projectiles are stopped by the player's barrier.
  3. **Target:**
     - A player projectile hits alive enemies within `radius + enemy.radius` whose id isn't already in `hit_ids`.
     - An enemy projectile hits the player within `radius + 0.3`.
     - Default impact: `apply_damage(damage)`, plus `splash()` if `splash_r > 0`. The directly hit target takes `splash_center` in full (distance counted as 0) and is excluded from the splash pass, so a direct Helix hit deals 40 + 80 = 120.
     - With `pierce`, the target id is recorded and the projectile keeps going; otherwise it dies.
- **Expiry.** When `ttl` runs out, `on_expire(world, proj)` is called if set.
- **Crits.** Projectiles never crit.
- **Cap.** At most 40 projectiles (`CAP_PROJECTILES`). At the cap, new enemy projectiles are dropped, and a new player projectile evicts the oldest enemy projectile.

`combat.splash(world, x, y, radius, dmg_center, dmg_edge, source, team, ability, *, exclude=(), ignore_barriers=False, hit_player=False)`:
- **Damage:** linear falloff by centre distance. It needs `world.los(x, y, target)`.
- **Barriers:** unless `ignore_barriers`, targets whose line from the blast crosses an active barrier of their own team are skipped.
- **Result:** emits `explosion{x, y, radius, team}` and returns the targets hit.

### 5.6 Barriers and how enemy attacks interact with them

`combat.Barrier`:
- **Shape:** a segment set each frame with `set_pose(cx, cy, facing)`.
- **Fields:** `team`, `hp`, `max_hp`, `half_width`, `owner` and `active`.
- **`take(world, amount, source)`:**
  - absorbs `min(hp, amount)` and emits `barrier_damage{barrier, amount, team, source}`;
  - at hp <= 0 it sets `active = False` and emits `barrier_broken`;
  - ult: if `owner is world.player`, the owner gains 0.5 per HP absorbed; if `source is world.player`, the source gains 0.5 per HP dealt.
- **Cap:** at most 4 barriers: 1 player barrier and 3 enemy barriers. A 4th Eradicator waits to deploy.
- **Blocked by barriers:**
  - enemy projectiles against the player's barrier;
  - Slicer lunge damage, Detonator blasts and Warden stomps when the source-to-player segment crosses the player's barrier. The Slicer's lunge motion also stops at the barrier line.
- **Not blocked:** player hitscan and projectiles never collide with the player's own barrier (team rule).
- **Rendering:** barriers are world segments drawn as additive column spans (section 7.7). RAMPART's own barrier is not drawn in the world; it is drawn as the screen overlay instead. Flag it `owner_view_only`, and the renderer skips it.

### 5.7 Status effects (`combat.StatusSet`)

| Kind | Effect | Sources |
|---|---|---|
| `stun` | Can't move or act; `update_disabled` runs instead of `update`; sprite at 60% height with stars | Quake Slam (2.5 s x STUN_MULT) |
| `pinned` | Like stun; carried by RAMPART each frame | Charge |
| `slow` | Speed x mag (the mag of the strongest active slow applies) | Warden stomp (mag 0.6, 1.5 s) |
| `root` | Can't move, can still act | RAMPART during Quake (0.6 s) |
| `invuln` | `taken_mult` = 0; enemies don't start attacks on the player | FLICKER Rewind (0.5 s) |

`add(kind, duration, now, mag=1.0)` extends the duration to the max of the old and new values. Status timers use the sim clock, so they freeze while paused.

### 5.8 Knockback

`combat.knockback(world, ent, from_x, from_y, dist)`:
- Moves the entity away from the source by `dist`, in 4 `move_slide` substeps within the same frame.
- Ignored if the entity is `knockback_immune`, and for the boss.

### 5.9 Ult charge rules

- **Damage.** +1 per point of damage actually dealt to enemies, on any pool, with no overkill. This comes from the return value of `apply_damage`.
- **Barriers.** +0.5 per HP dealt to enemy barriers. RAMPART also gets +0.5 per HP his barrier absorbs.
- **Healing.** +1 per HP healed by the hero's own abilities (Heal Field). The ability code calls `hero.add_ult(healed)` itself; `combat.heal` never adds ult. Health packs and Rewind give nothing.
- **Passive.** +5 per second while `director.in_combat` (a wave is active; not during countdown, intermission, clear delay or pause).
- **Objective.** +20% of `ULT_COST` on capture.
- **Lock.** No gain while `ult_active_left > 0`, except the capture bonus.
- **Cap.** Clamped to [0, ULT_COST]. `ult_ready` is emitted once, on the frame it reaches the cost.
- **Hero swap.** On swap, `new_charge = min(old_charge / old_cost, 0.30) * new_cost`.

### 5.10 Kill credit, stats hooks

- **Credit.** The player gets credit when `source is world.player`. For projectiles and effects, the source is their `owner`. Detonator chain kills are credited through the stored killer.
- **Stats.** All stats come from bus events only (section 7.5). No module keeps its own kill counters apart from `stats.py`.

---

## 6. HUD and screens

### 6.1 Flow and mouse lock

```
TITLE --click/Enter/Space--> HERO_SELECT --lock in--> COUNTDOWN(3s) --> PLAYING
PLAYING <--> PAUSED            (Esc/P/focus/lock loss -> PAUSED; click -> PLAYING; X -> END_BANNER)
PLAYING --stage clear--> INTERMISSION(8s, 1/2/3 swap, Enter skip) --> PLAYING
PLAYING --player death--> END_BANNER(2s) --> POTG(<=6s, any key skips; skipped if no highlight) --> SUMMARY
SUMMARY --Enter/click--> COUNTDOWN (same hero, new World)     SUMMARY --H--> HERO_SELECT
```

| State | World update | Mouse | Drawn |
|---|---|---|---|
| TITLE, HERO_SELECT, SUMMARY | none | unlocked, visible | full-screen screen |
| COUNTDOWN | yes, with the director idle (move and look allowed) | locked | world, HUD and countdown overlay |
| PLAYING | yes | locked | world and HUD |
| PAUSED | frozen (sim dt 0) | unlocked | last frame (copied once) plus the cached dim layer and pause panel |
| INTERMISSION | yes, with the director in intermission (no enemies) | locked | world, HUD and intermission panel (top half, not a full dim) |
| END_BANNER | frozen | unlocked | last frame plus the banner |
| POTG | replay only | unlocked | replayed scenes plus the banner |

### 6.2 Screens (HUD_UX, `screens.py`)

- **TITLE.** `theme.backdrop()` if present (drawn once into a cached surface), otherwise the grid background. Contents:
  - `theme.TITLE` (omnic "ROBOT WAVE FPS", seoul "DOKKAEBI: NIGHTFALL");
  - the subtitle "HERO EDITION";
  - a box with the 3 hero portraits;
  - a rules box: "5 WAVES = 1 STAGE", "WAVE 3: CAPTURE", "WAVE 5: BOSS", "CLEAR STAGE 3 FOR VICTORY", and the rank thresholds;
  - a blinking "CLICK TO PLAY".
  - Any cached overlay is built once; the reskin's per-frame 1024-line gradient is not allowed.
- **HERO_SELECT.**
  - 3 cards of 300x440 at x = 44, 362, 680 and y = 150.
  - Each card has a portrait (from `draw_icon('portrait')`, 96x96), NAME (size l), ROLE and difficulty stars, a pool bar split into 25-HP segments coloured by type, and the 5 KIT rows (key in yellow, name in white).
  - The highlighted card gets a 3 px border in the hero `COLOR`.
  - A LOCK IN button of 240x56 centred at y = 640.
  - Lock-in plays a white flash of 0.15 s (a `BLEND_RGB_ADD` fill that decays).
- **COUNTDOWN.** "MATCH STARTS IN 3 / 2 / 1" (size xl) at y = 230, and "CLICK TO LOCK MOUSE" if the mouse isn't locked.
- **PAUSED.**
  - Cached 50% black layer.
  - "PAUSED" (size xl); "CLICK TO RESUME"; "X - END MATCH"; "M - MUTE (on/off)"; "[ ] - SENS 1.0x".
  - The current hero's KIT list.
  - Live stats: ELIMS, DAMAGE, ACCURACY, TIME.
- **INTERMISSION.**
  - A panel of 600x260 at the top centre (y = 120): "{STAGE_WORD} {n} CLEAR" (size xl, stage colour), SCORE, ELIMS, and "NEXT {STAGE_WORD} IN 6.2s".
  - Hero chips "1 VECTOR  2 FLICKER  3 RAMPART", with the current one highlighted and "PRESS 1/2/3 TO SWAP (KEEP 30% ULT)".
  - Enter or Space skips.
  - After stage 3, the header is "VICTORY!" in gold, with "ENDLESS MODE CONTINUES".
- **END_BANNER.** A 2.0 s slanted band (parallelogram, 1024x120 at y = 300) reading "DEFEAT", or "VICTORY" when `world.victory`.
- **POTG.**
  - The recorded scenes are drawn through `render.draw_scene`, with no viewmodel and no HUD.
  - Slanted banner at the top: "PLAY OF THE GAME" / hero NAME / "4 ELIMS IN 5.2s".
  - A red hitmarker flashes at the crosshair on kill frames.
  - Any key or click skips.
  - If `potg.best()` is None, skip POTG entirely. Fallback (cut item 1): a static card with the same text over the last recorded frame.
- **SUMMARY.** Header VICTORY or DEFEAT. Then:
  - the hero portrait and name;
  - left column, stats: ELIMINATIONS, DAMAGE DONE, CRIT ACCURACY, WEAPON ACCURACY, HEALING, DAMAGE BLOCKED, OBJECTIVE TIME, ULT KILLS, TIME PLAYED, WAVES CLEARED;
  - right column: up to 6 medals, as circles of radius 26 in gold (236, 193, 119), silver (190, 200, 210) or bronze (190, 120, 70), with the stat name and value;
  - bottom: SCORE and the RANK letter (size xl), then "ENTER / CLICK - PLAY AGAIN    H - HERO SELECT".

**Medals** (`stats.py`). Rate stats use minutes = max(1, time_played / 60):

| Medal | Stat | Gold | Silver | Bronze | Minimum sample |
|---|---|---|---|---|---|
| ELIMINATIONS | elims / min | 10 | 6 | 3 | none |
| DAMAGE | damage / min | 1500 | 900 | 500 | none |
| CRIT ACCURACY | crit hits / hits, % | 30 | 20 | 12 | 30 hits |
| WEAPON ACCURACY | hits / shots, % | 55 | 40 | 25 | 50 shots |
| OBJECTIVE TIME | seconds on the point | 30 | 20 | 10 | none |
| SUPPORT | (healing + blocked) / min | 600 | 300 | 120 | none |

**Play of the Game** (`potg.py`):
- **Recording.** `record(world, scene)` is called every frame and stores the scene reference at 20 Hz of sim time, into an 8 s ring (160 entries).
- **Scoring.** From `kill` events credited to the player, over a rolling 8 s window:
  - 100 per kill, +50 for each extra kill within 3 s of the previous one;
  - +150 for an ult kill, +200 for a boss kill, +25 for a crit kill.
- **Capture.** When the window score beats the best so far, set `pending_until = now + 1.0`. At that time, copy the last 6 s of the ring (120 refs) as the best highlight, with its meta (hero, kill count, span).
- **Replay.** Plays at 20 Hz of real time.

### 6.3 In-match HUD layout (1024x768; HUD_UX, `hud.py`)

```
+----------------------------------------------------------------------------------+
|[MINIMAP 140]          STAGE 2  |  WAVE 3/5            VECTOR [HELIX] TROOPER     |
|                       CAPTURE THE POINT - 7 LEFT      VECTOR  >  SLICER  (x5)    |
|                          ( A )  1:24                                             |
|SCORE 001234              CONTESTED                                               |
|x2 MULT                                                                           |
|                     WAVE 3 / CAPTURE THE POINT  (banner y=230)                   |
|                                   -+-    arcs r=120, hitmarkers                  |
|                     ELIMINATED TROOPER +20   (y=440, 464, 488)                   |
|                          ULTIMATE READY / LOCKED ON!  (y=620)                    |
|[PORTRAIT] VECTOR              ( 82% )       [SHIFT][ E ][RMB]         30         |
|           |||||||||||  185 / 200   ult ring      ability tiles      / 30        |
+----------------------------------------------------------------------------------+
```

| Element | Geometry | Notes |
|---|---|---|
| Minimap | (12, 12, 140, 140), cell 7 px | Walls pre-drawn once. Per frame: enemy dots (r 2, boss r 4, colour by kind, elites cyan), active packs as green dots, the objective circle, the Heal Field ring, and the player triangle. |
| Score | (12, 158) size m "SCORE 001234"; (12, 184) size s "x2 MULT" | Uses `theme.WORDS['score']`. |
| Stage and wave | centred x 512, y 10, size m: "{STAGE} 2  \|  WAVE 3/5" | |
| Wave label | centred y 38, size s: "ASSAULT - 7 LEFT" / "CAPTURE THE POINT" / "BOSS" | Hidden while the boss bar is up. |
| Objective widget | ring centred (512, 86), r 28, width 5; "A" in the middle (size m); timer "1:24" at (552, 76); state label centred at y 122 | Progress is drawn as up to 48 line segments of width 5; `draw.arc` leaves gaps. State colours as in 4.7. |
| Objective marker | `render.project_point(cam, 10, 10, 0.9)`; a diamond of 14 px with "A 12m" | Drawn even through walls. When behind the camera, or when off-screen, it is clamped to the screen edge (margin 24). |
| Boss bar | rect (302, 64, 420, 14), 25-HP segments coloured by pool; name at (302, 44), size s | Only while `director.boss` is alive. |
| Kill feed | right-aligned at x 1012, rows at y = 12 + 28 i, max 5, 4.0 s each, fading over the last 0.5 s | Each row is a surface pre-rendered at event time: killer in (80, 190, 255), a tag box ("[HELIX]", a skull for a crit), victim in (255, 90, 80). |
| Crosshair | hero `draw_crosshair` at (512, 384) | |
| Hitmarker | 4 diagonal lines, gap 8 | Body: white, length 10, 0.12 s. Crit: length 14 with red tips, 0.18 s, SFX `crit`. Kill: red X of length 18, 0.30 s. |
| Elimination pop-ups | centred x 512, y = 440 + 24 i, max 3, 2.0 s each | "{KILL_WORD} {NAME} +{score}"; KILL_WORD is ELIMINATED (omnic) or BANISHED (seoul). |
| Ult prompt | centred y 620 | "ULTIMATE READY" (Q) for 1.5 s on `ult_ready`; the hero callout for 1.2 s on `ult_used`. |
| Wave banner | centred y 230 | "WAVE 3" (size xl) plus the kind label (size l) for 2.0 s; "WAVE CLEAR" for 1.5 s. |
| Damage arcs | arcs of radius 120 around the centre, +-25 deg wide, width 6, red (230, 40, 40) | 0.8 s each, max 4. The angle is from the player to `from_xy`, relative to the view; forward is up. |
| Portrait | (20, 668, 72, 72) in a slanted panel | Cached from `draw_icon('portrait')`. |
| Hero name | (104, 668), size m | |
| Health bar | (104, 694, 280, 18), 25-HP segments with 2 px gaps | Health (235, 235, 235), armor (255, 170, 40), shields (90, 170, 255), missing (40, 48, 56). Segment width = floor(280 / segments) - 2, minimum 4. |
| HP numbers | (104, 716): size l "185" plus size s " / 200" | Total of all pools, rounded up. |
| Status chips | (392, 694), 18 px tall | "SLOW", "STUN", "ROOT"; "INVULN" in cyan. |
| Ult ring | centre (512, 700), r 38, width 6 | Fill arc in `COL_ULT` (255, 210, 60). "82%" inside, or "Q" pulsing at 2 Hz when ready. While active, the ring drains in white. |
| Ability tiles | 52x52, right-aligned so the last tile ends at x 872, gap 8, y 684 | Icon from `draw_icon`, cached plain and greyed. On cooldown: greyed icon, a dark pie sweep (clockwise from the top, 24-point polygon) and the seconds left rounded up (size m). Charge pips (6x6) at y 676. Key label under the tile at y 738 (size xs). Active: 2 px hero-colour border. `meter`: a 4 px bar inside the bottom of the tile. Ready flash: white border for 0.25 s. |
| Ammo | right-aligned at x 1004, y 682: size xl current plus size s " / 30" | White when above 25%, yellow when above 10%, red below. RAMPART shows "MELEE" instead. Reload bar (884, 742, 120, 6). |
| Enemy health bars | 40x4 px above `ScreenBox.y0 - 8`, segmented by pool | Only within 3.0 s of the last damage and when `visible`; never for the boss. |
| Low-HP vignette | 4 cached edge strips 60 px thick (dark red to black), `BLEND_RGB_ADD` | Below 35% of total max pools. Intensity pulses at 1 Hz. |
| Debug overlay | (12, 210) | Only when toggled with 0. |

**Theme words** (`theme.WORDS`):
- omnic: stage STAGE, score SCORE, kill ELIMINATED, capture CAPTURE THE POINT;
- seoul: stage SECTOR, score SPIRIT SCORE, kill BANISHED, capture SEAL THE GATE.

**Palette:** `theme.PALETTE`. The seoul theme reuses the reskin's INK, EDGE, CYAN and GOLD. Panels are cached per size (a dict keyed by (w, h, accent)) and never allocated per frame.

### 6.4 Feedback summary (game-feel)

- **Enemy hit.** The enemy flashes white for 60 ms (renderer `FLAG_FLASH`). A crit also plays SFX `crit` and shows the crit hitmarker; the old "HEADSHOT!" banner is removed.
- **Kill.** Red hitmarker, SFX `elim`, a pop-up and a kill-feed row. The enemy collapses over 0.3 s (the height multiplier goes from 1 to 0 with `FLAG_DYING`).
- **Taken damage.** A damage arc, SFX `hurt`, and a 2 px shake for 0.1 s. There is no full-screen red flash.
- **Ult.** Slow-mo, shake, callout and chime. `ult_ready` plays SFX `ult_ready` plus the pulse.
- **Ability ready.** Tile flash plus SFX `ability_ready`, played for `ab1`, `ab2` and `secondary` only when the cooldown was 4 s or longer (to avoid spam).

### 6.5 Audio (HUD_UX, `sfx.py`)

- **Initialisation.**
  - `sfx.init()` is called by app on the first KEYDOWN or MOUSEBUTTONDOWN.
  - If `pygame.mixer.get_init()` returns None, try `pygame.mixer.init(22050, -16, 2, 512)`.
  - Synthesise only for 16-bit signed formats (size -16). Otherwise, or on any exception, set `sfx.enabled = False`; every call is then a no-op.
  - `set_num_channels(12)`.
- **Synthesis.** Build sounds with `array('h')` at the mixer's frequency and channel count, and `pygame.mixer.Sound(buffer=...)`. Generate at most 1 sound per frame after init. Each sound is at most 0.35 s long.
- **Throttles:** `hit` 50 ms, `shot_*` 40 ms, `enemy_shot` 80 ms, `beep` 100 ms.

| Name | Trigger (bus mapping in `sfx.attach`) | Recipe (suggestion) |
|---|---|---|
| shot_rifle / shot_pistol | `shot` (by hero KEY) | 60 ms noise plus a 180 Hz thump / 35 ms high click |
| hammer | `ability_used` slot primary (rampart) | 120 ms low filtered noise |
| hit / crit | `damage` with source player (crit True picks `crit`) | 30 ms 1800 Hz tick / 90 ms 2400+3600 Hz ding |
| elim | `kill` credited | 150 ms square wave falling 700 to 200 Hz |
| hurt | `player_hurt` | 80 ms 120 Hz buzz |
| ult_ready / ability_ready | the same events | 3-note arpeggio, 0.3 s / 60 ms 1200 Hz blip |
| explosion | `explosion` | 300 ms decaying low noise |
| barrier_hit | `barrier_damage` | 40 ms 400 Hz thunk |
| enemy_shot | `sfx` name enemy_shot (enemies emit it) | 50 ms 600 Hz zap |
| blink, rocket, beep, warn, capture, ui | `sfx` events from heroes, enemies and screens; `objective` capturing ticks once per second | short sweeps and tones |

---

## 7. Architecture

### 7.1 Files and owners (exactly one owner per file)

| Path | Owner | Contents |
|---|---|---|
| `game/main.py` | FOUNDATION | Entry point only: `import asyncio`, `import pygame`, `from rwf.app import main`, `asyncio.run(main())` (unguarded, like the originally deployed build). |
| `game/rwf/__init__.py` | FOUNDATION | Empty. |
| `game/rwf/config.py` | FOUNDATION | Constants, caps, KEYMAP, colours (section 7.4). |
| `game/rwf/theme.py` | FOUNDATION | Theme selection, names, words, palette, optional assets (downscaled once), font path. |
| `game/rwf/core.py` | FOUNDATION | SimClock, EventBus, InputState, font/text cache, math helpers, registries, mouse lock. |
| `game/rwf/world.py` | FOUNDATION | Map, `cast_ray`, `los`, movement helpers, FlowField, Camera, Particle, HealthPack, World. |
| `game/rwf/combat.py` | FOUNDATION | HealthPool, StatusSet, Entity, Enemy base, Dummy, Hit, hitscan, apply_damage, enemy_hits_player, heal, splash, knockback, cone_targets, Projectile, Barrier, Effect. |
| `game/rwf/render.py` | FOUNDATION | Walls (textured with the performance fix, or flat), Scene, painters and sprite cache, orbs, segments, rings, projection, shake, pack painters, dummy painter. |
| `game/rwf/hero_base.py` | FOUNDATION | Ability, AbilityHUD, HeroHUD, Hero base (input, move, hitscan fire, melee, reload, ult). |
| `game/rwf/app.py` | FOUNDATION | Screen state machine, `main()`, `run_match()`, pause and pointer lock, slow-mo, debug overlay. |
| `game/rwf/hero_vector.py` | HERO_A (FOUNDATION writes the stub) | VECTOR kit, viewmodel, icons, the heal_pylon painter, HealField effect. |
| `game/rwf/hero_flicker.py` | HERO_B (stub by FOUNDATION) | FLICKER kit, viewmodel (ported `draw_gun`), icons, the Rewind buffer, the PulseBomb effect. |
| `game/rwf/hero_rampart.py` | HERO_C (stub by FOUNDATION) | RAMPART kit, hammer viewmodel, the barrier overlay, Charge, FlameStrike, the Quake effect, icons. |
| `game/rwf/enemies.py` | ENEMIES (stub by FOUNDATION) | The 5 enemy classes, their painters, the boss logic. |
| `game/rwf/waves.py` | ENEMIES (stub by FOUNDATION) | WaveDirector, the wave table, the Objective, spawning. |
| `game/rwf/hud.py` | HUD_UX (stub by FOUNDATION) | The HUD class (section 6.3). |
| `game/rwf/screens.py` | HUD_UX (stub by FOUNDATION) | Title, HeroSelect, Countdown, Pause, Intermission, EndBanner, Potg, Summary. |
| `game/rwf/stats.py` | HUD_UX (stub by FOUNDATION) | MatchStats, medals, rank. |
| `game/rwf/potg.py` | HUD_UX (stub by FOUNDATION) | PotgRecorder. |
| `game/rwf/sfx.py` | HUD_UX (stub by FOUNDATION) | Synth, attach, play, mute. |
| `tools/smoke.py` | FOUNDATION | The harness (section 9). |
| `tools/checks/check_foundation.py`, `check_campaign.py`, `check_perf.py` | FOUNDATION | Foundation suites. |
| `tools/checks/check_vector.py` / `check_flicker.py` / `check_rampart.py` | HERO_A / HERO_B / HERO_C | Hero acceptance checks. |
| `tools/checks/check_enemies.py` | ENEMIES | Enemy and wave acceptance checks. |
| `tools/checks/check_hud.py` | HUD_UX | HUD, screens, stats, POTG and sfx checks. |
| `tools/build_web.py` | FOUNDATION | Add `game/rwf/*.py` to the packed file list, keeping the `assets/` archive prefix. |
| `.gitignore` | FOUNDATION | Add `tools/out/`. |
| `game/assets/*` | nobody (read-only) | Optional art and font from the concurrent reskin. |
| `design/OVERWATCH_SPEC.md` | spec author; the integrator may append notes | |

**Rules:**
- Don't name any folder inside `game/` `build`, `static`, `dist`, `venv` or `ignore`, because pygbag's packer skips them.
- Don't add top-level modules to `game/` other than `main.py`.

### 7.2 Import rules (no cycles)

`config` <- `theme` <- `core` <- `world` <- `combat` <- `render` <- `hero_base` <- (`hero_*`, `enemies`, `waves`) <- (`hud`, `screens`, `stats`, `potg`, `sfx`) <- `app`

- **Direction.** A module may import only modules to its left, plus pygame, math, random, array, collections and the other stdlib modules that are allowed.
- **World at runtime.** `world` must not import `combat` at module level. It reaches classes through `core.ENEMY_TYPES` and `core.HEROES`, and through attributes at runtime.
- **Enemies and waves** import `config`, `theme`, `core`, `world`, `combat` and `render` (for `register_painter` only). `waves` spawns by kind string, through `world.spawn_enemy`.
- **Heroes** may also import `hero_base`. They never import `hud`, `sfx` or `app`; they talk to those through bus events.
- **`app`** imports every module. Hero and enemy modules register themselves on import.
- **Forbidden everywhere:** numpy, threading, subprocess, `time.sleep`, and `time.time()` (use `world.now` in gameplay and `core.real_time()` in UI).

### 7.3 Phases and handoff

1. **Phase 0, FOUNDATION.**
   - Build every file in 7.1. Builder files are working stubs that honour the final interfaces (see 7.9).
   - Port what already works: map, raycaster, waves, packs, score, rank, minimap.
   - Pass `python tools/smoke.py --suite foundation` and `--suite campaign`, including the `RWF_NO_ASSETS=1` run.
   - Freeze all interfaces in 7.4 and report the frozen commit or file hashes.
2. **Phase 1, builders in parallel.**
   - Each builder edits only the files it owns, runs `python tools/smoke.py --suite <slot>` and `--suite foundation`, and must not break either.
   - If a core change seems necessary, work around it inside your own file (subclass, custom Effect, callback) and add a "CORE REQUEST:" line to your final report. Never edit a FOUNDATION file.
3. **Phase 2, integrator.**
   - Run `--suite all`, `--suite perf`, and the `RWF_NO_ASSETS=1` run.
   - Handle the CORE REQUESTs, balance with the debug overlay, and fix cross-file issues. The integrator may edit any file.
   - Run `python -m pygbag --build game`, a packaging check only (pygbag 0.9.3 is installed).
   - Don't copy build output to the repo root or push without the user's go-ahead.

### 7.4 Interfaces (frozen after Phase 0)

```python
# ============================ rwf/config.py ============================
W, H = 1024, 768; COLS = 320; FOV = math.pi / 3; HALF_FOV = FOV / 2; MAX_DEPTH = 20
EYE_Z = 0.5; PLAYER_RADIUS = 0.25; HIT_PAD = 0.08
TEAM_PLAYER, TEAM_ENEMY = 0, 1
CAP_ALIVE = 10; CAP_SUMMONS = 2; CAP_PROJECTILES = 40; CAP_PARTICLES = 64
CAP_EFFECTS = 24; CAP_BARRIERS = 4; CAP_LOS_PER_FRAME = 8
CRIT_MULT = 2.0; ARMOR_REDUCTION = 0.30; SHIELD_REGEN_DELAY = 3.0; SHIELD_REGEN_RATE = 30.0
ULT_PASSIVE_RATE = 5.0; ULT_SWAP_KEEP = 0.30; ULT_SLOWMO = (0.35, 0.3)
MOUSE_YAW = 0.0014; MOUSE_PITCH = 0.55; PITCH_LIMIT = 220
WAVES_PER_STAGE = 5; VICTORY_STAGE = 3; WAVE_CLEAR_DELAY = 3.0; INTERMISSION = 8.0; COUNTDOWN = 3.0
COL_HEALTH = (235, 235, 235); COL_ARMOR = (255, 170, 40); COL_SHIELD = (90, 170, 255)
COL_PLAYER = (80, 190, 255); COL_ENEMY = (255, 90, 80); COL_CRIT = (255, 60, 40); COL_ULT = (255, 210, 60)
KEYMAP: dict[int, str]   # K_w/K_UP 'fwd', K_s/K_DOWN 'back', K_a/K_LEFT 'left', K_d/K_RIGHT 'right',
                         # K_LSHIFT/K_RSHIFT/K_SPACE 'ab1', K_e 'ab2', K_q 'ult', K_f 'alt', K_r 'reload',
                         # K_v 'melee', K_ESCAPE/K_p 'pause', K_1/2/3 'hero1/2/3', K_RETURN/K_KP_ENTER 'confirm',
                         # K_m 'mute', K_0 'debug', K_LEFTBRACKET 'sens_down', K_RIGHTBRACKET 'sens_up',
                         # K_h 'hero_select', K_x 'end_match'
MOUSEMAP = {1: 'fire', 3: 'alt'}

# ============================ rwf/theme.py =============================
KEY: str                       # 'seoul' if <game>/assets/dokkaebi-normal.png exists and RWF_NO_ASSETS unset, else 'omnic'
TITLE: str; SUBTITLE: str      # 'ROBOT WAVE FPS' | 'DOKKAEBI: NIGHTFALL'; 'HERO EDITION'
WORDS: dict[str, str]          # keys: 'stage', 'score', 'kill', 'capture' (section 6.3)
PALETTE: dict[str, tuple]      # keys: 'ink','edge','accent','accent2','text','muted','sky','floor'
def enemy_name(kind: str) -> str
def enemy_image(kind: str, base_h: int) -> pygame.Surface | None   # smoothscaled ONCE to base_h, convert_alpha, cached
def backdrop(size) -> pygame.Surface | None; def sky_strip() -> pygame.Surface | None
def font_path() -> str | None  # NotoSansKR.ttf if present, else None (pygame default font)
def load() -> None             # called by app after set_mode; never raises (missing/broken files -> None)

# ============================ rwf/core.py ==============================
class SimClock:
    now: float; dt: float; timescale: float; paused: bool
    def tick(self, real_dt: float) -> float        # 0 if paused else min(real_dt, 0.05) * timescale
    def slowmo(self, scale: float, real_seconds: float) -> None
def real_time() -> float                           # pygame.time.get_ticks() / 1000; UI animation only
class EventBus:
    def on(self, name: str, fn) -> None            # fn(data: dict); data always has 'name' and 't' (sim now)
    def off(self, name: str, fn) -> None
    def emit(self, name: str, **data) -> None      # synchronous; handlers must be cheap
    def clear(self) -> None
class InputState:
    held: set; pressed: set; released: set; mouse_dx: float; mouse_dy: float; mouse_pos: tuple
    def feed(self, ev) -> None; def poll_keyboard(self) -> None; def end_frame(self) -> None; def clear(self) -> None
    def down(self, action) -> bool; def hit(self, action) -> bool; def up(self, action) -> bool
    def axes(self) -> tuple[int, int]              # (fwd, right), each -1/0/1
def font(size_key: str) -> pygame.font.Font        # 'xs','s','m','l','xl'; default font 18/22/28/46/74 px,
                                                   # NotoSansKR 12/15/20/33/53 px; italic on
def text(s: str, size_key='m', color=(255, 255, 255)) -> pygame.Surface   # LRU cache, 512 entries
def wrap_angle(a) -> float; def clamp(v, lo, hi); def lerp(a, b, t)
def lock_mouse(on: bool) -> None; def pointer_locked() -> bool | None
HEROES: dict[str, type]; HERO_ORDER = ['vector', 'flicker', 'rampart']; ENEMY_TYPES: dict[str, type]
def register_hero(cls): ...                        # decorator, key = cls.KEY
def register_enemy(cls): ...                       # decorator, key = cls.KIND

# ============================ rwf/world.py =============================
RAW_MAP; MAP_W; MAP_H; OPEN_CELLS
def is_wall(x, y) -> bool
def cast_ray(px, py, angle) -> tuple[float, int, int, int]      # unchanged DDA
def los(ax, ay, bx, by) -> bool
def move_slide(x, y, dx, dy, r=PLAYER_RADIUS) -> tuple[float, float]
def dash_target(x, y, ang, dist, step=0.1, margin=0.3) -> tuple[float, float]
def open_cells_far(px, py, min_dist) -> list[tuple[float, float]]
class Camera: x; y; angle; pitch; shake_amp; shake_left
class FlowField:
    def rebuild(self, cx: int, cy: int) -> None     # BFS, 8-way, no corner cutting
    def dist(self, x, y) -> int                     # 999 = unreachable
    def toward(self, x, y) -> tuple[float, float]   # unit vector to the neighbour-cell centre with lower dist
    def away(self, x, y) -> tuple[float, float]
class Particle: __slots__ = ('x', 'y', 'z', 'vx', 'vy', 'vz', 'ttl', 'color', 'size')
class HealthPack: x; y; big; heal; respawn; active
    def update(self, world, dt) -> None; def emit_visuals(self, scene) -> None
class World:
    clock: SimClock; bus: EventBus; rng: random.Random; debug: dict; cam: Camera; dt: float
    player: 'Hero'; enemies: list; projectiles: list; barriers: list; effects: list
    particles: list; packs: list; flow: FlowField; director: 'WaveDirector'
    score: int; victory: bool; over: bool; projection: dict[int, 'ScreenBox']; perf: dict
    now: float  # property
    stage: int  # property -> director.stage
    def __init__(self, hero_key: str, seed=None, debug=None): ...
        # creates the hero via core.HEROES and a NullDirector placeholder (defined in world.py, same attributes,
        # does nothing). app assigns world.director = waves.WaveDirector(world) right after construction,
        # because world must not import waves.
    def set_hero(self, key: str, keep_ult_frac: float | None = None) -> None   # emits 'hero_swap'
    def update(self, dt: float, inp: InputState) -> None                       # order: 7.6
    def spawn_enemy(self, kind, x, y, elite=False, summon=False) -> 'Enemy'   # emits 'enemy_spawn'
    def alive_enemies(self) -> list; def enemies_near(self, x, y, r) -> list
    def add_projectile(self, p) -> bool; def add_effect(self, e) -> bool
    def add_barrier(self, b) -> bool; def remove_barrier(self, b) -> None; def player_barrier(self)
    def burst(self, x, y, z, n, color, speed=2.0, ttl=0.5, size=2) -> None
    def shake(self, px: float, seconds: float) -> None
    def los_budgeted(self, ax, ay, bx, by, default: bool = False) -> bool   # returns default once 8 LOS/frame are used

# ============================ rwf/combat.py ============================
class HealthPool:
    health; armor; shields; max_health; max_armor; max_shields; last_damage
    total: float; max_total: float; dead: bool   # properties
    def __init__(self, health, armor=0.0, shields=0.0): ...
    def absorb(self, amount, now) -> float; def heal(self, amount) -> float
    def update(self, dt, now) -> None; def add_max_shields(self, n) -> None; def scale(self, mult) -> None
    def segments(self) -> list[tuple[str, float, float]]   # [('health', cur, max), ('armor', ...), ('shields', ...)]
class StatusSet:
    def add(self, kind, duration, now, mag=1.0) -> None; def has(self, kind, now) -> bool
    def speed_mult(self, now) -> float; def can_act(self, now) -> bool; def can_move(self, now) -> bool
    def taken_mult(self, now) -> float; def active(self, now) -> list[str]; def clear(self) -> None
class Entity:
    id: int; team: int; x; y; angle; radius; height; width; z0 = 0.0; head_band = (0.0, 0.2)
    height_mult = 1.0; pool: HealthPool; status: StatusSet; alive = True; dying_until = 0.0
    last_hit = -9.0; knockback_immune = False; NAME: str
    def on_damaged(self, world, amount, source, crit, ability) -> None: ...
    def on_death(self, world, source, ability) -> None: ...
class Enemy(Entity):
    KIND: str; SCORE: int; BOSS = False; PINNABLE = True; STUN_MULT = 1.0
    BASE_HEALTH = 0; BASE_ARMOR = 0; BASE_SHIELDS = 0; BASE_SPEED = 0.0
    elite: bool; speed: float; dmg_mult: float; vstate = 'idle'; summoned: bool
    def __init__(self, world, x, y, elite=False): ...  # builds the pool from BASE_* x stage scaling x elite; sets
                                                       # speed and dmg_mult; NAME = theme.enemy_name(KIND)
    def update(self, world, dt) -> None: ...           # AI; only called when status.can_act
    def update_disabled(self, world, dt) -> None: ...  # stunned or pinned; default no-op
    def emit_visuals(self, scene) -> None: ...         # default: one sprite, key=KIND, state=vstate, flags from
                                                       # flash/stun/dying, height*height_mult, elite, ref=id
    def move_toward(self, world, tx, ty, dt, speed_mult=1.0) -> None   # flow + steering + move_slide
    def fire_bolt(self, world, angle, speed, damage, radius=0.12, color=(255, 70, 50), ttl=1.25) -> bool
    def melee(self, world, damage, ability='melee') -> float           # via enemy_hits_player
    def dist_to_player(self, world) -> float
@register_enemy class Dummy(Enemy): KIND = 'dummy'   # no AI; attrs: fire_every (s, None = never), bolt_damage
class Hit: __slots__ = ('kind', 'target', 'dist', 'x', 'y', 'z', 'crit')
def hitscan(world, shooter, angle, pitch, max_range=MAX_DEPTH) -> Hit
def apply_damage(world, target, amount, source=None, *, ability='primary', crit=False, from_xy=None) -> float
def enemy_hits_player(world, source, amount, from_xy, ability='melee') -> float
def heal(world, target, amount, source=None, ability='') -> float        # emits 'heal'
def splash(world, x, y, radius, dmg_center, dmg_edge, source, team, ability, *, exclude=(),
           ignore_barriers=False, hit_player=False) -> list
def knockback(world, ent, from_x, from_y, dist) -> None
def cone_targets(world, x, y, angle, half_angle_rad, reach, need_los=True) -> list   # alive enemies
class Projectile:
    __slots__ = ('x', 'y', 'z', 'vx', 'vy', 'radius', 'team', 'damage', 'splash_r', 'splash_center',
                 'splash_edge', 'ttl', 'pierce', 'through_barriers', 'hit_ids', 'owner', 'ability', 'color',
                 'core', 'size', 'on_hit', 'on_expire', 'draw', 'alive', 'ox', 'oy')
    def __init__(self, x, y, angle, speed, *, team, damage, radius=0.12, owner=None, ability='projectile',
                 ttl=2.0, z=0.45, color=(255, 70, 50), core=(255, 255, 255), size=0.08, pierce=False,
                 through_barriers=False, splash_r=0.0, splash_center=0.0, splash_edge=0.0,
                 on_hit=None, on_expire=None, draw=None): ...
    # on_hit(world, proj, target_or_None, x, y) -> bool (True = the default impact already done, consumed)
    # draw(scene, proj) -> None overrides the default single orb
class Barrier:
    x1; y1; x2; y2; team; hp; max_hp; half_width; owner; active; last_hit; owner_view_only = False
    def __init__(self, team, max_hp, half_width, owner=None, color_add=(20, 60, 120)): ...
    def set_pose(self, cx, cy, facing) -> None
    def intersects(self, ax, ay, bx, by) -> float | None   # t in [0, 1] along a->b
    def take(self, world, amount, source=None) -> float
class Effect:
    alive = True
    def update(self, world, dt) -> None: ...
    def emit_visuals(self, scene) -> None: ...
    def draw_screen(self, surf, world) -> None: ...

# ============================ rwf/render.py ============================
FLAG_FLASH = 1; FLAG_STUN = 2; FLAG_DYING = 4; FLAG_NOSHADE = 8
ScreenBox = namedtuple('ScreenBox', 'x0 y0 x1 y1 depth visible')   # 1024x768 coordinates
class Scene:
    cam: tuple                                                   # (x, y, angle, pitch)
    def sprite(self, x, y, key, state, height, width, *, z0=0.0, flags=0, elite=False, ref=None) -> None
    def orb(self, x, y, z, radius, color, core=None) -> None     # world radius
    def segment(self, x1, y1, x2, y2, color_add, *, z0=0.0, z1=0.9, edge=(120, 200, 255), ref=None) -> None
    def ring(self, x, y, r, color, width=2, n=20) -> None        # floor decal
def register_painter(key: str, fn, base_w: int, base_h: int) -> None   # fn(surf, state, elite) -> None
def build_scene(world) -> Scene
def draw_scene(surf, scene) -> dict[int, ScreenBox]
def render_frame(surf, world) -> Scene     # build + draw + world.projection + shake; returns the scene for POTG
def project_point(cam, x, y, z) -> tuple[int, int, float] | None       # (sx, sy, depth); None if depth < 0.15

# ============================ rwf/hero_base.py =========================
AbilityHUD = namedtuple('AbilityHUD', 'slot name key cd_left cd_frac charges max_charges active active_frac meter usable')
HeroHUD = namedtuple('HeroHUD', 'key name color health max_health armor max_armor shields max_shields ammo max_ammo '
                                'reloading reload_frac abilities ult_frac ult_ready ult_active_frac statuses')
class Ability:
    slot; name; key_label; cooldown; max_charges; charges; recharge_left; duration; active_left; meter = None
    def __init__(self, hero, slot, name, key_label, cooldown, charges=1, duration=0.0): ...
    def ready(self) -> bool                          # charges > 0 and the hero can act
    def use(self, world) -> bool                     # consumes a charge, starts the recharge, emits 'ability_used'
    def start(self, duration) -> None; def stop(self) -> None; def start_cooldown(self, seconds) -> None
    def update(self, world, dt) -> None              # recharges one charge at a time; emits 'ability_ready'
    def reset(self) -> None; active: bool; cd_frac: float    # properties
    def hud(self) -> AbilityHUD
class Hero(Entity):
    KEY; NAME; ROLE; DIFFICULTY; COLOR; BLURB; KIT; LABELS; HEALTH; ARMOR = 0; SHIELDS = 0; SPEED
    ULT_COST; ULT_NAME; ULT_CALLOUT; ULT_DURATION = 0.0; MAX_AMMO; RELOAD_TIME
    angle; pitch; ammo; reloading; reload_left; ult_charge; ult_active_left; move_fwd; move_right
    speed_mult; custom_motion; turn_limit = None; lock_input = False; last_fire; melee_left
    abilities: dict[str, Ability]                    # keys among 'secondary', 'ab1', 'ab2'
    HUD_ORDER: tuple                                 # e.g. ('ab1', 'ab2', 'secondary')
    def __init__(self, world): ...
    # --- provided by the base (don't override handle_input or update) ---
    def handle_input(self, inp, world) -> None       # resets speed_mult=1 and custom_motion=False; look (turn_limit);
                                                     # axes; if can act: Q try_ult, R reload, V melee;
                                                     # then self.on_input
    def update(self, world, dt) -> None              # abilities, reload, ult timer, passive ult -> think ->
                                                     # move (unless custom_motion) -> after_move
    def move(self, world, dt) -> None
    def fire_hitscan(self, world, damage, *, spread=0.0, falloff=None, ability='primary') -> Hit
        # falloff = (full_until, zero_at, min_mult); applies falloff, then crit; emits 'shot' + 'ability_used'(primary)
    def quick_melee(self, world) -> None; def start_reload(self, world) -> None; def use_ammo(self, n=1) -> bool
    def add_ult(self, pts, ignore_lock=False) -> None
    def try_ult(self, world) -> bool                 # checks and spends charge; emits 'ult_used'; calls on_ult
    def can_act(self, world) -> bool; ult_frac: float; ult_ready: bool   # properties
    def hud_state(self, world) -> HeroHUD
    def label_for(self, ability) -> str
    # --- overridden by HERO_A, HERO_B and HERO_C ---
    def on_input(self, inp, world) -> None: ...      # fire / alt / ab1 / ab2 handling
    def think(self, world, dt) -> None: ...          # before movement
    def after_move(self, world, dt) -> None: ...     # e.g. barrier pose, rewind sampling
    def on_ult(self, world) -> None: ...
    def on_removed(self, world) -> None: ...         # remove barrier/effects on swap or match end
    def draw_viewmodel(self, surf, world) -> None: ...
    def draw_overlay(self, surf, world) -> None: ...
    def draw_crosshair(self, surf, world) -> None: ...
    @classmethod
    def draw_icon(cls, slot, surf, rect) -> None: ... # slot in 'portrait', 'secondary', 'ab1', 'ab2', 'ult'
    def emit_visuals(self, scene) -> None: ...       # usually nothing

# ============================ rwf/waves.py (ENEMIES) ===================
class Objective:
    x = 10.0; y = 10.0; radius = 1.8; progress: float; state: str; time_left: float
    player_inside: bool; contested: bool
class WaveDirector:
    stage: int; wave: int; wave_in_stage: int; kind: str      # 'assault' | 'capture' | 'boss'
    state: str                                                # 'idle' | 'active' | 'cleared' | 'intermission'
    in_combat: bool; objective: Objective | None; boss: 'Enemy | None'
    remaining: int; label: str; intermission_left: float
    def __init__(self, world): ...
    def start(self) -> None                                   # after COUNTDOWN (respects debug 'start_wave')
    def update(self, world, dt) -> None
    def emit_visuals(self, scene) -> None
    def skip_intermission(self) -> None
    def debug_kill_all(self, world) -> None                  # kills alive, empties the queue, no score

# ============================ rwf/hud.py, screens.py, stats.py, potg.py, sfx.py (HUD_UX) =====
class HUD:
    def __init__(self, world): ...                            # subscribes to world.bus
    def update(self, world, real_dt) -> None; def draw(self, surf, world) -> None
class Screen:                                                 # base in screens.py
    def handle(self, ev, inp) -> str | None; def update(self, real_dt) -> str | None; def draw(self, surf) -> None
# Constructors: TitleScreen(); HeroSelectScreen(default_key); CountdownOverlay(seconds);
# PauseOverlay(world, stats, frame); IntermissionOverlay(world); EndBanner(victory);
# PotgScreen(highlight); SummaryScreen(world, stats, hero_key)
# Action strings: 'start' | 'lock:<key>' | 'done' | 'resume' | 'end_match' | 'swap:<key>' | 'skip'
#                 | 'again' | 'select'
class MatchStats:
    def __init__(self, world): ...          # subscribes; fields: elims, damage, barrier_damage, crit_hits,
                                            # hits, shots, healing, blocked, obj_time, ult_elims, time_played,
                                            # waves_cleared, stage_reached, deaths
    def update(self, world, dt) -> None     # time_played, obj_time
    def medals(self) -> list[tuple[str, str, str]]   # (medal, tier 'gold'|'silver'|'bronze', value text)
    def rank(self, score) -> tuple[str, tuple]       # ('A', colour)
class PotgRecorder:
    def __init__(self, world): ...
    def record(self, world, scene) -> None
    def best(self) -> dict | None           # {'frames': [Scene], 'hero': key, 'kills': n, 'span': s, 'kill_frames': [i]}
# sfx.py
enabled: bool; muted: bool
def init() -> None; def attach(bus) -> None; def play(name: str, vol: float = 1.0) -> None
def set_muted(on: bool) -> None; def update() -> None   # lazy synthesis, one sound per call

# ============================ rwf/app.py ================================
async def main() -> None                                       # TITLE -> SELECT -> loop run_match
async def run_match(screen, hero_key, *, input_source=None, fixed_dt=None, max_frames=None, seed=None,
                    debug=None, setup=None, on_frame=None) -> 'MatchResult'
MatchResult = namedtuple('MatchResult', 'action world stats states frames frame_ms exception')
# input_source.events_for_frame(i) -> list[pygame.event.Event]; they are fed through the same path as live events.
# setup(world) is called once after the World is created; on_frame(world, i, state) -> 'stop' | None.
# Every loop calls `await asyncio.sleep(0)` once per frame.
```

### 7.5 Event catalogue (strings; the payload keys are part of the contract)

| Event | Emitted by | Payload |
|---|---|---|
| `damage` | `combat.apply_damage` | target, source, amount, raw, crit, ability, killed, x, y, to_player |
| `kill` | `combat.apply_damage` | target, name, source, killer, ability, label, crit, score, boss, ult, x, y |
| `player_hurt` | `combat.apply_damage` | amount, from_x, from_y, ability |
| `heal` | `combat.heal` | target, amount, source, ability |
| `barrier_damage` / `barrier_broken` | `Barrier.take` | barrier, amount, team, source / barrier, team |
| `shot` | `Hero.fire_hitscan` | hero, hit, crit, kind, x, y |
| `ability_used` / `ability_ready` | Ability, Hero | hero, slot, name |
| `ult_ready` / `ult_used` / `ult_end` | Hero | hero / hero, name, callout / hero |
| `explosion` | `combat.splash` | x, y, radius, team |
| `enemy_spawn` | `world.spawn_enemy` | enemy, kind, elite, summon |
| `wave_start` / `wave_clear` | director | stage, wave, wave_in_stage, kind, label / stage, wave |
| `stage_clear` / `intermission_end` / `victory` | director | stage |
| `objective` | director | state, progress, time_left |
| `boss_spawn` / `boss_phase` | director / warden | enemy / enemy, phase |
| `pack_pickup` | HealthPack | big, amount |
| `hero_swap` | `world.set_hero` | old, new |
| `player_death` | `world.update` | hero |
| `sfx` | anyone | name, vol |

### 7.6 Frame order

**App, PLAYING state:**
1. `real_dt = clock.tick(60) / 1000`, or `fixed_dt` in the harness.
2. For each event (live plus `input_source`):
   - `inp.feed`;
   - app handling: quit, pause, focus loss, sfx init, mute, sensitivity, debug.
3. `inp.poll_keyboard()`.
4. `dt = world.clock.tick(real_dt)`. If `dt > 0`: `world.update(dt, inp)`.
5. `scene = render.render_frame(screen, world)`, then `potg.record(world, scene)`.
6. Screen-space draws: `e.draw_screen(screen, world)` for each effect → `hero.draw_overlay` → `hero.draw_viewmodel`.
7. HUD: `hud.update(world, real_dt)` → `hud.draw(screen, world)`, which calls `hero.draw_crosshair` itself.
8. Overlay screen, if any → debug overlay → `pygame.display.flip()`.
9. `inp.end_frame()`, then `await asyncio.sleep(0)`.

Render straight into the display surface. When pausing, copy it once.

**`World.update(dt, inp)`:**
1. `los_used = 0`.
2. Player: `pool.update`; `player.handle_input(inp, self)`; `player.update(self, dt)`.
3. Rebuild `flow` if the player's cell changed.
4. `director.update`.
5. Enemies:
   - `pool.update`;
   - dying ones: shrink `height_mult` over 0.3 s, then remove;
   - otherwise `update` if `status.can_act`, else `update_disabled`.
6. Separation:
   - enemy pairs closer than 0.6 are pushed apart, half each, with `move_slide`;
   - enemies are kept at least radius + 0.25 from the player.
7. Projectiles (5.5).
8. Effects: update, and drop the dead ones.
9. Drop barriers that are inactive and ownerless.
10. Packs.
11. Particles (gravity -9 on z; removed at z < 0 or ttl <= 0).
12. Camera sync and shake decay.
13. Death check: `player.pool.dead` → emit `player_death`; `over = True`.

Slow-mo: app subscribes to `ult_used` and calls `clock.slowmo(*ULT_SLOWMO)`.

### 7.7 Render primitives and the painter contract (FOUNDATION)

- **Walls.** Keep the reskin's textured walls if its textures exist, with the performance fix:
  - pre-shade every texture into 6 depth levels x 2 sides once;
  - pre-create the 128 one-pixel column subsurfaces per variant;
  - per column, `transform.scale` only the visible vertical slice;
  - drop the per-column reflection (at most one precomputed floor gradient surface of COLS x 2H, blitted at the horizon offset);
  - blit the sky strip twice.
  - Otherwise, flat shaded lines as in the original.
  - Budget: walls <= 3.5 ms desktop p95 in the corridor view.
- **One depth-sorted pass.** Sprites, orbs and segments go into `small` (320x768, allocated once) back to front by depth. Floor rings are drawn after the walls and before that pass, with a z-buffer test per ring segment at its midpoint column.
- **Sprites.**
  - Painters draw once per (key, state, elite) at base size on a transparent surface.
  - Variants: flash = a copy with `fill((255, 255, 255), special_flags=BLEND_RGB_MAX)`; shade = 3 levels (d < 6: 1.0, d < 12: 0.75, else 0.5) with `BLEND_RGB_MULT` on a copy.
  - Scaling: `transform.scale` (never smoothscale at runtime) to (columns, pixel height). Heights are bucketed: 8 px up to 256, 16 px up to 512, 32 px above, clamped to 1.5 x H.
  - Cache: LRU with 160 entries.
  - Blitting: only the column spans where `zbuf[col] > depth`, with a `blit(area=...)` per contiguous run.
  - `FLAG_STUN` adds 3 yellow orbs circling at z = z0 + h + 0.08. `FLAG_DYING` forces the 0.5 shade.
- **Orbs.** Ellipses of width 2R/3.2 and height 2R in `small`, where R = radius x 768 / d, clamped to 1-80 px. A darker outer ellipse, then the core ellipse. Depth is tested at the centre column only.
- **Segments (barriers).**
  - Span: project both endpoints to columns, clamped to the screen.
  - For each column in the span: intersect the ray with the segment to get depth t, and skip if `zbuf[col] < t`.
  - Draw z0 to z1 as `small.fill(color_add, rect, special_flags=BLEND_RGB_ADD)`, plus 1 px edge lines at the top and bottom.
  - Skip segments with `owner_view_only`.
- **Projection.** `ScreenBox` for every sprite with a `ref`, in 1024 coordinates. `visible` means at least one column passed the z-buffer.
- **Shake.** `surf.scroll(dx, dy)` after upscaling, with random ints within `shake_amp`.
- **Painter rules** (ENEMIES, and HERO_A for heal_pylon):
  - Call `register_painter(kind, fn, base_w, base_h)` at import.
  - Suggested base sizes: trooper 48x96, slicer 40x80, detonator 64x80, eradicator 72x112, warden 96x128.
  - `fn(surf, state, elite)` must handle every state listed in 4.4. Unknown states are drawn as `idle`.
  - When `theme.enemy_image(kind, base_h)` returns a Surface, blit it fitted to the base rect and add state overlays (visor glow, windup ring, stun darkening). Otherwise draw the code shapes: at most about 12 primitives, silhouettes readable at 30 px tall.
  - Painters never read the clock (the state carries all animation). Blinking is done by alternating states, such as `armed_a` and `armed_b`.

### 7.8 Debug hooks (`world.debug`; FOUNDATION implements, the director honours the wave keys)

| Key | Meaning |
|---|---|
| `god` | The player takes no damage; `player_hurt` still fires with the raw amount. |
| `inf_ult` | The ult is always ready. |
| `no_cooldowns` | Abilities recharge instantly. |
| `no_director` | Waves never start. |
| `skip_countdown` | Start in PLAYING. |
| `start_wave` | Global wave number (1-based) to start at. |
| `autokill` | Seconds after each wave start at which `debug_kill_all` runs. |
| `auto_capture` | Capture progress runs x10. |
| `skip_end_screens` | `run_match` returns right after `player_death`. |
| `kill_player_at` | Frame index at which the player's health is set to 0. |
| `perf` | Record per-system ms in `world.perf` (update, render, hud, total). |

**Env var `RWF_NO_ASSETS=1`:** theme `omnic`, the default font, flat walls, and no PNGs.

### 7.9 What the Phase 0 stubs must do

- **Heroes.** `hero_vector.py`, `hero_flicker.py` and `hero_rampart.py`:
  - Registered classes with the final class attributes (3.4).
  - A working hitscan primary (VECTOR and FLICKER), or a cone swing (RAMPART).
  - Abilities that exist with the right slots, cooldowns and charges, and emit `ability_used`.
  - A placeholder `on_ult` that emits `ult_used`.
  - Simple rectangle viewmodels and letter icons.
- **Enemies.** `enemies.py`:
  - All 5 kinds registered with the stats in 4.2.
  - A shared stub AI: flow chase plus melee through `enemy_hits_player`; Troopers also fire a bolt every 2 s.
  - Coloured-box painters.
- **Waves.** `waves.py`:
  - The full state machine, events and debug keys.
  - The real 4.6 table for counts, with capture waves run as a trickle without the objective, and bosses as a `warden` with the escort.
- **HUD.** `hud.py`: a port of the reskin/original HUD reduced to the 6.3 geometry (health bar, ammo, wave, score, cached minimap).
- **Screens.** `screens.py`: plain-text versions of every Screen class, with the right action strings.
- **Stats, POTG and audio.**
  - `stats.py`: counts elims, damage, shots and hits.
  - `potg.py`: records scenes; `best()` returns None.
  - `sfx.py`: all no-ops, with `enabled = False`.

---

## 8. Performance budget and rules

**Measured baseline.**
- Desktop: Python 3.14, pygame-ce 2.5.8, dummy SDL. Another session was running at the time, so the numbers are noisy.
  - The original flat renderer (tech lens): walls 2.8 ms; 12 robots 5.2 ms; one full-screen SRCALPHA overlay 1.1 ms.
  - The current reskin: walls 5-6 ms (per-column texture scale plus reflection); 10 sprites in view 16 ms (per-frame smoothscale and multiply of 1000-1500 px PNGs); `draw_hud` 3.2 ms (per-call SRCALPHA panels, a scrim built from 112 lines every frame, and the minimap rebuilt).
- Browser CPython is about 3-5x slower, so the reskin as it stands runs at roughly 10-15 fps in the browser.
- **Target:** 30 fps in the browser (33 ms).

| System | Desktop p95 target | Browser estimate |
|---|---|---|
| Walls (320 rays, textured with the fix) + scale to 1024 | 3.5 ms | ~12 ms |
| Sprites (at most 12 cached) + segments (at most 4) + orbs (at most 104) + rings | 1.5 ms | ~5 ms |
| Simulation: hero, 12 enemies, 40 projectiles, 64 particles, flow, 8 LOS | 1.0 ms | ~4 ms |
| HUD, viewmodel and overlays | 1.5 ms | ~5 ms |
| flip | ~0.5 ms | ~3 ms |
| **Total** | **p95 <= 9 ms (fail above 12)** | **about 29 ms** |

**Rules** (reviewers reject violations):
1. **No large per-frame surfaces.** Never allocate a surface larger than 64x64 per frame in any draw or update path. Full-screen and panel overlays are built once (lazily after `set_mode`) and reused, through `set_alpha`, or through a `BLEND_RGB_ADD` or `BLEND_RGB_MULT` fill or blit.
2. **Cheap tints.** Use `surf.fill(color, rect, special_flags=pygame.BLEND_RGB_ADD)` (about 0.07 ms), never an alpha surface (about 1.1 ms).
3. **Cached text.** All text goes through `core.text()`. Never call `font.render` directly in per-frame code.
4. **Sprites only via painters and the render cache.** No per-column `draw.line` sprites, and no runtime smoothscale. PNG assets are smoothscaled once at load, to their painter base size.
5. **Caps.**
   - enemies alive 10 (+2 summons); projectiles 40; particles 64; effects 24; barriers 4;
   - kill feed 5; pop-ups 3; damage arcs 4;
   - sprite cache 160; text cache 512;
   - LOS 8 per frame (through `los_budgeted`); each enemy re-checks LOS at most 5 times a second.
6. **Flow field.** Rebuilt only when the player's cell changes (about 0.11 ms).
7. **O(n^2)** is allowed only for enemy separation (n <= 12).
8. **Hitscan cost.** Each trace is 1 `cast_ray` plus n enemies plus barriers. FLICKER's 20/s is fine.
9. **Sound.** Synthesise at most 1 sound per frame, only after the first input.
10. **Minimap.** Walls pre-drawn once; per frame, only the dots.
11. **Menus.** Screens cache their static layers. The rain streaks (26 lines) are fine.
12. **Harness check.** The harness wraps `pygame.Surface` in a counting subclass. In the perf scenario, after 60 warm-up frames, surfaces of 256x256 or larger must total <= 5 over 300 frames.
13. **Emergency lever** (integrator only): `COLS` 320 → 240, if browser frames stay above 40 ms.

---

## 9. Test plan

### 9.1 Harness: `tools/smoke.py` (FOUNDATION)

- **Location.** `tools/` is outside `game/`, so neither packer ships it.
- **Setup.**
  - Set `SDL_VIDEODRIVER=dummy` and `SDL_AUDIODRIVER=dummy`.
  - Insert `game/` into `sys.path` and import `rwf.app`. Never import `main.py`, because it runs the game on import.
  - Run with `python -X utf8`.
- **Command line:**

```
python tools/smoke.py --suite foundation|campaign|perf|vector|flicker|rampart|enemies|hud|all [--shots] [--no-assets]
```

- **Exit status.** The exit code is non-zero on any failure. The harness prints `PASS` or `FAIL <suite>: <message>` per check, and writes PNGs to `tools/out/` when `--shots` is given.

**API** (check modules use only this):

```python
class Harness:
    def run(self, hero='vector', frames=600, *, timeline=(), debug=None, setup=None, on_frame=None,
            seed=1, shots=(), name='run') -> Result
        # defaults: debug = {'god': True, 'skip_countdown': True, 'no_director': True} merged with the argument;
        # fixed_dt = 1/30. The player is placed at (2.5, 7.5), angle 0 (east), pitch 0, in the open row y = 7.5.
    def spawn(self, world, kind, fwd, side=0.0, **attrs) -> 'Enemy'   # relative to the player's facing
    def place(self, world, x, y, angle=0.0, pitch=0.0) -> None
class Result:
    world; events: list[tuple[int, str, dict]]; exception: str | None; frame_ms: list[float]; states: list[str]
    def count(self, name, **match) -> int      # match values: plain (==) or callables
    def first(self, name, **match); def total(self, name, key, **match) -> float
# Timeline entries:
#   ('tap', frame, action)                  press at frame, release at frame + 1
#   ('hold', frame, action, n_frames)
#   ('look', frame, dx, dy)                 one MOUSEMOTION with rel = (dx, dy)
#   ('aim', frame, angle, pitch)            set hero.angle / pitch directly (for exact aim)
#   ('call', frame, fn)                     fn(world)
# Actions become real pygame events (the first key in KEYMAP, or the mouse button) fed through input_source.
```

**Invariants** checked every frame of every run (they fail the suite):
- no exception;
- no NaN in any x, y, angle or pool value;
- the player and every alive enemy are outside walls;
- every cap in rule 5 is respected;
- `0 <= ult_charge <= ULT_COST`;
- `0 <= pool values <= max`;
- `0 <= ammo <= MAX_AMMO`;
- `hero.hud_state(world)` returns a HeroHUD with 2-3 abilities.

### 9.2 FOUNDATION acceptance (`check_foundation.py`, `check_campaign.py`, `check_perf.py`)

1. **Static checks** (section 9.5).
2. **Pool math:** the 5.3 test vectors, heal order, and shield regen timing (no regen at 2.9 s, regen at 3.1 s).
3. **Hitscan geometry:** the 5.4 cases with a dummy; barrier hits return `kind == 'barrier'`; wall hits.
4. **Projectiles and barriers:** an enemy bolt into a player-team barrier gives `barrier_damage` and no `player_hurt`. A projectile at 16 cells/s doesn't tunnel through a 0.22-radius dummy at 30 fps.
5. **Flow field:** a path from (1.5, 1.5) to (18.5, 18.5) exists. `toward()` never points into a wall for any open cell.
6. **Clock and pause:** with `pause` tapped, 60 frames leave `world.now` unchanged and enemies don't move. A click resumes. `time.time` is never called (monkeypatched to raise).
7. **Registries and stubs:**
   - `core.HEROES` has 3 keys and `ENEMY_TYPES` has all 5 kinds plus `dummy`;
   - each registered painter draws every state;
   - each Screen class draws once;
   - the generic hero contract (9.3, step 1) passes for all 3 stub heroes.
8. **Screen flow:** COUNTDOWN → PLAYING → forced death (`kill_player_at`) → END_BANNER → POTG (or skipped) → SUMMARY, driven by scripted Enter presses. `result.states` contains each of them.
9. **`--no-assets`:** the whole foundation suite passes with `RWF_NO_ASSETS=1`.
10. **Packer:** the static check confirms that `tools/build_web.py` globs `rwf`.
11. **Campaign** (`check_campaign.py`): god mode plus `autokill: 2.0` and `auto_capture`, running waves 1 to 10.
    - `wave_start` fires in order 1-10 with the kinds from 4.6.
    - Waves 5 and 10 each have a `boss_spawn`.
    - `stage_clear` fires twice.
    - Pressing `hero2` during the intermission swaps to FLICKER with ult fraction <= 0.30.
    - Then death, POTG for 60 frames, and the summary renders.
12. **Perf** (`check_perf.py`):
    - Setup: god mode; 10 dummies (or real enemies once available) at 3-8 cells in view; 30 enemy bolts; 2 enemy barriers; 40 particles; full kill feed.
    - 60 warm-up frames, then 300 measured frames.
    - Report p50/p95 for update, render, hud and total. Warn above 9 ms, fail above 12 ms.
    - Apply the surface-allocation rule (rule 12).

### 9.3 Hero acceptance (HERO_A `check_vector.py`, HERO_B `check_flicker.py`, HERO_C `check_rampart.py`)

**1. Generic contract** (the helper `h.hero_contract(key)` is provided by FOUNDATION).
- 900 frames, `inf_ult` on, 3 dummies at 4 cells ahead (side offsets -0.6, 0 and 0.6).
- Timeline: hold fire for 60 frames, tap or hold alt, tap ab1 and ab2, look sweeps, tap ult at frame 400, tap reload, tap melee.
- **Pass requires:**
  - `ability_used` for `primary`, `melee` and every key in `hero.abilities`;
  - an action on alt (`ability_used` from any slot, or a barrier raised);
  - at least 1 `damage` with the hero as source;
  - `ult_used` at least once;
  - no exceptions;
  - `draw_viewmodel`, `draw_overlay`, `draw_crosshair` and `draw_icon` (every slot, into 52x52 and 96x96) run without error.

**2. Hero-specific checks.** Use dummies (with `pool` set to a `HealthPool` of 1000 health) and `no_director`.

| Hero | Check | Pass condition |
|---|---|---|
| VECTOR | Rifle | Aim at a dummy 4 ahead (body) and hold fire for 1.0 s: damage 150-190. Hold for 4.0 s: at least 30 `shot` events and a reload. |
| VECTOR | Helix | 2 dummies 0.8 apart at 5 cells, tap alt: both damaged; the centre one takes at least 110. The cooldown blocks a second rocket within 6 s. |
| VECTOR | Sprint | Tap ab1 and hold fwd for 1.0 s: moved at least 5.5 cells. Tap fire: speed back to 4.2 within one frame. |
| VECTOR | Heal Field | Player health set to 100, tap ab2, wait 2.0 s: health at least 175, `heal` events with ability `ab2`, and ult charge rises by the amount healed (with `inf_ult` off). |
| VECTOR | Lock-On | 3 dummies at +-20 deg, aim at an empty wall, tap ult and hold fire for 1.0 s: at least 6 `damage` events on the dummies, and ammo unchanged. |
| FLICKER | Falloff | Dummy at 3 cells: 12 per body hit. At 9 cells: 6.6-7.2. |
| FLICKER | Blink | In the open row: moves 3.5 +- 0.1. Facing the east wall from (17.5, 7.5): ends with x <= 18.75 and never in a wall. Charges 3 → 0; 1 charge back after 3.0 s. |
| FLICKER | Rewind | Record position P at t. Move 3 cells and take 80 damage over 2.9 s (`god` off, dummy `fire_every`). Tap ab2 at t + 3.0. After 0.5 s: within 0.4 of P, health >= health at t, no damage taken during the travel, and ammo = 40. |
| FLICKER | Pulse Bomb | Dummy at 4 cells, tap ult: it sticks, and 1.0-1.1 s later the dummy takes 350. A second dummy 1.5 away takes 190-240. |
| RAMPART | Hammer | 3 dummies at 2 cells within +-40 deg all take 80 per swing. A dummy behind (180 deg) takes 0. At most 1 swing per 0.9 s. |
| RAMPART | Barrier | Dummy with `fire_every: 0.5` at 5 cells, hold alt for 3 s: `barrier_damage` events and player health unchanged. Lowered for 2.5 s: HP regenerating. Broken (set hp to 1, one bolt): a 5 s lockout. |
| RAMPART | Charge | Player at (8.5, 7.5) facing east, dummy at (11.5, 7.5), tap ab1: `damage` of 225 on the dummy within 1.5 s, and the charge has ended. From open space with no target: ends within 1.5 s, never in a wall. |
| RAMPART | Flame Strike | 2 dummies in a line behind an enemy barrier (spawn a Barrier with `TEAM_ENEMY`): both take 90. 2 charges. |
| RAMPART | Quake | 3 dummies inside the cone within 8 cells take 120 each and have `stun` for 2.5 s; a dummy behind a wall isn't hit; RAMPART is rooted for 0.6 s. |

### 9.4 ENEMIES acceptance (`check_enemies.py`) and HUD_UX acceptance (`check_hud.py`)

**ENEMIES**

Setup for every kind: `no_director`, `god`, the player at (2.5, 7.5) facing east, one enemy spawned at (7.5, 7.5), 600 frames with a passive player.

| Kind | Pass condition |
|---|---|
| trooper | At least 1 enemy projectile spawned; `player_hurt` within 10 s; mean distance to the player over the last 5 s between 3 and 8. |
| slicer | Enters `windup`, then `lunge` (`vstate` sampled each frame); lunge displacement at least 2.0 within 0.4 s; `player_hurt` at least 1. |
| detonator | `explosion` and `player_hurt` when near the player. Killed at 5 cells with a trooper 1.0 away: the trooper takes at least 100, and any resulting `kill` has the player as source. |
| eradicator | An enemy-team barrier exists within 3 s of having LOS. A player hitscan from the front gives `Hit.kind == 'barrier'`. With the player placed behind it, the result is `'enemy'`. |
| warden | Recon bolts fire. `vstate == 'sentry_windup'` at least 0.8 s before the first sentry bolt, within 13 s. Damage to 49% gives `boss_phase` and 2 slicers with `summon=True`. Player within 2 cells: `slow` status after the stomp. |
| all kinds | Dies after 10000 damage (`kill` event; score up by SCORE x stage). Stun for 2 s gives zero displacement. The painter draws every state, with and without assets. No NaN and never in a wall. |

- **Waves:** the campaign run (9.2, item 11) must still pass with the real director. Also:
  - alive enemies never exceed 10 (12 with summons);
  - the capture wave reaches `captured` with `auto_capture`, and the remaining enemies die with no score;
  - letting the timer expire outside the point gives `failed`.
- **Elites:** stage 2 has at least 1 elite across waves 6-9 with seed 1.

**HUD_UX**
- The HUD draws for each hero over 120 frames of synthetic events: 6 kills gives a kill feed of at most 5 rows, 5 eliminations give at most 3 pop-ups, and there are hitmarker variants, arcs, low-HP, objective states (every state) and the boss bar.
- Every Screen draws.
- The summary medals come out right for a synthetic `MatchStats`: elims/min of 7 gives a silver ELIMINATIONS.
- `rank(2000) == 'A'`.
- POTG: after at least 7 s of recording, a synthetic 3-kill burst makes `best()` return 120 frames, and `PotgScreen` plays 60 of them.
- `sfx.init()` under the dummy audio driver doesn't raise, and `play('unknown')` is a no-op.
- HUD draw p95 is at most 1.5 ms over 300 frames with a full feed.
- PNGs of the HUD and every screen are saved with `--shots`.

### 9.5 Static checks (run in the foundation suite; they apply to every builder)

1. Every `game/**/*.py` file is pure ASCII: no non-ASCII bytes in code, comments or strings.
2. `ast.parse(src, feature_version=(3, 12))` succeeds. The browser runs CPython 3.12, while the desktop runs 3.14, so avoid 3.13+ syntax such as `except A, B:` without parentheses.
3. **Forbidden:**
   - `import numpy`, `threading`, `subprocess`, `time.sleep`;
   - `time.time(` anywhere under `rwf/`;
   - `K_TAB`, `K_F<n>`, `K_LCTRL`, `K_RCTRL`, `K_LALT`, `K_RALT`, `K_LMETA`, `K_RMETA`, `K_LGUI`, `K_RGUI`;
   - `KMOD_` in key handling;
   - `pygame.mouse.get_pressed`.
4. Every `async def` that contains a `while` loop also contains `await asyncio.sleep(0)`.
5. `game/` contains only `main.py`, `favicon.png`, `assets/` and `rwf/` (plus the ignored `build/`), and no module named `platform.py` or `config.py` at the `game/` top level.
6. `tools/build_web.py` references `rwf`.

### 9.6 Integrator checklist

1. `python tools/smoke.py --suite all --shots` passes, and so does the `--no-assets` run.
2. `--suite perf`: p95 at most 9 ms. Record the numbers in the integration report.
3. `python -m pygbag --build game` succeeds, and the build archive contains `rwf/*.py`.
4. Manual desktop play (`게임실행.bat`), 5 minutes per hero. Watch the debug overlay's ult-ready log against the targets:
   - median time between ults: FLICKER about 40 s, RAMPART about 55 s, VECTOR about 60 s;
   - at least 1 ult per wave from wave 3 on;
   - wave length 30-60 s;
   - WARDEN fight 25-40 s.
   Adjust `ULT_COST` by +-10% and enemy damage by +-15% only.
5. Review the CORE REQUESTs.
6. Merge any theme or presentation changes made to the old `main.py` by the concurrent session after FOUNDATION's snapshot.
7. Don't deploy (copy to the repo root, commit or push) without the user's go-ahead.

---

## 10. Integration notes (appended by the integrator; details in design/INTEGRATION_REPORT.md)

- Retuned with the 9.6 levers after the autoplay balance runs (`tools/autoplay.py`): `ULT_COST` +10% (VECTOR 1650,
  FLICKER 1210, RAMPART 1540) and enemy damage to the player -15% (`enemies.TUNING['player_damage_scale'] = 0.85`;
  enemy-on-enemy blasts unscaled). All other numbers in this file are unchanged.
- Core additions from the CORE REQUESTs: `Barrier(edge=, color_hit=, edge_hit=, color_low=, edge_low=, z1=)` drawn by
  the renderer with a hit flash / low-HP tint / near-camera fade; `Enemy.fire_bolt(..., ability=, core=, size=, z=)`;
  `combat.player_barrier_between()`; `sfx` 'variant' field (`rewind`, `hammer_low`) plus a `heal` sound; reloads no
  longer count the dt of the frame they start in; harness `h.spawn_at()`.
- Open balance items that need a spec decision (not tunable with the allowed levers): ult charge is 1.5-3x faster
  than the 9.6 targets because assault waves last 14-36 s instead of 30-60 s; Pulse Bomb / Quake damage feeds the next
  ult; FLICKER is fragile and RAMPART dominant; capture waves resolve in about 14 s.
