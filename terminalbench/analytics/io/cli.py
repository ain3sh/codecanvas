"""
CLI Entry Point for TerminalBench Analytics.

Usage:
    python -m terminalbench.analytics results/<slug>/<batch>/runs --output results/<slug>/<batch>/analytics/
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from ..core.comparisons import ComparisonResult, ProfileComparator
from ..core.deterministic import DeterministicMetrics, compute_aggregate_metrics, compute_metrics
from ..core.intelligent import LLMAnalyzer, estimate_analysis_cost
from ..extensions.codecanvas import (
    CodeCanvasVisionAnalyzer,
    compute_codecanvas_metrics,
    get_codecanvas_images,
    load_codecanvas_state,
)
from .parser import ParsedTrajectory, TrajectoryParser
from .reports import ReportGenerator


def main():
    parser = argparse.ArgumentParser(description="TerminalBench Analytics - Hybrid SOTA Agent Evaluation")
    parser.add_argument("runs_dir", type=Path, help="Path to runs/ directory (e.g., results/3/runs)")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output directory (default: sibling analytics/ dir)",
    )
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM-powered analysis (deterministic only)")
    parser.add_argument("--llm-only", action="store_true", help="Run only LLM analysis")
    parser.add_argument("--compare", nargs=2, metavar=("PROFILE_A", "PROFILE_B"), help="Compare two profiles")
    parser.add_argument("--tasks", nargs="+", help="Filter to specific tasks")
    parser.add_argument("--profiles", nargs="+", help="Filter to specific profiles")
    parser.add_argument("--limit", type=int, help="Randomly sample N trajectories")
    parser.add_argument("--list", action="store_true", help="List discovered runs and exit")
    parser.add_argument("--succeeded", action="store_true", help="Only analyze successful runs")
    parser.add_argument("--failed", action="store_true", help="Only analyze failed runs")
    parser.add_argument("--estimate-cost", action="store_true", help="Estimate LLM cost and exit")
    parser.add_argument("--model", default="openrouter/openai/gpt-5.2", help="LLM model")
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress progress output")

    args = parser.parse_args()

    if not args.runs_dir.exists():
        print(f"Error: Runs directory not found: {args.runs_dir}", file=sys.stderr)
        sys.exit(1)

    # Auto-derive output from runs_dir parent (batch directory)
    if args.output is None:
        args.output = args.runs_dir.parent / "analytics"
    args.output.mkdir(parents=True, exist_ok=True)

    if not args.quiet:
        print(f"Parsing trajectories from {args.runs_dir}...")

    parser_obj = TrajectoryParser(args.runs_dir)
    trajectories = parser_obj.parse_all()

    if not trajectories:
        print("No trajectories found.", file=sys.stderr)
        sys.exit(1)

    # Apply filters
    if args.tasks:
        trajectories = [t for t in trajectories if t.task_id in args.tasks]
    if args.profiles:
        trajectories = [t for t in trajectories if t.profile_key in args.profiles]
    if args.succeeded:
        trajectories = [t for t in trajectories if t.success]
    elif args.failed:
        trajectories = [t for t in trajectories if not t.success]

    if not trajectories:
        print("No trajectories after filtering.", file=sys.stderr)
        sys.exit(1)

    if args.limit and args.limit < len(trajectories):
        import random

        trajectories = random.sample(trajectories, args.limit)

    if args.list:
        print(f"\nDiscovered {len(trajectories)} trajectories:\n")
        print(f"{'Task':<32} {'Profile':<15} {'Success':<8}")
        print("-" * 55)
        for t in sorted(trajectories, key=lambda x: (x.task_id, x.profile_key)):
            print(f"{t.task_id:<32} {t.profile_key:<15} {'PASS' if t.success else 'FAIL':<8}")
        sys.exit(0)

    if not args.quiet:
        print(f"Found {len(trajectories)} trajectories")

    if args.estimate_cost:
        print("\nEstimated LLM Analysis Cost:")
        print(json.dumps(estimate_analysis_cost(len(trajectories)), indent=2))
        sys.exit(0)

    if not args.llm_only:
        if not args.quiet:
            print("\n--- Layer 1: Deterministic Metrics ---")
        run_deterministic_analysis(trajectories, args)

    if not args.no_llm:
        if not args.quiet:
            print("\n--- Layer 2: LLM-Powered Analysis ---")
        run_llm_analysis(trajectories, args)

    if not args.quiet:
        print(f"\nResults written to: {args.output}/")


def run_deterministic_analysis(trajectories: List[ParsedTrajectory], args) -> Dict[str, DeterministicMetrics]:
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

    report_gen = ReportGenerator(args.output)

    csv_path = report_gen.write_metrics_csv(all_metrics)
    if not args.quiet:
        print(f"  Wrote: {csv_path}")

    summary_path = report_gen.write_summary_csv(metrics_by_profile)
    if not args.quiet:
        print(f"  Wrote: {summary_path}")

    profiles = list(metrics_by_profile.keys())
    if args.compare:
        pa, pb = args.compare
        if pa in profiles and pb in profiles:
            comps = run_comparisons(metrics_by_profile[pa], metrics_by_profile[pb], pa, pb, metrics_by_task, args)
            report_gen.write_comparison_report(comps)
    elif len(profiles) >= 2:
        comps = run_comparisons(
            metrics_by_profile[profiles[0]],
            metrics_by_profile[profiles[1]],
            profiles[0],
            profiles[1],
            metrics_by_task,
            args,
        )
        report_gen.write_comparison_report(comps)

    agg_path = args.output / "aggregate_metrics.json"
    aggregate_metrics = {p: compute_aggregate_metrics(m) for p, m in metrics_by_profile.items()}
    agg_path.write_text(json.dumps(aggregate_metrics, indent=2, default=str))
    if not args.quiet:
        print(f"  Wrote: {agg_path}")

    if any(m.codecanvas_evidence_count is not None for m in all_metrics):
        cc_path = report_gen.write_codecanvas_comparison(metrics_by_profile)
        if not args.quiet:
            print(f"  Wrote: {cc_path}")

    return {f"{m.task_id}/{m.profile_key}": m for m in all_metrics}


def run_comparisons(metrics_a, metrics_b, profile_a, profile_b, metrics_by_task, args) -> List[ComparisonResult]:
    comparator = ProfileComparator()
    comparisons = [comparator.compare(metrics_a, metrics_b, profile_a, profile_b)]

    for task_id, task_metrics in metrics_by_task.items():
        ta = [m for m in task_metrics if m.profile_key == profile_a]
        tb = [m for m in task_metrics if m.profile_key == profile_b]
        if ta and tb:
            comparisons.append(comparator.compare(ta, tb, profile_a, profile_b, task_id))

    return comparisons


def run_llm_analysis(trajectories: List[ParsedTrajectory], args):
    analyzer = LLMAnalyzer(model=args.model)
    report_gen = ReportGenerator(args.output)

    metrics_map = {f"{t.task_id}/{t.profile_key}": compute_metrics(t) for t in trajectories}

    if not args.quiet:
        print("  Running strategy analysis...")
    strategy_analyses = []
    for t in trajectories:
        key = f"{t.task_id}/{t.profile_key}"
        strategy_analyses.append((t.task_id, t.profile_key, analyzer.analyze_strategy(t, metrics_map[key])))
    report_gen.write_strategy_analysis(strategy_analyses)

    if not args.quiet:
        print("  Running failure analysis...")
    failure_analyses = []
    for t in trajectories:
        key = f"{t.task_id}/{t.profile_key}"
        if metrics_map[key].success:
            continue
        failure_analyses.append((t.task_id, t.profile_key, analyzer.analyze_failure(t, metrics_map[key])))
    if failure_analyses:
        report_gen.write_failure_analysis(failure_analyses)

    if not args.quiet:
        print("  Running MCP utilization analysis...")
    mcp_analyses = []
    for t in trajectories:
        key = f"{t.task_id}/{t.profile_key}"
        if metrics_map[key].mcp_tool_calls <= 0:
            continue
        mcp_analyses.append((t.task_id, t.profile_key, analyzer.analyze_mcp_utilization(t, metrics_map[key])))
    if mcp_analyses:
        report_gen.write_mcp_analysis(mcp_analyses)

    if not args.quiet:
        print("  Generating comparative narratives...")
    traj_by_task = defaultdict(list)
    for t in trajectories:
        traj_by_task[t.task_id].append(t)

    narratives = []
    for task_id, task_trajs in traj_by_task.items():
        if len(task_trajs) >= 2:
            ta, tb = task_trajs[0], task_trajs[1]
            narratives.append(
                (
                    task_id,
                    analyzer.compare_profiles(
                        task_id,
                        ta,
                        metrics_map[f"{ta.task_id}/{ta.profile_key}"],
                        tb,
                        metrics_map[f"{tb.task_id}/{tb.profile_key}"],
                    ),
                )
            )
    if narratives:
        report_gen.write_comparative_narratives(narratives)

    if not args.quiet:
        print("  Synthesizing insights...")
    profiles = list(set(t.profile_key for t in trajectories))
    tasks = list(set(t.task_id for t in trajectories))
    metrics_by_profile = defaultdict(list)
    for t in trajectories:
        metrics_by_profile[t.profile_key].append(metrics_map[f"{t.task_id}/{t.profile_key}"])
    aggregate_metrics = {p: compute_aggregate_metrics(m) for p, m in metrics_by_profile.items()}

    per_task_sections: List[str] = []
    for tid, ts in traj_by_task.items():
        lines: List[str] = [f"### {tid}"]
        for t in ts:
            key = f"{t.task_id}/{t.profile_key}"
            status = "SUCCESS" if metrics_map[key].success else "FAIL"
            lines.append(f"- {t.profile_key}: {status}")
        per_task_sections.append("\n".join(lines))
    per_task = "\n".join(per_task_sections)

    individual = "\n".join(f"- {tid}/{p}: {a.primary_strategy}" for tid, p, a in strategy_analyses)

    synthesis = analyzer.synthesize_insights(profiles, tasks, aggregate_metrics, per_task, individual)
    report_gen.write_synthesis(synthesis)
    report_gen.write_paper_snippets(synthesis, narratives, aggregate_metrics)

    # CodeCanvas vision analysis
    if not args.quiet:
        print("  Running CodeCanvas vision analysis...")

    cc_metrics_list = []
    cc_visual_analyses = []
    vision_analyzer = None

    for traj in trajectories:
        key = f"{traj.task_id}/{traj.profile_key}"
        cc_state = load_codecanvas_state(traj.trial_dir)
        if cc_state:
            cc_metrics = compute_codecanvas_metrics(traj, cc_state)
            cc_metrics_list.append((traj.task_id, traj.profile_key, cc_metrics))

            images = get_codecanvas_images(traj.trial_dir)
            if images:
                if vision_analyzer is None:
                    vision_analyzer = CodeCanvasVisionAnalyzer(analyzer)

                if not args.quiet:
                    print(f"    Vision analysis: {key}")

                metrics = metrics_map[key]
                visual = vision_analyzer.analyze_run(
                    traj.trial_dir,
                    list(metrics.files_edited),
                    list(metrics.files_read),
                    list(cc_metrics.blast_radius_files),
                    task_description=traj.task_id,
                )
                cc_visual_analyses.append((traj.task_id, traj.profile_key, visual))

    if cc_metrics_list:
        report_gen.write_codecanvas_analysis(cc_metrics_list, cc_visual_analyses or None)


if __name__ == "__main__":
    main()
