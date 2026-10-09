from pathlib import Path

from fpl_bot.services.public_squad import (
    UNLIMITED, estimate_free_transfers, estimate_purchase_prices, estimate_squad_state, selling_price,
)


def history(**transfers_by_gw):
    """history('g2'=1, ...) -> entry history rows; gameweeks not named made no transfers (GW1..last)."""
    last = max(int(k[1:]) for k in transfers_by_gw) if transfers_by_gw else 1
    return [{"event": g, "event_transfers": transfers_by_gw.get(f"g{g}", 0), "bank": 10} for g in range(1, last + 1)]


def test_gw1_is_unlimited_and_gw2_starts_with_one():
    assert estimate_free_transfers([], [], 1) == UNLIMITED
    assert estimate_free_transfers(history(g1=15), [], 2) == 1


def test_unused_transfers_bank_up_to_five():
    # GW2..GW6 all unused: GW3=2, GW4=3, GW5=4, GW6=5, GW7 still capped at 5
    h = history(g6=0)
    assert estimate_free_transfers(h, [], 4) == 3
    assert estimate_free_transfers(h, [], 7) == 5
    assert estimate_free_transfers(history(g9=0), [], 10) == 5


def test_using_transfers_resets_the_balance_and_hits_use_all():
    # 1 FT at GW2, uses it -> 1 at GW3; banks -> 2 at GW4; makes 3 (2 free + a hit) -> 1 at GW5
    h = history(g2=1, g3=0, g4=3)
    assert estimate_free_transfers(h, [], 5) == 1


def test_wildcard_and_free_hit_weeks_do_not_consume_transfers():
    h = history(g2=0, g3=15, g4=0)
    chips = [{"event": 3, "name": "wildcard"}]
    # GW3 would be 2 free; wildcard uses none, so GW4 has 3 and GW5 has 4
    assert estimate_free_transfers(h, chips, 5) == 4
    assert estimate_free_transfers(h, [], 5) == 2  # without the chip GW3 burns both banked transfers


def test_selling_price_keeps_half_of_rise_rounded_down():
    assert selling_price(50, 50) == 50
    assert selling_price(50, 53) == 51
    assert selling_price(50, 55) == 52
    assert selling_price(50, 47) == 47


def test_purchase_price_uses_latest_transfer_in_or_start_price():
    elements = {1: {"now_cost": 60, "cost_change_start": 3}, 2: {"now_cost": 80, "cost_change_start": 0},
                3: {"now_cost": 45, "cost_change_start": -2}}
    transfers = [
        {"time": "2026-09-01T00:00:00Z", "element_in": 2, "element_in_cost": 70, "element_out": 9, "element_out_cost": 70},
        {"time": "2026-09-10T00:00:00Z", "element_in": 2, "element_in_cost": 75, "element_out": 9, "element_out_cost": 75},
    ]
    prices = estimate_purchase_prices([1, 2, 3], transfers, elements)
    assert prices == {1: 57, 2: 75, 3: 47}  # start price = now - net change; rebought player uses latest cost


def test_pending_transfer_is_applied_to_squad_bank_and_free_transfers():
    elements = {i: {"now_cost": 50, "cost_change_start": 0} for i in (1, 2, 3)}
    picks = [{"element": 1, "position": 1, "is_captain": True, "is_vice_captain": False},
             {"element": 2, "position": 2, "is_captain": False, "is_vice_captain": True}]
    transfers = [{"event": 6, "time": "2026-10-09T10:00:00Z", "element_in": 3, "element_in_cost": 48,
                  "element_out": 2, "element_out_cost": 52}]
    state = estimate_squad_state(picks, [{"event": 5, "event_transfers": 0, "bank": 10}], [], transfers,
                                 elements, picks_gw=5, target_gw=6)
    assert [p["element"] for p in state["picks"]] == [1, 3]
    assert state["bank"] == 10 + 52 - 48
    assert state["pending_transfers"] == 1
    assert state["free_transfers"] == 4  # GW6 balance of 5 (banked since GW2) minus the pending move
    swapped = next(p for p in state["picks"] if p["element"] == 3)
    assert swapped["is_vice_captain"] is False  # the armband left with the sold player


def test_dashboard_has_freshness_banner():
    html = (Path(__file__).resolve().parent.parent / "fpl_bot" / "web" / "templates" / "index.html").read_text()
    assert 'id="freshness"' in html and "renderFreshness(diag)" in html


def test_static_data_fetches_bypass_the_browser_cache():
    html = (Path(__file__).resolve().parent.parent / "fpl_bot" / "web" / "templates" / "index.html").read_text()
    assert html.count("`./data/${baseName}.json`, { cache: 'no-store'") == 3
    assert "`./data/${baseName}.json`, options" not in html
