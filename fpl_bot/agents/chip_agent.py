"""
Chip Optimizer Agent evaluating Wildcard, Free Hit, Bench Boost, and Triple Captain.
Section 11 of FPL-Optimizer.md.
"""

from typing import Any, Dict, List, Optional, Tuple
from fpl_bot.core.config import settings
from fpl_bot.core.models import Player, PlayerProjection, CurrentSquad


class ChipAgent:
    def __init__(self):
        self.available_chips = ["wildcard", "freehit", "bboost", "3xc"]

    def evaluate_chips(
        self,
        gameweek: int,
        current_squad: CurrentSquad,
        projections: Dict[int, PlayerProjection],
        used_chips: List[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates whether a chip is strongly recommended for this Gameweek.
        Never activates automatically; outputs structured recommendation for user approval.
        """
        active_chip = current_squad.active_chip
        if active_chip:
            return None

        # Determine remaining available chips for the current phase (e.g. GW 1-19 vs 20-38)
        remaining = [c for c in self.available_chips if c not in used_chips]

        squad_ids = [p.element_id for p in current_squad.picks]
        squad_projections = [projections.get(pid) for pid in squad_ids if pid in projections]

        # 1. Triple Captain Evaluation
        if "3xc" in remaining:
            top_projected = max((projections.get(pid) for pid in squad_ids if projections.get(pid)), key=lambda p: p.expected_fpl_points, default=None)
            if top_projected and top_projected.expected_fpl_points >= 8.5:
                immediate_gain = top_projected.expected_fpl_points
                # If high ceiling player has exceptional fixture (e.g. DGW or home vs struggling team)
                if top_projected.expected_fpl_points >= 9.5:
                    return {
                        "chip": "3xc",
                        "immediate_expected_gain": round(immediate_gain, 1),
                        "future_5gw_gain": 0.0,
                        "opportunity_cost": 4.0,
                        "reason": f"Exceptional Triple Captain opportunity on top performer ({top_projected.expected_fpl_points:.1f} expected points)."
                    }

        # 2. Bench Boost Evaluation
        if "bboost" in remaining:
            # Check bench players points
            bench_ids = [p.element_id for p in current_squad.picks if p.position > 11]
            bench_xp = sum(projections[pid].expected_fpl_points for pid in bench_ids if pid in projections)
            if bench_xp >= 14.0:  # Strong bench all starting with good fixtures
                return {
                    "chip": "bboost",
                    "immediate_expected_gain": round(bench_xp, 1),
                    "future_5gw_gain": 0.0,
                    "opportunity_cost": 5.0,
                    "reason": f"Strong bench fixture alignment with {bench_xp:.1f} projected bench points."
                }

        # 3. Wildcard Evaluation
        if "wildcard" in remaining:
            # If 4 or more players have low availability or very poor multi-gw fixtures
            low_performers = sum(1 for p in squad_projections if p and p.expected_fpl_points < 2.5)
            if low_performers >= 4 and gameweek >= 4:
                return {
                    "chip": "wildcard",
                    "immediate_expected_gain": 12.0,
                    "future_5gw_gain": 35.0,
                    "opportunity_cost": 10.0,
                    "reason": f"Structural squad refresh needed ({low_performers} underperforming/flagged players)."
                }

        # 4. Free Hit Evaluation
        if "freehit" in remaining:
            # Useful if major blank gameweek or severe temporary injury crisis
            flagged = sum(1 for p in current_squad.picks if p.player and p.player.status in ("i", "s", "u"))
            if flagged >= 5:
                return {
                    "chip": "freehit",
                    "immediate_expected_gain": 16.0,
                    "future_5gw_gain": 0.0,
                    "opportunity_cost": 8.0,
                    "reason": f"Temporary crisis management: {flagged} players unavailable this round."
                }

        return None


chip_agent = ChipAgent()
