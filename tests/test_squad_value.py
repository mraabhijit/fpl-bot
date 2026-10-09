from fpl_bot.agents.orchestrator import Orchestrator
from fpl_bot.core.models import CurrentSquad, Player, SquadPick


def pick(pid: int, now_cost: int, selling: int) -> SquadPick:
    player = Player(id=pid, web_name=f"P{pid}", first_name="T", second_name=str(pid),
                    team_id=pid, element_type=3, now_cost=now_cost)
    return SquadPick(element_id=pid, position=pid, selling_price=selling, player=player)


def test_squad_value_is_market_price_and_sell_value_is_lower_after_rises():
    # bought at 5.0m, now 5.5m: FPL keeps half the rise, so he sells for 5.2m
    squad = CurrentSquad(event=5, picks=[pick(1, 55, 52), pick(2, 60, 60)], bank=18, value=112, free_transfers=1)
    vals = Orchestrator._squad_values(squad)
    assert vals == {"team_value": "£11.5m", "sell_value": "£11.2m"}


def test_sell_value_hidden_without_authentication():
    squad = CurrentSquad(event=5, picks=[pick(1, 55, 55)], bank=0, value=55, free_transfers=1)
    vals = Orchestrator._squad_values(squad, authenticated=False)
    assert vals == {"team_value": "£5.5m", "sell_value": None}
