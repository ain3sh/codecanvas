"""
CLI Entry Point for TerminalBench Analytics.

Usage:
    python -m terminalbench.analytics results/runs/ --output results/analytics/
    python -m terminalbench.analytics results/runs/ --no-llm
    python -m terminalbench.analytics results/runs/ --compare text loc
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from .parser import TrajectoryParser, ParsedTrajectory
from .deterministic import DeterministicMetrics, compute_metrics, compute_aggregate_metrics
from .comparisons import ProfileComparator, ComparisonResult
from .reports import ReportGenerator
from .llm_analysis import (
    LLMAnalyzer,
    estimate_analysis_cost,
    StrategyAnalysis,
    FailureAnalysis,
    MCPUtilizationAnalysis,
    ComparativeNarrative,
    InsightSynthesis,
)


def main():
    parser = argparse.ArgumentParser(
        description="TerminalBench Analytics v2 - Hybrid SOTA Agent Evaluation"
    )
    parser.add_argument(
        "runs_dir",
        type=Path,
        help="Path to runs/ directory",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("results/analytics"),
        help="Output directory (default: results/analytics/)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM-powered analysis (deterministic only)",
    )
    parser.add_argument(
        "--llm-only",
        action="store_true",
        help="Run only LLM analysis (assumes deterministic already done)",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("PROFILE_A", "PROFILE_B"),
        help="Compare two specific profiles",
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        help="Filter to specific tasks",
    )
    parser.add_argument(
        "--profiles",
        nargs="+",
        help="Filter to specific profiles (e.g., text codegraph codecanvas)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Randomly sample N trajectories (useful for testing)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List discovered runs and exit (no processing)",
    )
    parser.add_argument(
        "--succeeded",
        action="store_true",
        help="Only analyze successful runs",
    )
    parser.add_argument(
        "--failed",
        action="store_true",
        help="Only analyze failed runs",
    )
    parser.add_argument(
        "--estimate-cost",
        action="store_true",
        help="Estimate LLM analysis cost and exit",
    )
    parser.add_argument(
        "--model",
        default="openrouter/openai/gpt-5.2",
        help="LLM model for analysis (default: openrouter/openai/gpt-5.2)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output",
    )
    
    args = parser.parse_args()
    
    # Validate runs directory
    if not args.runs_dir.exists():
        print(f"Error: Runs directory not found: {args.runs_dir}", file=sys.stderr)
        sys.exit(1)
    
    # Parse trajectories
    if not args.quiet:
        print(f"Parsing trajectories from {args.runs_dir}...")
    
    parser_obj = TrajectoryParser(args.runs_dir)
    trajectories = parser_obj.parse_all()
    
    if not trajectories:
        print("No trajectories found.", file=sys.stderr)
        sys.exit(1)
    
    # Filter by tasks if specified
    if args.tasks:
        trajectories = [t for t in trajectories if t.task_id in args.tasks]
        if not trajectories:
            print(f"No trajectories found for tasks: {args.tasks}", file=sys.stderr)
            sys.exit(1)
    
    # Filter by profiles if specified
    if args.profiles:
        trajectories = [t for t in trajectories if t.profile_key in args.profiles]
        if not trajectories:
            print(f"No trajectories found for profiles: {args.profiles}", file=sys.stderr)
            sys.exit(1)
    
    # Filter by outcome
    if args.succeeded:
        trajectories = [t for t in trajectories if t.success]
        if not trajectories:
            print("No successful trajectories found.", file=sys.stderr)
            sys.exit(1)
    elif args.failed:
        trajectories = [t for t in trajectories if not t.success]
        if not trajectories:
            print("No failed trajectories found.", file=sys.stderr)
            sys.exit(1)
    
    # Random sample if --limit specified
    if args.limit and args.limit < len(trajectories):
        import random
        trajectories = random.sample(trajectories, args.limit)
        if not args.quiet:
            print(f"Randomly sampled {args.limit} trajectories")
    
    # List mode - show discovered runs and exit
    if args.list:
        print(f"\nDiscovered {len(trajectories)} trajectories:\n")
        print(f"{'Task':<32} {'Profile':<15} {'Success':<8}")
        print("-" * 55)
        for t in sorted(trajectories, key=lambda x: (x.task_id, x.profile_key)):
            status = "PASS" if t.success else "FAIL"
            print(f"{t.task_id:<32} {t.profile_key:<15} {status:<8}")
        print(f"\nUnique tasks: {sorted(set(t.task_id for t in trajectories))}")
        print(f"Unique profiles: {sorted(set(t.profile_key for t in trajectories))}")
        sys.exit(0)
    
    if not args.quiet:
        print(f"Found {len(trajectories)} trajectories")
        print(f"Tasks: {parser_obj.get_unique_tasks()}")
        print(f"Profiles: {parser_obj.get_unique_profiles()}")
    
    # Estimate cost if requested
    if args.estimate_cost:
        cost_est = estimate_analysis_cost(len(trajectories))
        print("\nEstimated LLM Analysis Cost:")
        print(json.dumps(cost_est, indent=2))
        sys.exit(0)
    
    # Compute deterministic metrics
    if not args.llm_only:
        if not args.quiet:
            print("\n--- Layer 1: Deterministic Metrics ---")
        run_deterministic_analysis(trajectories, args)
    
    # Run LLM analysis
    if not args.no_llm:
        if not args.quiet:
            print("\n--- Layer 2: LLM-Powered Analysis ---")
        run_llm_analysis(trajectories, args)
    
    if not args.quiet:
        print(f"\nResults written to: {args.output}/")


def run_deterministic_analysis(
    trajectories: List[ParsedTrajectory],
    args: argparse.Namespace,
) -> Dict[str, DeterministicMetrics]:
    """Run deterministic metrics computation."""
    
    # Compute metrics for each trajectory
    all_metrics: List[DeterministicMetrics] = []
    metrics_by_profile: Dict[str, List[DeterministicMetrics]] = defaultdict(list)
    metrics_by_task: Dict[str, List[DeterministicMetrics]] = defaultdict(list)
    
    for traj in trajectories:
        if not args.quiet:
            print(f"  Computing metrics: {traj.task_id} / {traj.profile_key}")
        
        metrics = compute_metrics(traj)
        all_metrics.append(metrics)
        metrics_by_profile[traj.profile_key].append(metrics)
        metrics_by_task[traj.task_id].append(metrics)
    
    # Generate reports
    report_gen = ReportGenerator(args.output)
    
    # Write detailed metrics CSV
    csv_path = report_gen.write_metrics_csv(all_metrics)
    if not args.quiet:
        print(f"  Wrote: {csv_path}")
    
    # Write summary CSV
    summary_path = report_gen.write_summary_csv(metrics_by_profile)
    if not args.quiet:
        print(f"  Wrote: {summary_path}")
    
    # Run comparisons if requested or if multiple profiles
    profiles = list(metrics_by_profile.keys())
    
    if args.compare:
        profile_a, profile_b = args.compare
        if profile_a not in profiles or profile_b not in profiles:
            print(f"Warning: Profiles {args.compare} not found in data", file=sys.stderr)
        else:
            comparisons = run_comparisons(
                metrics_by_profile[profile_a],
                metrics_by_profile[profile_b],
                profile_a,
                profile_b,
                metrics_by_task,
                args,
            )
            comp_path = report_gen.write_comparison_report(comparisons)
            if not args.quiet:
                print(f"  Wrote: {comp_path}")
    
    elif len(profiles) >= 2:
        # Auto-compare first two profiles
        profile_a, profile_b = profiles[0], profiles[1]
        comparisons = run_comparisons(
            metrics_by_profile[profile_a],
            metrics_by_profile[profile_b],
            profile_a,
            profile_b,
            metrics_by_task,
            args,
        )
        comp_path = report_gen.write_comparison_report(comparisons)
        if not args.quiet:
            print(f"  Wrote: {comp_path}")
    
    # Write aggregate JSON
    agg_path = args.output / "aggregate_metrics.json"
    agg_data = {
        profile: compute_aggregate_metrics(metrics)
        for profile, metrics in metrics_by_profile.items()
    }
    agg_path.write_text(json.dumps(agg_data, indent=2, default=str))
    if not args.quiet:
        print(f"  Wrote: {agg_path}")
    
    return {m.task_id + "/" + m.profile_key: m for m in all_metrics}


def run_comparisons(
    metrics_a: List[DeterministicMetrics],
    metrics_b: List[DeterministicMetrics],
    profile_a: str,
    profile_b: str,
    metrics_by_task: Dict[str, List[DeterministicMetrics]],
    args: argparse.Namespace,
) -> List[ComparisonResult]:
    """Run statistical comparisons between profiles."""
    
    comparator = ProfileComparator()
    comparisons = []
    
    # Overall comparison
    if not args.quiet:
        print(f"  Comparing: {profile_a} vs {profile_b} (overall)")
    
    overall = comparator.compare(metrics_a, metrics_b, profile_a, profile_b)
    comparisons.append(overall)
    
    # Per-task comparisons
    for task_id, task_metrics in metrics_by_task.items():
        task_a = [m for m in task_metrics if m.profile_key == profile_a]
        task_b = [m for m in task_metrics if m.profile_key == profile_b]
        
        if task_a and task_b:
            if not args.quiet:
                print(f"  Comparing: {profile_a} vs {profile_b} on {task_id}")
            
            task_comp = comparator.compare(
                task_a, task_b, profile_a, profile_b, task_id
            )
            comparisons.append(task_comp)
    
    return comparisons


def run_llm_analysis(
    trajectories: List[ParsedTrajectory],
    args: argparse.Namespace,
):
    """Run LLM-powered semantic analysis."""
    
    analyzer = LLMAnalyzer(model=args.model)
    report_gen = ReportGenerator(args.output)
    
    # Compute metrics first (needed for LLM context)
    metrics_map = {}
    for traj in trajectories:
        key = f"{traj.task_id}/{traj.profile_key}"
        metrics_map[key] = compute_metrics(traj)
    
    # Strategy analysis for all trajectories
    if not args.quiet:
        print("  Running strategy analysis...")
    
    strategy_analyses = []
    for traj in trajectories:
        key = f"{traj.task_id}/{traj.profile_key}"
        if not args.quiet:
            print(f"    Analyzing: {key}")
        
        analysis = analyzer.analyze_strategy(traj, metrics_map[key])
        strategy_analyses.append((traj.task_id, traj.profile_key, analysis))
    
    strategy_path = report_gen.write_strategy_analysis(strategy_analyses)
    if not args.quiet:
        print(f"  Wrote: {strategy_path}")
    
    # Failure analysis for failed trajectories
    if not args.quiet:
        print("  Running failure analysis...")
    
    failure_analyses = []
    for traj in trajectories:
        key = f"{traj.task_id}/{traj.profile_key}"
        if not metrics_map[key].success:
            if not args.quiet:
                print(f"    Analyzing failure: {key}")
            
            analysis = analyzer.analyze_failure(traj, metrics_map[key])
            failure_analyses.append((traj.task_id, traj.profile_key, analysis))
    
    if failure_analyses:
        failure_path = report_gen.write_failure_analysis(failure_analyses)
        if not args.quiet:
            print(f"  Wrote: {failure_path}")
    
    # MCP utilization for MCP-enabled trajectories
    if not args.quiet:
        print("  Running MCP utilization analysis...")
    
    mcp_analyses = []
    for traj in trajectories:
        key = f"{traj.task_id}/{traj.profile_key}"
        metrics = metrics_map[key]
        if metrics.mcp_tool_calls > 0:
            if not args.quiet:
                print(f"    Analyzing MCP usage: {key}")
            
            analysis = analyzer.analyze_mcp_utilization(traj, metrics)
            mcp_analyses.append((traj.task_id, traj.profile_key, analysis))
    
    if mcp_analyses:
        mcp_path = report_gen.write_mcp_analysis(mcp_analyses)
        if not args.quiet:
            print(f"  Wrote: {mcp_path}")
    
    # Comparative narratives (pair trajectories by task)
    if not args.quiet:
        print("  Generating comparative narratives...")
    
    narratives = []
    traj_by_task = defaultdict(list)
    for traj in trajectories:
        traj_by_task[traj.task_id].append(traj)
    
    for task_id, task_trajs in traj_by_task.items():
        if len(task_trajs) >= 2:
            # Compare first two profiles
            traj_a, traj_b = task_trajs[0], task_trajs[1]
            key_a = f"{traj_a.task_id}/{traj_a.profile_key}"
            key_b = f"{traj_b.task_id}/{traj_b.profile_key}"
            
            if not args.quiet:
                print(f"    Comparing: {traj_a.profile_key} vs {traj_b.profile_key} on {task_id}")
            
            narrative = analyzer.compare_profiles(
                task_id,
                traj_a, metrics_map[key_a],
                traj_b, metrics_map[key_b],
            )
            narratives.append((task_id, narrative))
    
    if narratives:
        narrative_path = report_gen.write_comparative_narratives(narratives)
        if not args.quiet:
            print(f"  Wrote: {narrative_path}")
    
    # Cross-run synthesis
    if not args.quiet:
        print("  Synthesizing insights...")
    
    # Build inputs for synthesis
    profiles = list(set(t.profile_key for t in trajectories))
    tasks = list(set(t.task_id for t in trajectories))
    
    metrics_by_profile = defaultdict(list)
    for traj in trajectories:
        key = f"{traj.task_id}/{traj.profile_key}"
        metrics_by_profile[traj.profile_key].append(metrics_map[key])
    
    aggregate_metrics = {
        profile: compute_aggregate_metrics(metrics)
        for profile, metrics in metrics_by_profile.items()
    }
    
    # Build per-task summary
    per_task_lines = []
    for task_id, task_trajs in traj_by_task.items():
        per_task_lines.append(f"\n### {task_id}")
        for traj in task_trajs:
            key = f"{traj.task_id}/{traj.profile_key}"
            m = metrics_map[key]
            status = "SUCCESS" if m.success else "FAIL"
            per_task_lines.append(f"- {traj.profile_key}: {status}, {m.total_steps} steps, ${m.total_cost_usd:.4f}")
    
    # Build individual summaries
    individual_lines = []
    for task_id, profile, analysis in strategy_analyses:
        individual_lines.append(f"- {task_id}/{profile}: {analysis.primary_strategy} (quality={analysis.strategy_quality:.2f})")
    
    synthesis = analyzer.synthesize_insights(
        profiles=profiles,
        tasks=tasks,
        aggregate_metrics=aggregate_metrics,
        per_task_summary="\n".join(per_task_lines),
        individual_summaries="\n".join(individual_lines),
    )
    
    synthesis_path = report_gen.write_synthesis(synthesis)
    if not args.quiet:
        print(f"  Wrote: {synthesis_path}")
    
    # Paper snippets
    snippets_path = report_gen.write_paper_snippets(
        synthesis, narratives, aggregate_metrics
    )
    if not args.quiet:
        print(f"  Wrote: {snippets_path}")


if __name__ == "__main__":
    main()
