"""
Domain models for the Autonomous FPL Optimizer.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


class Player(BaseModel):
    id: int
    web_name: str
    first_name: str
    second_name: str
    team_id: int
    team_short_name: str = ""
    team_name: str = ""
    element_type: int  # 1: GKP, 2: DEF, 3: MID, 4: FWD
    position_name: str = ""  # GKP, DEF, MID, FWD
    now_cost: int  # in 10ths (e.g. 155 = 15.5m)
    cost_str: str = ""
    next_opponent: str = ""
    status: str = "a"  # a: available, d: doubtful, i: injured, s: suspended, u: unavailable
    news: str = ""
    chance_of_playing_this_round: Optional[int] = 100
    chance_of_playing_next_round: Optional[int] = 100
    form: float = 0.0
    points_per_game: float = 0.0
    total_points: int = 0
    event_points: int = 0
    selected_by_percent: float = 0.0
    expected_goals: float = 0.0
    expected_assists: float = 0.0
    expected_goal_involvements: float = 0.0
    expected_goals_conceded: float = 0.0
    minutes: int = 0
    goals_scored: int = 0
    assists: int = 0
    clean_sheets: int = 0
    bonus: int = 0
    bps: int = 0
    influence: float = 0.0
    creativity: float = 0.0
    threat: float = 0.0
    ict_index: float = 0.0
    penalties_order: Optional[int] = None
    direct_freekicks_order: Optional[int] = None
    corners_and_indirect_freekicks_order: Optional[int] = None


class Team(BaseModel):
    id: int
    name: str
    short_name: str
    strength: Optional[int] = 3
    strength_overall_home: Optional[int] = 1000
    strength_overall_away: Optional[int] = 1000
    strength_attack_home: Optional[int] = 1000
    strength_attack_away: Optional[int] = 1000
    strength_defence_home: Optional[int] = 1000
    strength_defence_away: Optional[int] = 1000


class Fixture(BaseModel):
    id: int
    event: Optional[int]
    team_h: int
    team_a: int
    team_h_difficulty: int
    team_a_difficulty: int
    kickoff_time: Optional[str]
    finished: bool = False
    started: bool = False
    team_h_score: Optional[int] = None
    team_a_score: Optional[int] = None


class Gameweek(BaseModel):
    id: int
    name: str
    deadline_time: str
    deadline_epoch: float = 0.0
    is_current: bool = False
    is_next: bool = False
    is_previous: bool = False
    finished: bool = False
    chip_plays: List[Dict[str, Any]] = []


class SquadPick(BaseModel):
    element_id: int
    position: int  # 1 to 15
    is_captain: bool = False
    is_vice_captain: bool = False
    multiplier: int = 1
    selling_price: Optional[int] = None
    purchase_price: Optional[int] = None
    player: Optional[Player] = None


class CurrentSquad(BaseModel):
    event: int
    picks: List[SquadPick]
    bank: int  # in 10ths (e.g. 9 = 0.9m)
    value: int  # in 10ths (e.g. 1006 = 100.6m)
    free_transfers: int
    active_chip: Optional[str] = None


class PlayerProjection(BaseModel):
    player_id: int
    expected_minutes: float
    expected_starts: float
    expected_goals: float
    expected_assists: float
    expected_clean_sheet_probability: float
    expected_bonus: float
    expected_cards: float
    expected_goals_conceded: float
    expected_penalty_probability: float
    expected_set_piece_probability: float
    expected_fpl_points: float  # Next GW
    confidence: float
    horizon_points: Dict[int, float] = Field(default_factory=dict)  # 1, 3, 5, 8 GWs


class PlayerAvailability(BaseModel):
    player_id: int
    availability_probability: float
    start_probability: float
    minutes_probability: float
    rotation_risk: float
    injury_risk: float
    news: str = ""


class FixtureScore(BaseModel):
    team_id: int
    fixture_score_1gw: float
    fixture_score_3gw: float
    fixture_score_5gw: float
    fixture_score_8gw: float


class MiniLeagueStanding(BaseModel):
    league_id: int
    league_name: str
    entry_rank: int
    entry_last_rank: int
    leader_name: str = ""
    leader_points: int = 0
    my_points: int = 0
    points_to_leader: int = 0


class TransferMove(BaseModel):
    element_out: int
    element_in: int
    selling_price: int
    purchase_price: int
    immediate_gain: float
    long_term_gain: float
    cost_deduction: int = 0  # 0 or 4 points per hit


class Recommendation(BaseModel):
    gameweek: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
    transfers_in: List[int] = Field(default_factory=list)
    transfers_out: List[int] = Field(default_factory=list)
    starting_xi: List[int] = Field(default_factory=list)
    bench_order: List[int] = Field(default_factory=list)  # [GKP_sub, sub1, sub2, sub3]
    captain_id: int
    vice_captain_id: int
    chip_recommendation: Optional[str] = None
    hit_count: int = 0
    hit_cost: int = 0
    expected_points_hold: float = 0.0
    expected_points_recommended: float = 0.0
    starting_xi_expected_points: float = 0.0
    bench_expected_points: float = 0.0
    bench_autosub_probabilities: Dict[int, float] = Field(default_factory=dict)
    expected_net_gain: float = 0.0
    reasons: List[str] = Field(default_factory=list)
    risk_assessment: str = ""
    approval_required: bool = False
    approval_status: str = "PENDING"  # PENDING, APPROVED, REJECTED, AUTO_ALLOWED
    execution_status: str = "DRY_RUN_OK"  # PENDING, DRY_RUN_OK, EXECUTED, FAILED
    execution_error: Optional[str] = None
    transaction_hash: Optional[str] = None


class BacktestResult(BaseModel):
    gameweek: int
    projected_points: float
    actual_points: int
    hold_actual_points: int
    transfer_delta: int
    captain_actual_points: int
    vice_captain_actual_points: int
    bench_points_left: int
    captain_success: bool
    hit_points_cost: int
    hit_points_gain: int
    notes: str = ""
