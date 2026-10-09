"""
Rebuilds the squad state that FPL only exposes to a logged-in manager (free transfers, bank, selling prices)
from public endpoints: entry history, transfers and picks. Every function here is pure so it can be tested
without the network. The result is an estimate; ``my-team`` stays authoritative when a token is available.
"""

from typing import Any, Dict, List, Optional

MAX_BANKED_TRANSFERS = 5
UNLIMITED = 15  # GW1 (and chips) have no transfer limit; the optimizer treats >= 15 as unlimited
FREE_TRANSFER_CHIPS = ("wildcard", "freehit")


def selling_price(purchase: int, now: int) -> int:
    """FPL keeps half of any price rise (rounded down); falls are passed on in full."""
    return now if now <= purchase else purchase + (now - purchase) // 2


def estimate_free_transfers(history_current: List[Dict[str, Any]], chips: List[Dict[str, Any]], target_gw: int) -> int:
    """
    Free transfers available for ``target_gw``. You start with 1 for GW2, gain 1 per gameweek, use up to
    your balance on transfers (extras are hits) and bank at most 5. Wildcard and Free Hit weeks use none.
    Caveat: one-off top-ups FPL occasionally grants (for example mid-season) are not visible in history.
    """
    if target_gw <= 1:
        return UNLIMITED
    by_event = {h["event"]: h for h in history_current}
    chip_by_event = {c["event"]: c["name"] for c in chips}
    free = 1  # available for GW2
    for gw in range(2, target_gw):
        made = by_event.get(gw, {}).get("event_transfers", 0)
        used = 0 if chip_by_event.get(gw) in FREE_TRANSFER_CHIPS else min(made, free)
        free = min(MAX_BANKED_TRANSFERS, free - used + 1)
    return free


def estimate_purchase_prices(squad_ids: List[int], transfers: List[Dict[str, Any]],
                             elements: Dict[int, Dict[str, Any]]) -> Dict[int, int]:
    """
    Purchase price per squad player: the cost of the latest transfer in, or the start-of-season price for
    players who were in the original squad (current price minus the season's net price change).
    """
    last_in: Dict[int, int] = {}
    for t in sorted(transfers, key=lambda t: t["time"]):
        last_in[t["element_in"]] = t["element_in_cost"]
    prices = {}
    for pid in squad_ids:
        if pid in last_in:
            prices[pid] = last_in[pid]
        else:
            el = elements[pid]
            prices[pid] = el["now_cost"] - el.get("cost_change_start", 0)
    return prices


def estimate_squad_state(
    picks: List[Dict[str, Any]],
    history_current: List[Dict[str, Any]],
    chips: List[Dict[str, Any]],
    transfers: List[Dict[str, Any]],
    elements: Dict[int, Dict[str, Any]],
    picks_gw: int,
    target_gw: int,
) -> Dict[str, Any]:
    """
    Squad as it stands for ``target_gw``: last published picks with any transfers already made for the target
    gameweek applied, plus bank, free transfers left and per-player purchase and selling prices.
    """
    bank_row = next((h for h in sorted(history_current, key=lambda h: h["event"]) if h["event"] == picks_gw), None)
    bank = bank_row["bank"] if bank_row else 0

    squad = [dict(p) for p in sorted(picks, key=lambda p: p["position"])]
    pending = sorted((t for t in transfers if t["event"] == target_gw and target_gw > picks_gw), key=lambda t: t["time"])
    for t in pending:
        slot = next((p for p in squad if p["element"] == t["element_out"]), None)
        if slot is None:
            continue
        slot["element"] = t["element_in"]
        slot["is_captain"] = slot["is_vice_captain"] = False  # armbands go with the player who left
        bank += t["element_out_cost"] - t["element_in_cost"]

    ids = [p["element"] for p in squad]
    purchase = estimate_purchase_prices(ids, transfers, elements)
    for p in squad:
        pid = p["element"]
        p["purchase_price"] = purchase[pid]
        p["selling_price"] = selling_price(purchase[pid], elements[pid]["now_cost"])

    free = estimate_free_transfers(history_current, chips, target_gw)
    free = max(0, free - len(pending)) if free < UNLIMITED else free
    return {"picks": squad, "bank": bank, "free_transfers": free, "pending_transfers": len(pending)}
