from fpl_bot.core.simulation import score_lineup, sell_price

POS = {1: 1, 2: 2, 3: 2, 4: 2, 5: 2, 6: 3, 7: 3, 8: 3, 9: 3, 10: 4, 11: 4,
       12: 1, 13: 2, 14: 3, 15: 4}
XI = list(range(1, 12))


def pts(default=2.0, **over):
    d = {i: default for i in POS}
    d.update({int(k[1:]): v for k, v in over.items()})
    return d


def mins(default=90, **over):
    d = {i: default for i in POS}
    d.update({int(k[1:]): v for k, v in over.items()})
    return d


def test_captain_doubles():
    total = score_lineup(XI, [12, 13, 14, 15], 10, 11, pts(p10=8), mins(), POS)
    assert total == 8 + 2 * 10 + 8  # ten others at 2 plus captain counted twice


def test_vice_captain_takes_over_when_captain_does_not_play():
    p = pts(p10=0, p11=5)
    m = mins(m10=0)
    total = score_lineup(XI, [12, 13, 14, 15], 10, 11, p, m, POS)
    # sub 15 (a forward) replaces the absent forward; vice's points count twice
    assert total == (9 * 2) + 5 + 5 + 2


def test_goalkeeper_autosub():
    total = score_lineup(XI, [12, 13, 14, 15], 10, 11, pts(p1=0, p12=6), mins(m1=0), POS)
    assert total == 6 + 10 * 2 + 2


def test_outfield_autosub_respects_formation():
    # DEF 2 absent: the DEF sub (13) is the first legal replacement and fills the only gap.
    total = score_lineup(XI, [12, 13, 14, 15], 10, 11, pts(p2=0, p13=7), mins(m2=0), POS)
    assert total == 10 * 2 + 7 + 2  # ten starters at 2, DEF sub on for 7, captain bonus 2


def test_sub_that_breaks_formation_is_skipped():
    # XI is 4 DEF / 4 MID / 2 FWD... make it 3 FWD so a 4th forward can never come on.
    pos = dict(POS)
    pos[8] = 4  # XI: 4 DEF (2-5), 3 MID (6,7,9), 3 FWD (8,10,11) -> formation 4-3-3
    # a DEF (3) is absent; bench order puts the forward (15) first, then the DEF (13)
    total = score_lineup(XI, [12, 15, 13, 14], 10, 11, pts(p13=7, p15=9), mins(m3=0), pos)
    assert total == 10 * 2 + 7 + 2  # DEF 13 comes on, forward 15 (illegal 4th FWD) is skipped


def test_selling_price_keeps_half_of_profit():
    assert sell_price(50, 50) == 50
    assert sell_price(50, 53) == 51   # +3 -> keep 1
    assert sell_price(50, 55) == 52   # +5 -> keep 2
    assert sell_price(50, 47) == 47   # falls are passed on in full
