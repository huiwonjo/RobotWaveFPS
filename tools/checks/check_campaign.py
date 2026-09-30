"""Campaign run (spec 9.2 item 11): god + autokill 2.0 + auto_capture through waves 1-10."""

KINDS = ['assault', 'assault', 'capture', 'assault', 'boss'] * 2


def check_campaign(h):
    st = {'swap_req': False, 'swap_frac': None, 'stage_clears': 0, 'death_set': False, 'summary': 0,
          'potg': 0, 'boss_waves': []}

    def setup(w):
        def on_stage_clear(d):
            st['stage_clears'] += 1

        def on_swap(d):
            st['swap_frac'] = w.player.ult_charge / w.player.ULT_COST
            st['swap_to'] = d['new']

        def on_boss(d):
            st['boss_waves'].append(w.director.wave)
        w.bus.on('stage_clear', on_stage_clear)
        w.bus.on('hero_swap', on_swap)
        w.bus.on('boss_spawn', on_boss)

    def on_frame(w, i, state):
        if state == 'INTERMISSION' and not st['swap_req']:
            st['swap_req'] = True
            w.player.ult_charge = w.player.ULT_COST       # full ult: the swap must cut it to 30%
            h.tap_next('hero2')
        if st['stage_clears'] >= 2 and state == 'INTERMISSION' and not st['death_set']:
            st['death_set'] = True
            w.debug['kill_player_at'] = i + 2
        if state == 'POTG':
            st['potg'] += 1
        if state == 'SUMMARY':
            st['summary'] += 1
            if st['summary'] >= 5:
                return 'stop'
        return None

    r = h.run('vector', 3600, debug={'no_director': False, 'autokill': 2.0, 'auto_capture': True},
              setup=setup, on_frame=on_frame, name='campaign', shots=(200, 1200))
    starts = r.where('wave_start')
    waves = [d['wave'] for d in starts][:10]
    assert waves == list(range(1, 11)), 'wave_start order %r' % waves
    kinds = [d['kind'] for d in starts][:10]
    assert kinds == KINDS, 'wave kinds %r' % kinds
    assert st['boss_waves'][:2] == [5, 10], 'boss_spawn on waves %r' % st['boss_waves']
    assert r.count('stage_clear') == 2, 'stage_clear x%d' % r.count('stage_clear')
    assert st['swap_frac'] is not None and st.get('swap_to') == 'flicker', 'hero2 in the intermission did not swap'
    assert 0 < st['swap_frac'] <= 0.30 + 1e-9, 'ult fraction after swap %.3f' % st['swap_frac']
    assert r.count('player_death') == 1 and 'END_BANNER' in r.states, 'no death / end banner'
    if 'POTG' in r.states:
        assert st['potg'] >= 60 or st['summary'] > 0, 'POTG cut short'
    assert st['summary'] >= 1, 'summary never rendered'
    h.save(h.screen, 'campaign_summary')
    return 'waves 1-10 ok, swap ult %.2f, POTG frames %d' % (st['swap_frac'], st['potg'])
