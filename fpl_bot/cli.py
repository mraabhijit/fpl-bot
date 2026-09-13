"""
Command line interface for Autonomous FPL Optimizer.
Supports diagnostic, optimize, backtest, audit, and server modes.
"""

import sys
import argparse
import uvicorn
from fpl_bot.core.config import settings
from fpl_bot.agents.orchestrator import orchestrator
from fpl_bot.core.backtest import backtesting_engine
from fpl_bot.core.database import db
from fpl_bot.services.scheduler import scheduler_service


def run_diagnostic():
    diag = orchestrator.run_diagnostic()
    print("============================================================")
    print(f"FPL CONNECTION: {diag['fpl_connection']}")
    print(f"TEAM ID: {diag['team_id']}")
    print(f"TEAM NAME: {diag['team_name']}")
    print(f"CURRENT GW: {diag['current_gw']}")
    print(f"DEADLINE: {diag['deadline']}")
    print(f"TIMEZONE: {diag['timezone']}")
    print("")
    print(f"OVERALL RANK: {diag['overall_rank']:,}")
    print(f"OVERALL POINTS: {diag['overall_points']}")
    print(f"TEAM VALUE: {diag['team_value']}")
    print(f"BANK: {diag['bank']}")
    print(f"FREE TRANSFERS: {diag['free_transfers']}")
    print("")
    print("CURRENT XI:")
    for player in diag["current_xi"]:
        print(f"  {player}")
    print("")
    print("BENCH:")
    for player in diag["bench"]:
        print(f"  {player}")
    print("")
    print(f"CAPTAIN:\n  {diag['captain']}")
    print(f"VICE:\n  {diag['vice_captain']}")
    print("")
    print("AVAILABLE CHIPS:")
    for chip in diag["available_chips"]:
        print(f"  {chip}")
    print("")
    print("MINI-LEAGUES:")
    for lg in diag["mini_leagues"]:
        print(f"  {lg}")
    print("")
    print(f"AUTHENTICATED WRITE ACCESS:\n{diag['authenticated_write_access']}")
    print("")
    print(f"EXECUTION MODE:\n{diag['execution_mode']}")
    print("============================================================")


def run_optimization():
    print("Running strategic FPL optimization cycle...")
    rec = orchestrator.run_optimization_cycle()
    print("============================================================")
    print(f"GW{rec.gameweek} RECOMMENDATION SUMMARY")
    print(f"Projected Points: {rec.expected_points_recommended:.1f} pts (Hold: {rec.expected_points_hold:.1f} pts)")
    print(f"Net Gain: +{rec.expected_net_gain:.1f} pts | Hit Cost: -{rec.hit_cost} pts")
    print(f"Captain ID: {rec.captain_id} | Vice ID: {rec.vice_captain_id}")
    print(f"Starting XI: {rec.starting_xi}")
    print(f"Bench Order: {rec.bench_order}")
    if rec.transfers_in:
        print(f"Transfers IN: {rec.transfers_in}")
        print(f"Transfers OUT: {rec.transfers_out}")
    else:
        print("Transfers: None (Hold squad)")
    if rec.chip_recommendation:
        print(f"Chip Advisory: {rec.chip_recommendation}")
    print("Reasons:")
    for idx, r in enumerate(rec.reasons, 1):
        print(f"  {idx}. {r}")
    print(f"Approval Required: {rec.approval_required} (Status: {rec.approval_status})")
    print(f"Execution Status: {rec.execution_status}")
    if rec.transaction_hash:
        print(f"Transaction Hash: {rec.transaction_hash[:16]}...")
    print("============================================================")


def run_backtests():
    print("Running historical backtest simulation for GW1-GW4 (zero data leakage)...")
    results = backtesting_engine.run_all_historical(up_to_gw=4)
    print(f"{'GW':<5}{'Projected':<12}{'Optimized':<12}{'Hold/Act':<12}{'Delta':<8}{'Cap Success':<12}")
    print("-" * 65)
    for r in results:
        cap_str = "YES" if r.captain_success else "NO"
        print(f"{r.gameweek:<5}{r.projected_points:<12.1f}{r.actual_points:<12}{r.hold_actual_points:<12}{r.transfer_delta:<+8}{cap_str:<12}")


def run_server():
    print(f"Starting FPL Optimizer Server on {settings.web_host}:{settings.web_port} (Timezone: {settings.timezone})...")
    scheduler_service.start()
    uvicorn.run("fpl_bot.web.app:app", host=settings.web_host, port=settings.web_port, reload=False)


def main():
    parser = argparse.ArgumentParser(description="Autonomous FPL Optimizer CLI")
    parser.add_argument("command", choices=["diagnostic", "optimize", "backtest", "server"], help="Command to run")
    args = parser.parse_args()

    if args.command == "diagnostic":
        run_diagnostic()
    elif args.command == "optimize":
        run_optimization()
    elif args.command == "backtest":
        run_backtests()
    elif args.command == "server":
        run_server()


if __name__ == "__main__":
    main()
