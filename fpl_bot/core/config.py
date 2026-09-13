"""
Configuration and settings for Autonomous FPL Optimizer.
Target team: Overspent FC (6834344)
Season: 2026/27
Timezone: Asia/Kolkata
"""

from pathlib import Path
from typing import List, Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Core Identifiers
    team_id: int = 6834344
    team_name: str = "Overspent FC"
    season: str = "2026/27"
    timezone: str = "Asia/Kolkata"

    # Execution Mode: DRY_RUN | LIVE
    # Live execution is locked down by default until approvals and dry-run verify
    execution_mode: Literal["DRY_RUN", "LIVE"] = "DRY_RUN"

    # Database
    db_path: Path = DATA_DIR / "fpl_optimizer.db"

    # FPL API & Auth Endpoints
    fpl_base_url: str = "https://fantasy.premierleague.com/api"
    auth_issuer_url: str = "https://account.premierleague.com/as"
    auth_client_id: str = "bfcbaf69-aade-4c1b-8f00-c1cb8a193030"
    session_file: Path = DATA_DIR / "session.json"

    # Optional credentials / tokens (can be set via .env or Web UI or OAuth token injection)
    fpl_access_token: str = Field(default="", description="OAuth Bearer token")
    fpl_refresh_token: str = Field(default="", description="OAuth Refresh token")
    fpl_email: str = Field(default="", description="Manager email")

    # Optimization Strategy Weights (Section 14)
    overall_rank_weight: float = 1.0
    mini_league_weight: float = 1.0
    short_term_points_weight: float = 1.0
    long_term_points_weight: float = 0.75
    risk_tolerance: str = "aggressive"
    free_transfer_preference: float = 1.2
    hit_penalty_cost: float = 4.0
    hit_minimum_gain_threshold: float = 2.0  # Net expected point advantage needed to consider hit
    chip_aggression: float = 1.2

    # Planning Horizons (in Gameweeks)
    projection_horizons: List[int] = [1, 3, 5, 8]

    # Scheduling offsets (minutes before deadline)
    schedule_stages: dict = {
        "initial": 1440,    # T-24h
        "refresh": 360,     # T-6h
        "primary": 180,     # T-3h (User primary run)
        "lineup_check": 90, # T-90m
        "final_audit": 30,  # T-30m
        "safety_check": 15, # T-15m
    }

    # Web Dashboard
    web_host: str = "0.0.0.0"
    web_port: int = 8000


settings = Settings()
