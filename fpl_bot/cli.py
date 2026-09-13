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
    players_map, _, _ = orchestrator.player_data.get_all_players_and_teams()

    print("============================================================")
    print(f"GW{rec.gameweek} RECOMMENDATION SUMMARY")
    print(f"Total 15-Player Squad Projected XP: {rec.expected_points_recommended:.1f} pts (Hold: {rec.expected_points_hold:.1f} pts)")
    print(f"  • Starting XI Base + Captaincy:   {rec.starting_xi_expected_points:.1f} pts")
    print(f"  • Bench Autosub Coverage Value:   {rec.bench_expected_points:.1f} pts")
    print(f"Net Gain: +{rec.expected_net_gain:.1f} pts | Hit Cost: -{rec.hit_cost} pts")
    
    cap_p = players_map.get(rec.captain_id)
    vice_p = players_map.get(rec.vice_captain_id)
    print(f"Captain: {cap_p.web_name if cap_p else rec.captain_id} ({cap_p.team_short_name if cap_p else ''}) | Vice: {vice_p.web_name if vice_p else rec.vice_captain_id} ({vice_p.team_short_name if vice_p else ''})")
    
    print("\nStarting XI:")
    for idx, pid in enumerate(rec.starting_xi, start=1):
        p = players_map.get(pid)
        c_badge = " (C)" if pid == rec.captain_id else (" (V)" if pid == rec.vice_captain_id else "")
        print(f"  {idx:2d}. {p.position_name} {p.web_name} ({p.team_short_name}) £{p.now_cost/10:.1f}m{c_badge}")

    print("\nSubs Lineup Sequence (Formation Legality & Priority Optimized):")
    # Pos 12: GK Sub
    gk_sub = players_map.get(rec.bench_order[0]) if rec.bench_order else None
    gk_prob = rec.bench_autosub_probabilities.get(rec.bench_order[0], 0.0) * 100
    print(f"  Slot 12 [GK Sub]: {gk_sub.web_name} ({gk_sub.team_short_name}) £{gk_sub.now_cost/10:.1f}m (Autosub Prob: {gk_prob:.1f}%)")
    
    # Pos 13, 14, 15: Outfield Subs
    for s_idx, pid in enumerate(rec.bench_order[1:], start=1):
        p = players_map.get(pid)
        prob = rec.bench_autosub_probabilities.get(pid, 0.0) * 100
        print(f"  Slot {12+s_idx} [Sub {s_idx}]:  {p.position_name} {p.web_name} ({p.team_short_name}) £{p.now_cost/10:.1f}m (Autosub Prob: {prob:.1f}%)")

    if rec.transfers_in:
        t_in = [f"{players_map[pid].web_name} ({players_map[pid].team_short_name})" for pid in rec.transfers_in if pid in players_map]
        t_out = [f"{players_map[pid].web_name} ({players_map[pid].team_short_name})" for pid in rec.transfers_out if pid in players_map]
        print(f"\nTransfers IN:  {', '.join(t_in)}")
        print(f"Transfers OUT: {', '.join(t_out)}")
    else:
        print("\nTransfers: None (Hold squad)")

    if rec.chip_recommendation:
        print(f"Chip Advisory: {rec.chip_recommendation}")

    print("\nStrategic Optimization Rationale:")
    for idx, r in enumerate(rec.reasons, 1):
        print(f"  {idx}. {r}")
    print(f"\nApproval Required: {rec.approval_required} (Status: {rec.approval_status})")
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
    uvicorn.run("fpl_bot.web.app:app", host=settings.web_host, port=settings.web_port, reload=True)


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
