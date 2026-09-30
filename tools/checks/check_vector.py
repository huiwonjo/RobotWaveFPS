"""HERO_A acceptance: VECTOR (spec 9.3 step 1 + the VECTOR rows of the 9.3 table, plus the 3.1 rules).

    python -X utf8 tools/smoke.py --suite vector [--shots] [--no-assets]

Every run uses the harness defaults (god, skip_countdown, no_director) unless a check says otherwise;
fixed dt = 1/30, so 30 frames = 1.0 s. Dummies get a HealthPool of 1000 health (spec 9.3).
Speeds per frame: walk 4.2 / 30 = 0.14 cells, sprint 6.3 / 30 = 0.21 cells.
"""
import math
import time

DT = 1.0 / 30.0
WALK = 4.2 * DT
SPRINT = 6.3 * DT


def _dummy(h, w, fwd, side=0.0, hp=1000.0, **attrs):
    from rwf.combat import HealthPool
    e = h.spawn(w, 'dummy', fwd, side, **attrs)
    e.pool = HealthPool(hp)
    return e


def _dummy_at(w, x, y, hp=1000.0):
    from rwf.combat import HealthPool
    e = w.spawn_enemy('dummy', x, y)
    e.pool = HealthPool(hp)
    return e


def _dealt(r, target, **match):
    return r.total('damage', 'amount', target=lambda t: t is target, **match)


def _hits_on(r, target, **match):
    return r.where('damage', target=lambda t: t is target, **match)


# ============================================================================ contract / attributes
def check_vector_contract(h):
    """9.3 step 1: the generic hero contract."""
    return h.hero_contract('vector')


def check_vector_attrs(h):
    """3.4 attributes, 3.1 numbers in TUNING, ability slots / cooldowns / key labels."""
    from rwf import core, hero_vector as V
    c = core.HEROES['vector']
    got = (c.KEY, c.NAME, c.ROLE, c.DIFFICULTY, c.COLOR, c.HEALTH, c.ARMOR, c.SHIELDS, c.SPEED, c.ULT_COST,
           c.ULT_NAME, c.ULT_CALLOUT, c.ULT_DURATION, c.MAX_AMMO, c.RELOAD_TIME, c.HUD_ORDER)
    want = ('vector', 'VECTOR', 'DAMAGE', 1, (80, 150, 255), 200, 0, 0, 4.2, 1500, 'LOCK-ON', 'LOCKED ON!', 6.0,
            30, 1.5, ('ab1', 'ab2', 'secondary'))
    assert got == want, 'class attrs %r' % (got,)
    assert c.BLURB == 'Versatile rifleman. Rockets, sprint, self-heal.', c.BLURB
    assert [(k, n) for k, n, _ in c.KIT] == [('LMB', 'PULSE RIFLE'), ('RMB/F', 'HELIX ROCKETS'), ('SHIFT', 'SPRINT'),
                                            ('E', 'HEAL FIELD'), ('Q', 'LOCK-ON')], c.KIT
    lab = {k: c.LABELS.get(k) for k in ('primary', 'secondary', 'ult', 'melee')}
    assert lab == {'primary': 'PULSE RIFLE', 'secondary': 'HELIX', 'ult': 'LOCK-ON', 'melee': 'MELEE'}, lab
    t = V.TUNING
    nums = {'rifle_damage': 19.0, 'rifle_interval': 0.111, 'rifle_exact_shots': 3, 'spread_step_deg': 0.3,
            'spread_max_deg': 1.5, 'burst_reset': 0.3, 'helix_direct': 40.0, 'helix_center': 80.0,
            'helix_edge': 40.0, 'helix_radius': 1.5, 'helix_speed': 16.0, 'helix_proj_radius': 0.2,
            'helix_cd': 6.0, 'helix_knockback': 0.4, 'sprint_mult': 1.5, 'heal_rate': 40.0, 'heal_time': 5.0,
            'heal_radius': 2.5, 'heal_cd': 15.0, 'lockon_time': 6.0, 'lockon_damage': 19.0}
    bad = {k: (t.get(k), v) for k, v in nums.items() if t.get(k) != v}
    assert not bad, 'TUNING differs from spec 3.1: %r' % bad
    # spread schedule: 3 exact shots, then +0.3 deg per shot up to 1.5 deg (0.026 rad)
    sp = [round(math.degrees(V.spread_for(i)), 6) for i in range(10)]
    assert sp == [0, 0, 0, 0.3, 0.6, 0.9, 1.2, 1.5, 1.5, 1.5], sp
    assert abs(V.spread_for(20) - 0.02618) < 1e-4
    w = h.make_world('vector')
    ab = w.player.abilities
    assert sorted(ab) == ['ab1', 'ab2', 'secondary'], sorted(ab)
    rows = {k: (a.name, a.key_label, a.cooldown, a.max_charges) for k, a in ab.items()}
    assert rows == {'secondary': ('HELIX ROCKETS', 'RMB', 6.0, 1), 'ab1': ('SPRINT', 'SHIFT', 0.0, 1),
                    'ab2': ('HEAL FIELD', 'E', 15.0, 1)}, rows
    hs = w.player.hud_state(w)
    assert [a.slot for a in hs.abilities] == ['ab1', 'ab2', 'secondary'] and hs.max_ammo == 30


# ============================================================================ PULSE RIFLE
def check_vector_rifle(h):
    """9.3: dummy 4 ahead (body), hold fire 1.0 s: damage 150-190. Hold 4.0 s: >= 30 shots and a reload."""
    rec = {}
    pitch = (0.35 - 0.5) * 768 / 4.0        # the middle of the 0.70-tall body at 4 cells

    def setup(w):
        rec['d'] = _dummy(h, w, 4.0)
    r = h.run('vector', 60, timeline=[('aim', 5, 0.0, pitch), ('hold', 10, 'fire', 30)], setup=setup,
              name='vector_rifle_1s')
    d = rec['d']
    dmg = _dealt(r, d)
    shots = r.count('shot', hero='vector')
    assert 150 <= dmg <= 190, 'hold 1.0 s on a body: damage %.1f not in 150-190 (%d shots)' % (dmg, shots)
    assert shots == 9, '9 shots/s: got %d shots in 1.0 s' % shots
    hits = _hits_on(r, d)
    assert all(abs(x['amount'] - 19.0) < 1e-9 and not x['crit'] and x['ability'] == 'primary' for x in hits), \
        'body shots must deal 19, no crit'
    assert r.count('ability_used', hero='vector', slot='primary') == shots, 'ability_used primary per shot'
    note = 'dmg %.0f in 1 s (%d shots)' % (dmg, shots)

    # hold 4.0 s: 30 shots empty the mag at ~3.2 s, the held trigger starts the 1.5 s reload by itself
    st = {'reload_frames': [], 'ammo': {}}

    def on_frame(w, i, s):
        if w.player.reloading:
            st['reload_frames'].append(i)
        st['ammo'][i] = w.player.ammo
    r = h.run('vector', 200, timeline=[('aim', 5, 0.0, pitch), ('hold', 10, 'fire', 120)], setup=setup,
              on_frame=on_frame, name='vector_rifle_4s')
    shots = r.count('shot', hero='vector')
    assert shots >= 30, 'hold 4.0 s: %d shots (need >= 30)' % shots
    assert st['reload_frames'], 'hold 4.0 s: no reload started'
    rf = st['reload_frames']
    assert shots == 30, 'no shot may fire during the reload (got %d shots)' % shots
    # the reload starts in handle_input and starts ticking on the next frame (integration: the start frame's
    # dt no longer counts): 45 ticks of 1/30 s = 1.5 s, so 45 frames end with reloading True (44/46 allow
    # for float rounding)
    assert rf[-1] - rf[0] + 1 in (44, 45, 46), 'reload lasted %d frames, want 1.5 s' % (rf[-1] - rf[0] + 1)
    assert st['ammo'][rf[-1] + 1] == 30, 'mag not refilled after the reload'
    return note + '; 4 s: %d shots, reload frames %d-%d' % (shots, rf[0], rf[-1])


def check_vector_rifle_spread(h):
    """3.1: shots 1-3 of a burst are exact, then +0.3 deg per shot up to 1.5 deg; the burst resets 0.3 s
    after the last shot. Fired along the open row y = 7.5 into the east wall (x = 19, 16.5 cells)."""
    tl = [('hold', 10, 'fire', 30), ('hold', 52, 'fire', 12), ('hold', 69, 'fire', 7)]
    r = h.run('vector', 90, timeline=tl, name='vector_spread')
    ev = [(f, d) for f, n, d in r.events if n == 'shot']
    first = [d for f, d in ev if 10 <= f < 40]
    second = [d for f, d in ev if 52 <= f < 64]       # after 12 idle frames (0.4 s): a new burst
    third = [d for f, d in ev if 69 <= f < 76]        # after 5 idle frames (0.17 s): the same burst
    assert len(first) == 9, '9 shots in 1.0 s, got %d' % len(first)
    dys = [abs(d['y'] - 7.5) for d in first]
    assert max(dys[:3]) < 1e-9, 'first 3 shots not exact: %r' % dys[:3]
    for k, dy in enumerate(dys[3:], start=3):
        lim = math.tan(math.radians(min(1.5, 0.3 * (k - 2)))) * 16.6 + 1e-6
        assert dy <= lim, 'shot %d off by %.3f > %.3f' % (k + 1, dy, lim)
    assert max(dys[3:]) > 1e-6, 'no spread after the 3rd shot'
    assert len(second) >= 3 and max(abs(d['y'] - 7.5) for d in second[:3]) < 1e-9, \
        'burst did not reset after 0.4 s idle'
    assert third and abs(third[0]['y'] - 7.5) > 1e-9, 'burst reset after only 0.17 s idle'
    # crosshair circle radius 10 + spread x 400
    from rwf import hero_vector as V
    p = r.world.player
    assert abs(p.spread_now(p._last_shot) - V.spread_for(p._burst - 1)) < 1e-12
    return 'max offsets %s' % ', '.join('%.3f' % x for x in dys)


def check_vector_rifle_crit_reload(h):
    """5.4 geometry: pitch +20 px at 5 cells is a crit (38). R with a full mag is a no-op; R at 20 ammo
    reloads for 1.5 s, and the held trigger fires nothing until the mag is full."""
    rec = {}

    def setup(w):
        rec['d'] = _dummy(h, w, 5.0)

    def on_frame(w, i, s):
        rec.setdefault('rel', {})[i] = (w.player.reloading, w.player.ammo)
    tl = [('aim', 5, 0.0, 20.0), ('tap', 8, 'reload'), ('tap', 10, 'fire'),
          ('call', 30, lambda w: setattr(w.player, 'ammo', 20)), ('tap', 31, 'reload'), ('hold', 33, 'fire', 60)]
    r = h.run('vector', 100, timeline=tl, setup=setup, on_frame=on_frame, name='vector_crit_reload')
    hits = _hits_on(r, rec['d'])
    assert hits and hits[0]['crit'] and abs(hits[0]['amount'] - 38.0) < 1e-9, 'head shot: %r' % (hits[:1],)
    rel = rec['rel']
    assert rel[8][0] is False and rel[8][1] == 30, 'R with a full mag started a reload'
    assert rel[31][0] and rel[31][1] == 20, 'R at 20 ammo did not reload'
    ends = [i for i in range(32, 100) if not rel[i][0]]
    assert ends and ends[0] - 31 in (44, 45, 46), 'reload of %s frames, want 45' % (ends[0] - 31 if ends else '?')
    shot_frames = [f for f in r.frames_of('shot') if f > 11]
    assert shot_frames and shot_frames[0] >= ends[0], 'fired during the reload (frame %d)' % shot_frames[0]
    return 'crit %.0f, reload %d frames' % (hits[0]['amount'], ends[0] - 31)


# ============================================================================ HELIX ROCKETS
def check_vector_helix(h):
    """9.3: 2 dummies 0.8 apart at 5 cells, tap alt: both damaged, the centre one takes >= 110 (40 + 80 = 120);
    the 6 s cooldown blocks a second rocket. Knockback 0.4 on the splashed dummies."""
    rec = {}

    def setup(w):
        h.place(w, *h.ROOMY)
        rec['c'] = _dummy(h, w, 5.0, 0.0)
        rec['s'] = _dummy(h, w, 5.0, 0.8)
        rec['s0'] = (rec['s'].x, rec['s'].y)

    def on_frame(w, i, s):
        if i == 40:
            rec['s40'] = (rec['s'].x, rec['s'].y)
            rec['proj40'] = len(w.projectiles)
    tl = [('tap', 5, 'alt'), ('tap', 95, 'alt'), ('tap', 188, 'alt')]
    r = h.run('vector', 240, timeline=tl, setup=setup, on_frame=on_frame, name='vector_helix',
              shots=(12, 13, 14))
    c, s = rec['c'], rec['s']
    first_c = sum(d['amount'] for f, n, d in r.events if n == 'damage' and d['target'] is c and f < 90)
    first_s = sum(d['amount'] for f, n, d in r.events if n == 'damage' and d['target'] is s and f < 90)
    assert first_c >= 110, 'centre dummy took %.1f (need >= 110)' % first_c
    assert abs(first_c - 120.0) < 1e-6, 'direct hit should be 40 + 80 = 120 (got %.1f)' % first_c
    assert first_s > 0, 'side dummy 0.8 away took no splash'
    assert 40.0 <= first_s <= 80.0, 'splash %.1f outside 40-80' % first_s
    me = r.world.player
    assert all(d['ability'] == 'secondary' and not d['crit'] for d in r.where('damage', source=lambda x: x is me))
    used = r.frames_of('ability_used', slot='secondary')
    assert used[:1] == [5] and not [f for f in used if 6 <= f < 188], 'cooldown did not block: %r' % used
    assert 188 in used, 'rocket not available again after 6 s (%r)' % used
    assert r.count('sfx', name='rocket') == len(used)
    kb = math.hypot(rec['s40'][0] - rec['s0'][0], rec['s40'][1] - rec['s0'][1])
    assert kb >= 0.3, 'splashed dummy knocked back only %.2f' % kb
    assert r.count('explosion', team=0) >= 2
    return 'direct %.0f, splash %.1f at 0.8, knockback %.2f, rockets at frames %r' % (first_c, first_s, kb, used)


def check_vector_helix_barrier_self(h):
    """An enemy barrier takes direct + splash (120) and shields what is behind it; the rocket gives ult at
    0.5 per barrier HP. No self-damage from a rocket fired into a wall 0.6 away."""
    from rwf import combat
    from rwf.config import TEAM_ENEMY
    rec = {}

    def setup(w):
        b = combat.Barrier(TEAM_ENEMY, 400, 1.0)
        b.set_pose(w.player.x + 2.5, w.player.y, math.pi)
        w.add_barrier(b)
        rec['b'] = b
        rec['d'] = _dummy(h, w, 3.7)
    r = h.run('vector', 40, timeline=[('tap', 5, 'alt')], setup=setup, name='vector_helix_barrier')
    b = rec['b']
    bd = r.total('barrier_damage', 'amount')
    assert abs(bd - 120.0) < 1e-6 and abs(b.hp - 280.0) < 1e-6, 'barrier took %.1f (hp %.1f), want 120' % (bd, b.hp)
    assert _dealt(r, rec['d']) == 0, 'dummy behind the barrier was hit'
    assert r.count('explosion') == 1
    ult = r.world.player.ult_charge
    assert abs(ult - 60.0) < 1e-6, 'ult from barrier damage %.1f, want 60' % ult

    def setup2(w):
        h.place(w, 1.6, 7.5, math.pi)
    r = h.run('vector', 30, timeline=[('tap', 5, 'alt')], setup=setup2, debug={'god': False}, name='vector_helix_self')
    p = r.world.player
    assert r.count('explosion') == 1, 'rocket did not explode on the wall'
    assert r.count('player_hurt') == 0 and p.pool.health == 200, 'self-damage (health %.1f)' % p.pool.health
    return 'barrier hp 400 -> %.0f, ult %.0f; no self-damage' % (b.hp, 60.0)


def check_vector_helix_splash_rules(h):
    """Splash falls linearly 80 -> 40 over r 1.5, needs LOS from the blast point, and knocks back 0.4.
    Blast at (9.5, 7.05) under wall cell (9, 6): a dummy 1.4 away behind that wall takes nothing."""
    from rwf import hero_vector as V
    w = h.make_world('vector')
    hidden = _dummy_at(w, 9.5, 5.65)
    seen = _dummy_at(w, 10.9, 7.3)
    far = _dummy_at(w, 9.5 - 1.6, 7.5)
    x0, y0 = seen.x, seen.y
    hit = V.helix_blast(w, w.player, 9.5, 7.05)
    d = math.hypot(x0 - 9.5, y0 - 7.05)
    want = 80.0 - 40.0 * d / 1.5
    got = 1000.0 - seen.pool.health
    assert hidden not in hit and hidden.pool.health == 1000.0, 'splash went through a wall'
    assert far not in hit and far.pool.health == 1000.0, 'splash reached past r 1.5'
    assert abs(got - want) < 1e-6, 'splash at %.2f: %.2f, want %.2f' % (d, got, want)
    moved = math.hypot(seen.x - x0, seen.y - y0)
    assert abs(moved - 0.4) < 0.02, 'knockback %.3f, want 0.4' % moved
    assert any(isinstance(e, V.BlastRing) for e in w.effects), 'no ring flash'
    assert w.cam.shake_amp >= 4 and len(w.particles) >= 14
    return 'splash %.1f at %.2f cells, knockback %.2f' % (got, d, moved)


# ============================================================================ SPRINT
def check_vector_sprint(h):
    """9.3: tap ab1 and hold fwd for 1.0 s: moved >= 5.5 cells. Tap fire: speed back to 4.2 within one frame."""
    xs = {}
    act = {}

    def on_frame(w, i, s):
        xs[i] = w.player.x
        act[i] = w.player.hud_state(w).abilities[0].active
    tl = [('tap', 10, 'ab1'), ('hold', 10, 'fwd', 60), ('tap', 50, 'fire')]
    r = h.run('vector', 80, timeline=tl, on_frame=on_frame, name='vector_sprint', shots=(30,))
    moved = xs[39] - xs[9]
    assert moved >= 5.5, 'sprint 1.0 s moved %.2f cells (need >= 5.5)' % moved
    assert abs((xs[30] - xs[29]) - SPRINT) < 1e-6, 'sprint speed %.4f/frame' % (xs[30] - xs[29])
    assert act[30] and not act[5], 'the SHIFT tile must show active while sprinting'
    assert abs((xs[50] - xs[49]) - WALK) < 1e-6, 'fire: speed %.4f/frame on the fire frame, want %.4f' % (
        xs[50] - xs[49], WALK)
    assert not act[51], 'sprint still latched after fire'
    assert 50 in r.frames_of('shot'), 'the fire tap that ended the sprint did not shoot'
    assert r.count('ability_used', slot='ab1') == 1
    return 'moved %.2f in 1.0 s' % moved


def check_vector_sprint_latch(h):
    """3.1 latch rules: W release, Shift again, RMB, E, V and Q end it; a latch pressed before W starts the
    sprint when W goes down; starting to sprint cancels a reload."""
    st = {}

    def on_frame(w, i, s):
        st[i] = (w.player.x, w.player.sprinting, w.player._latched, w.player.reloading, w.player.ammo)

    def spd(i):
        return abs(st[i][0] - st[i - 1][0])
    tl = [('tap', 10, 'ab1'), ('hold', 10, 'fwd', 15),                        # W release
          ('hold', 30, 'fwd', 10),                                           # no latch any more
          ('tap', 45, 'ab1'), ('hold', 50, 'fwd', 20), ('tap', 60, 'ab1'),     # armed latch; Shift again
          ('tap', 75, 'ab1'), ('hold', 75, 'fwd', 25), ('tap', 85, 'alt'),     # RMB
          ('aim', 102, math.pi, 0.0),
          ('tap', 105, 'ab1'), ('hold', 105, 'fwd', 20), ('tap', 110, 'ab2'),  # E
          ('tap', 130, 'ab1'), ('hold', 130, 'fwd', 20), ('tap', 135, 'melee'),  # V
          ('tap', 155, 'ab1'), ('hold', 155, 'fwd', 12), ('tap', 160, 'ult')]   # Q (ult not ready)
    h.run('vector', 175, timeline=tl, on_frame=on_frame, name='vector_latch')
    assert abs(spd(20) - SPRINT) < 1e-6 and not st[25][1] and not st[25][2], 'W release must end the sprint'
    assert abs(spd(35) - WALK) < 1e-6, 'walking after the W release is not normal speed'
    assert st[46][2] and not st[46][1], 'a latch pressed before W must wait for W (armed)'
    assert abs(spd(55) - SPRINT) < 1e-6, 'armed latch did not sprint when W went down'
    assert not st[60][2] and abs(spd(61) - WALK) < 1e-6, 'Shift again must end the sprint'
    for f, what in ((85, 'RMB'), (110, 'E'), (135, 'V'), (160, 'Q')):
        assert abs(spd(f - 2) - SPRINT) < 1e-6, 'no sprint before the %s test' % what
        assert not st[f][2] and abs(spd(f) - WALK) < 1e-6, '%s did not end the sprint' % what

    def ammo10(w):
        w.player.ammo = 10
    st.clear()
    tl = [('call', 5, ammo10), ('tap', 10, 'reload'), ('tap', 15, 'ab1'), ('hold', 15, 'fwd', 10)]
    h.run('vector', 70, timeline=tl, on_frame=on_frame, name='vector_sprint_reload')
    assert st[10][3] and st[14][3], 'reload did not start'
    assert not st[15][3] and st[15][4] == 10, 'starting a sprint must cancel the reload'
    assert st[69][4] == 10, 'cancelled reload refilled the mag'
    return 'latch rules ok'


# ============================================================================ HEAL FIELD
def check_vector_heal_field(h):
    """9.3: health 100, tap ab2, wait 2.0 s: health >= 175, 'heal' events with ability ab2, and ult charge
    rises by the amount healed (inf_ult off). The field lasts 5 s, the cooldown 15 s from the deploy."""
    from rwf import hero_vector as V, render
    st = {}

    def setup(w):
        w.player.pool.health = 100.0

    def on_frame(w, i, s):
        p = w.player
        st[i] = (p.pool.health, p.ult_charge, len([e for e in w.effects if isinstance(e, V.HealField)]))
        if i == 20:
            sc = render.build_scene(w)
            st['pylon'] = [t for t in sc.sprites if t[2] == 'heal_pylon']
            st['rings'] = [t for t in sc.rings if abs(t[2] - 2.5) < 1e-9]
            st['mini'] = [e.minimap_ring for e in w.effects if isinstance(e, V.HealField)]
            st['inside'] = [e.inside for e in w.effects if isinstance(e, V.HealField)]
    tl = [('tap', 10, 'ab2'), ('tap', 200, 'ab2')]
    r = h.run('vector', 220, timeline=tl, setup=setup, on_frame=on_frame, name='vector_heal', shots=(25,))
    hp = st[69][0]
    assert hp >= 175, 'health %.1f after 2.0 s in the field (need >= 175)' % hp
    heals = [(f, d) for f, n, d in r.events if n == 'heal']
    assert heals and all(d['ability'] == 'ab2' and d['target'] is r.world.player for f, d in heals), 'heal events'
    healed = sum(d['amount'] for f, d in heals if f <= 69)
    gain = st[69][1] - st[9][1]
    assert abs(gain - healed) < 1e-6 and healed > 70, 'ult +%.2f for %.2f healed (want 1:1)' % (gain, healed)
    assert st['pylon'] and abs(st['pylon'][0][4] - 0.35) < 1e-9 and abs(st['pylon'][0][5] - 0.2) < 1e-9, \
        'heal_pylon sprite (0.35 x 0.2) missing'
    assert st['rings'], 'no floor ring of r 2.5'
    assert st['mini'] and st['mini'][0][:3] == (2.5, 7.5, 2.5), 'minimap_ring %r' % st['mini']
    assert st['inside'] == [True]
    assert st[150][2] == 1 and st[165][2] == 0, 'field must last 5.0 s (alive %d at 4.7 s, %d at 5.2 s)' % (
        st[150][2], st[165][2])
    used = r.frames_of('ability_used', slot='ab2')
    assert used == [10], 'cooldown 15 s: ab2 used at frames %r' % used
    cd = r.world.player.hud_state(r.world).abilities[1].cd_left
    assert abs(cd - (15.0 - (219 - 9) * (1 / 30.0))) < 0.05, 'cooldown left %.2f' % cd
    return 'health 100 -> %.0f in 2 s, ult +%.1f' % (hp, gain)


def check_vector_heal_field_area(h):
    """Heals only inside r 2.5, 40 HP/s, 200 HP max over the 5 s; removed on hero swap."""
    from rwf import hero_vector as V
    st = {}

    def setup(w):
        w.player.pool.health = 1.0

    def on_frame(w, i, s):
        f = [e for e in w.effects if isinstance(e, V.HealField)]
        st[i] = (w.player.pool.health, math.hypot(w.player.x - 2.5, w.player.y - 7.5))
    tl = [('tap', 10, 'ab2'), ('hold', 40, 'fwd', 30), ('hold', 90, 'back', 30)]
    r = h.run('vector', 180, timeline=tl, setup=setup, on_frame=on_frame, name='vector_heal_area')
    hf = r.frames_of('heal', ability='ab2')
    outside = [i for i in range(11, 175) if st[i][1] > 2.5 + 1e-9]
    assert outside, 'the player never left the field'
    bad = [i for i in hf if st[i][1] > 2.5 + 1e-9]
    assert not bad, 'healed outside the field at frames %r' % bad[:5]
    assert any(i > outside[-1] for i in hf), 'healing did not resume on walking back in'
    per = [d['amount'] for d in r.where('heal', ability='ab2')]
    full = sum(1 for a in per if abs(a - 40.0 / 30.0) < 1e-9)
    assert all(a <= 40.0 / 30.0 + 1e-9 for a in per) and full > 60, \
        '40 HP/s at 30 fps is 1.333 per frame (max %.4f)' % max(per)
    total = sum(per)
    assert total <= 200.0 + 1e-6, 'healed %.1f > 200 in 5 s' % total
    w = h.make_world('vector')
    w.player.abilities['ab2'].use(w)
    w.player._deploy_field(w)
    f = w.player.field
    assert f is not None and f.alive and f in w.effects
    w.set_hero('flicker', 0.3)
    assert not f.alive and f.minimap_ring is None, 'hero swap must remove the field'
    return 'healed %.1f over %d frames inside, none outside' % (total, len(hf))


# ============================================================================ LOCK-ON
def _lock_layout(h, w, fragile=False):
    """From h.ROOMY (9.5, 12.5) facing north: dummies at -20 and +20 deg (3 cells) and +10 deg (4.5 cells);
    the crosshair points at the empty wall (9, 6); a 4th dummy hides straight ahead behind that wall."""
    h.place(w, *h.ROOMY)
    out = []
    for deg, dist in ((-20.0, 3.0), (20.0, 3.0), (10.0, 4.5)):
        a = math.radians(deg)
        out.append(_dummy(h, w, dist * math.cos(a), dist * math.sin(a), hp=40.0 if (fragile and deg == 10.0)
                          else 1000.0))
    hidden = _dummy_at(w, 9.5, 5.5)
    return out, hidden


def check_vector_lockon(h):
    """9.3: 3 dummies at +-20 deg, aim at an empty wall, tap ult and hold fire 1.0 s: >= 6 damage events on
    the dummies and ammo unchanged. Also: no crits (19 each), clip refilled on activation (reload cancelled),
    targets nearest the crosshair first, never a hidden enemy, no ult charge while active, 6 s duration."""
    rec = {}

    def setup(w):
        rec['d'], rec['hid'] = _lock_layout(h, w)
        w.player.ult_charge = float(w.player.ULT_COST)

    def on_frame(w, i, s):
        rec[i] = (w.player.ammo, w.player.reloading, w.player.ult_charge, w.player.ult_active_left)
    # the ult's slow-mo (0.35x for 0.3 s real) covers frames 11-18, so the 1.0 s hold starts at frame 20
    tl = [('call', 5, lambda w: setattr(w.player, 'ammo', 7)), ('tap', 7, 'reload'), ('tap', 10, 'ult'),
          ('hold', 20, 'fire', 30)]
    r = h.run('vector', 210, timeline=tl, setup=setup, on_frame=on_frame, name='vector_lockon',
              shots=(20, 21))
    ds = rec['d']
    evs = [d for f, n, d in r.events if n == 'damage' and 20 <= f <= 49 and any(d['target'] is x for x in ds)]
    assert len(evs) >= 6, 'only %d damage events on the dummies in 1.0 s of Lock-On' % len(evs)
    assert rec[8][1] and not rec[10][1] and rec[10][0] == 30, 'ult must cancel the reload and refill the clip'
    assert rec[49][0] == rec[11][0] == 30, 'ammo changed during Lock-On (%r -> %r)' % (rec[11][0], rec[49][0])
    assert all(not d['crit'] and abs(d['amount'] - 19.0) < 1e-9 and d['ability'] == 'ult' for d in evs), \
        'Lock-On shots must deal 19 and never crit'
    assert evs[0]['target'] is ds[2], 'first target was not the dummy nearest the crosshair'
    assert _dealt(r, rec['hid']) == 0, 'Lock-On hit an enemy hidden behind a wall'
    assert rec[49][2] == 0.0, 'ult charge rose during Lock-On (%.1f)' % rec[49][2]
    u = r.first('ult_used')
    assert u and u['name'] == 'LOCK-ON' and u['callout'] == 'LOCKED ON!'
    ends = r.where('ult_end')
    span = ends[0]['t'] - u['t'] if len(ends) == 1 else -1.0
    assert abs(span - 6.0) < 0.04, 'ult_end %.3f s (sim) after ult_used, want 6.0' % span
    shots = r.count('shot')
    hits = r.count('shot', hit=True)
    assert shots == 9 and hits == 9, 'Lock-On: %d shots, %d hits' % (shots, hits)
    return '%d damage events in 1 s, ammo %d -> %d' % (len(evs), rec[11][0], rec[49][0])


def check_vector_lockon_retarget(h):
    """Kills during Lock-On are ult kills (label LOCK-ON) and the next shot moves to the next target;
    with no valid target the shot is a manual one (no ammo either)."""
    rec = {}

    def setup(w):
        rec['d'], rec['hid'] = _lock_layout(h, w, fragile=True)
    tl = [('tap', 10, 'ult'), ('hold', 20, 'fire', 30)]
    r = h.run('vector', 55, timeline=tl, setup=setup, debug={'inf_ult': True}, name='vector_lockon_kill')
    k = r.first('kill')
    assert k and k['target'] is rec['d'][2] and k['ult'] and k['label'] == 'LOCK-ON' and k['killer'] == 'VECTOR', \
        'kill during Lock-On: %r' % ({x: k.get(x) for x in ('ult', 'label', 'killer')} if k else None)
    after = [d for f, n, d in r.events if n == 'damage' and d['target'] is not rec['d'][2]]
    assert len(after) >= 4 and all(d['target'] in rec['d'][:2] for d in after), 'no retarget after the kill'

    def setup2(w):
        _dummy_at(w, 1.4, 7.5)               # behind the player: never a Lock-On target
    tl = [('tap', 10, 'ult'), ('hold', 20, 'fire', 15)]
    r = h.run('vector', 40, timeline=tl, setup=setup2, debug={'inf_ult': True}, name='vector_lockon_manual')
    sh = r.where('shot')
    assert len(sh) >= 4 and all(d['kind'] == 'wall' for d in sh), 'manual shots should hit the east wall'
    assert abs(sh[0]['y'] - 7.5) < 1e-9, 'the first manual shot goes where the crosshair points'
    assert r.world.player.ammo == 30 and r.count('damage') == 0
    return 'kill -> %s, retargeted %d shots' % (k['label'], len(after))


# ============================================================================ restore / drawing
def check_vector_restore(h):
    """3.0 stage clear: pools, cooldowns and ammo restored, the sprint latch dropped, ult kept."""
    w = h.make_world('vector')
    p = w.player
    p.pool.health = 30.0
    p.ammo = 3
    p.ult_charge = 700.0
    p.abilities['secondary'].use(w)
    p.abilities['ab2'].use(w)
    p._latched = p.sprinting = True
    w.bus.emit('stage_clear', stage=1)
    assert p.pool.health == 200 and p.ammo == 30 and p.ult_charge == 700.0
    assert all(a.charges == a.max_charges for a in p.abilities.values()) and not p._latched and not p.sprinting


def check_vector_draw(h):
    """3.0 / 6.3: viewmodel inside y 480-768 and out of the central 200x200 box (flash and tracer excepted);
    crosshair radius 10 + spread x 400; icons for every slot at 52/72/96; the heal_pylon painter in every
    state; PNGs with --shots. Also times VECTOR's own per-frame draws."""
    import pygame
    from rwf import hero_vector as V, render
    w = h.make_world('vector')
    p = w.player
    box = pygame.Rect(412, 284, 200, 200)
    for label, prep in (('idle', lambda: None), ('sprint', lambda: setattr(p, '_low', 60.0)),
                        ('reload', lambda: (setattr(p, 'reloading', True), setattr(p, 'reload_left', 0.75))),
                        ('ult', lambda: setattr(p, 'ult_active_left', 3.0)),
                        ('bob', lambda: (setattr(p, '_bob_amp', 1.0), setattr(p, '_bob_phase', 1.3)))):
        prep()
        s = pygame.Surface((1024, 768))
        s.fill((0, 0, 0))
        p.draw_viewmodel(s, w)
        s.set_colorkey((0, 0, 0))
        br = s.get_bounding_rect()
        assert br.width > 250 and br.top >= 480, '%s viewmodel bounds %r' % (label, br)
        assert not br.colliderect(box), '%s viewmodel enters the central box: %r' % (label, br)
    # crosshair circle radius
    s = pygame.Surface((1024, 768))
    p._last_shot = w.now
    p._spread = V.spread_for(7)
    s.fill((0, 0, 0))
    p.draw_crosshair(s, w)
    s.set_colorkey((0, 0, 0))
    br = s.get_bounding_rect()
    rad = int(10 + V.spread_for(7) * 400 + 0.5)
    assert br.width == 2 * rad + 1 or br.width == 2 * rad, 'crosshair %r, want radius %d' % (br, rad)
    # icons and painter
    sheet = pygame.Surface((3 * 110 + 20, 5 * 110 + 20))
    sheet.fill((24, 28, 38))
    for j, slot in enumerate(('portrait', 'secondary', 'ab1', 'ab2', 'ult')):
        for i, size in enumerate((52, 72, 96)):
            r = pygame.Rect(10 + i * 110, 10 + j * 110, size, size)
            V.Vector.draw_icon(slot, sheet, r)
    h.save(sheet, 'vector_icons')
    fn, bw, bh = render.PAINTERS['heal_pylon']
    assert (bw, bh) == (32, 56)
    for st in ('idle', 'pulse', 'nope'):
        for el in (False, True):
            ps = pygame.Surface((bw, bh), pygame.SRCALPHA)
            fn(ps, st, el)
            assert ps.get_bounding_rect().height > 40
    # a live run through every visual state, timing VECTOR's own draws
    times = []
    orig = (V.Vector.draw_viewmodel, V.Vector.draw_overlay, V.Vector.draw_crosshair, V.HealField.draw_screen)

    def timed(fn):
        def wrap(*a):
            t0 = time.perf_counter()
            fn(*a)
            times.append((time.perf_counter() - t0) * 1000.0)
        return wrap

    def setup(w):
        _lock_layout(h, w)
    # fire, Helix, Lock-On on the 3 dummies, Heal Field, walk 2.8 cells away and turn back to face the pylon,
    # then sprint toward it
    tl = [('hold', 5, 'fire', 25), ('tap', 40, 'alt'), ('tap', 60, 'ult'), ('hold', 70, 'fire', 30),
          ('tap', 105, 'ab2'), ('hold', 106, 'fwd', 20), ('aim', 127, math.pi / 2, 0.0), ('tap', 132, 'ab1'),
          ('hold', 132, 'fwd', 14)]
    V.Vector.draw_viewmodel, V.Vector.draw_overlay = timed(orig[0]), timed(orig[1])
    V.Vector.draw_crosshair, V.HealField.draw_screen = timed(orig[2]), timed(orig[3])
    try:
        h.count_surfaces(True)
        h.run('vector', 160, timeline=tl, setup=setup, debug={'inf_ult': True}, name='vector_draw',
              shots=(6, 41, 43, 45, 80, 81, 110, 130, 142))
        big = h.big_surfaces
    finally:
        h.count_surfaces(False)
        V.Vector.draw_viewmodel, V.Vector.draw_overlay, V.Vector.draw_crosshair, V.HealField.draw_screen = orig
    per_frame = sum(times) / 160.0
    times.sort()
    p50 = times[len(times) // 2]
    p95 = times[int(len(times) * 0.95)]
    assert big == 0, '%d surfaces >= 256x256 allocated during the VECTOR run' % big
    assert p95 < 2.0, 'VECTOR draw call p95 %.2f ms' % p95
    return 'draw calls p50 %.3f p95 %.3f ms (%d calls, %.2f ms per frame on average)' % (
        p50, p95, len(times), per_frame)
