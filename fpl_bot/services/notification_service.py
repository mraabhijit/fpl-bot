"""
Notification and Approval workflow message generator matching Section 17 of FPL-Optimizer.md.
"""

from typing import Any, Dict, List, Optional
from fpl_bot.core.models import Recommendation, Player


class NotificationService:
    @staticmethod
    def format_hit_approval_request(
        recommendation: Recommendation,
        players_map: Dict[int, Player],
        deadline_str: str,
        alternative: str = "Hold current squad (0 hit cost)"
    ) -> str:
        """
        Formats Section 17 hit approval request message.
        """
        outs = [f"{players_map[p].web_name} ({players_map[p].team_short_name})" for p in recommendation.transfers_out if p in players_map]
        ins = [f"{players_map[p].web_name} ({players_map[p].team_short_name})" for p in recommendation.transfers_in if p in players_map]

        reasons_formatted = "\n".join(f"{i+1}. {r}" for i, r in enumerate(recommendation.reasons))

        return f"""
============================================================
                     ACTION REQUIRED
============================================================

Gameweek: GW{recommendation.gameweek}
Deadline: {deadline_str}

Proposed action:
OUT: {", ".join(outs)}
IN:  {", ".join(ins)}

Cost:
-{recommendation.hit_cost} points

Expected gain:
+{recommendation.expected_points_recommended - recommendation.expected_points_hold:.1f} points

Expected net gain:
+{recommendation.expected_net_gain:.1f} points

Why:
{reasons_formatted}

Risk:
{recommendation.risk_assessment}

Alternative:
{alternative}

Approve hit?
[YES]  /  [NO]
============================================================
"""

    @staticmethod
    def format_chip_approval_request(
        recommendation: Recommendation,
        deadline_str: str,
        immediate_gain: float,
        five_gw_gain: float,
        opp_cost: float
    ) -> str:
        """
        Formats Section 17 chip approval request message.
        """
        reasons_formatted = "\n".join(f"{i+1}. {r}" for i, r in enumerate(recommendation.reasons))

        return f"""
============================================================
                 CHIP APPROVAL REQUIRED
============================================================

Chip: {recommendation.chip_recommendation}
Gameweek: GW{recommendation.gameweek}
Deadline: {deadline_str}

Expected immediate gain: +{immediate_gain:.1f}
Expected 5-GW gain:      +{five_gw_gain:.1f}
Expected opportunity cost: {opp_cost:.1f}

Reason:
{reasons_formatted}

Approve?
[YES]  /  [NO]
============================================================
"""


notification_service = NotificationService()
