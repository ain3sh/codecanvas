"""
Report Generation - Output artifacts for analysis results.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.deterministic import DeterministicMetrics, compute_aggregate_metrics
from ..core.comparisons import ComparisonResult, format_comparison_table
from ..core.intelligent import (
    StrategyAnalysis,
    FailureAnalysis,
    MCPUtilizationAnalysis,
    ComparativeNarrative,
    InsightSynthesis,
)
from ..extensions.codecanvas import CodeCanvasMetrics, aggregate_codecanvas_metrics, CodeCanvasVisualAnalysis


class ReportGenerator:
    """Generate analysis reports in multiple formats."""
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def write_metrics_csv(self, metrics: List[DeterministicMetrics], filename: str = "metrics_detail.csv") -> Path:
        """Write per-trajectory metrics to CSV."""
        path = self.output_dir / filename
        if not metrics:
            return path
        
        fieldnames = list(metrics[0].to_dict().keys())
        with open(path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for m in metrics:
                row = m.to_dict()
                for k, v in row.items():
                    if isinstance(v, (list, dict, set)):
                        row[k] = json.dumps(v) if v else ""
                writer.writerow(row)
        return path
    
    def write_summary_csv(self, metrics_by_profile: Dict[str, List[DeterministicMetrics]], filename: str = "metrics_summary.csv") -> Path:
        """Write aggregated metrics by profile to CSV."""
        path = self.output_dir / filename
        rows = []
        for profile, metrics in metrics_by_profile.items():
            agg = compute_aggregate_metrics(metrics)
            agg["profile"] = profile
            rows.append(agg)
        
        if not rows:
            return path
        
        fieldnames = ["profile"] + [k for k in rows[0].keys() if k != "profile"]
        with open(path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                clean_row = {}
                for k, v in row.items():
                    if isinstance(v, (list, dict)):
                        clean_row[k] = json.dumps(v) if v else ""
                    elif isinstance(v, float):
                        clean_row[k] = f"{v:.4f}"
                    else:
                        clean_row[k] = v
                writer.writerow(clean_row)
        return path
    
    def write_comparison_report(self, comparisons: List[ComparisonResult], filename: str = "comparison_report.md") -> Path:
        """Write comparison report as markdown."""
        path = self.output_dir / filename
        lines = [
            "# Profile Comparison Report",
            f"\nGenerated: {datetime.now().isoformat()}",
            "\n## Summary Table\n",
            format_comparison_table(comparisons),
            "\n## Detailed Comparisons\n",
        ]
        
        for comp in comparisons:
            task = comp.task_id or "All Tasks"
            lines.extend([
                f"\n### {task}: {comp.profile_a} vs {comp.profile_b}\n",
                f"**Sample Sizes**: n_a={comp.n_a}, n_b={comp.n_b}\n",
                "\n**Key Deltas** (B - A):",
            ])
            for key, delta in comp.deltas.items():
                if not key.endswith("_pct_change"):
                    pct = comp.deltas.get(f"{key}_pct_change")
                    pct_str = f" ({pct:+.1f}%)" if pct else ""
                    lines.append(f"- {key}: {delta:+.2f}{pct_str}")
            
            lines.append("\n**Statistical Tests**:")
            for name, test in comp.tests.items():
                sig = "***" if test.significant else ""
                effect = f", effect={test.effect_interpretation}" if test.effect_interpretation else ""
                lines.append(f"- {name}: p={test.p_value:.4f}{sig}{effect}")
        
        path.write_text("\n".join(lines))
        return path
    
    def write_strategy_analysis(self, analyses: List[tuple[str, str, StrategyAnalysis]], filename: str = "strategy_analysis.json") -> Path:
        path = self.output_dir / filename
        data = [{
            "task_id": task_id, "profile": profile,
            "primary_strategy": a.primary_strategy, "strategy_quality": a.strategy_quality,
            "reasoning_coherence": a.reasoning_coherence, "adaptation_events": a.adaptation_events,
            "strengths": a.strengths, "weaknesses": a.weaknesses, "key_decisions": a.key_decisions,
        } for task_id, profile, a in analyses]
        path.write_text(json.dumps(data, indent=2))
        return path
    
    def write_failure_analysis(self, analyses: List[tuple[str, str, FailureAnalysis]], filename: str = "failure_analyses.json") -> Path:
        path = self.output_dir / filename
        data = [{
            "task_id": task_id, "profile": profile,
            "root_cause": a.root_cause, "confidence": a.confidence,
            "critical_step": a.critical_step, "critical_step_explanation": a.critical_step_explanation,
            "missed_insight": a.missed_insight, "counterfactual": a.counterfactual,
            "contributing_factors": a.contributing_factors, "task_specific_difficulty": a.task_specific_difficulty,
        } for task_id, profile, a in analyses if a.root_cause != "not_applicable"]
        path.write_text(json.dumps(data, indent=2))
        return path
    
    def write_mcp_analysis(self, analyses: List[tuple[str, str, MCPUtilizationAnalysis]], filename: str = "mcp_utilization.json") -> Path:
        path = self.output_dir / filename
        data = [{
            "task_id": task_id, "profile": profile,
            "utilization_quality": a.utilization_quality, "init_timing": a.init_timing,
            "init_quality": a.init_quality, "dependency_leverage": a.dependency_leverage,
            "search_effectiveness": a.search_effectiveness, "structural_understanding": a.structural_understanding,
            "missed_opportunities": a.missed_opportunities, "effective_uses": a.effective_uses,
            "recommendation": a.recommendation,
        } for task_id, profile, a in analyses]
        path.write_text(json.dumps(data, indent=2))
        return path
    
    def write_comparative_narratives(self, narratives: List[tuple[str, ComparativeNarrative]], filename: str = "comparative_narratives.md") -> Path:
        path = self.output_dir / filename
        lines = ["# Comparative Narratives", f"\nGenerated: {datetime.now().isoformat()}"]
        
        for task_id, n in narratives:
            lines.extend([
                f"\n## {task_id}\n", f"**Winner**: {n.winner}", f"\n**Reason**: {n.winner_reason}\n",
                "\n### Performance Delta\n",
                *[f"- **{k}**: {v}" for k, v in n.performance_delta.items()],
                f"\n### Exploration Comparison\n{n.exploration_comparison}",
                f"\n### Key Insight\n> {n.key_insight}",
                f"\n### Paper-Ready Paragraph\n{n.narrative_paragraph}",
            ])
            if n.quote_worthy_moment:
                lines.append(f"\n### Quote-Worthy Moment\nStep {n.quote_worthy_moment.get('step')}: {n.quote_worthy_moment.get('description')}")
        
        path.write_text("\n".join(lines))
        return path
    
    def write_synthesis(self, synthesis: InsightSynthesis, filename: str = "synthesis.md") -> Path:
        path = self.output_dir / filename
        s = synthesis
        lines = [
            "# Cross-Run Insight Synthesis", f"\nGenerated: {datetime.now().isoformat()}",
            "\n## Task Difficulty Ranking\n",
            *[f"- **{i.get('task')}** ({i.get('difficulty')}): {i.get('reason')}" for i in s.task_difficulty_ranking],
            "\n## MCP Benefit Patterns\n", *[f"- {p}" for p in s.mcp_benefit_patterns],
            "\n## MCP Overhead Patterns\n", *[f"- {p}" for p in s.mcp_overhead_patterns],
            "\n## Emergent Findings\n", *[f"- {f}" for f in s.emergent_findings],
            "\n## Recommended Improvements\n",
            *[f"- **{i.get('tool')}**: {i.get('improvement')}" for i in s.recommended_improvements],
            "\n## Paper Claims\n",
        ]
        for c in s.paper_claims:
            lines.extend([f"\n### Claim ({c.get('confidence', 'medium')} confidence)", f"> {c.get('claim')}", f"\n**Evidence**: {c.get('evidence')}"])
        lines.extend(["\n## Limitations\n", *[f"- {l}" for l in s.limitations], "\n## Future Work\n", *[f"- {f}" for f in s.future_work]])
        path.write_text("\n".join(lines))
        return path
    
    def write_paper_snippets(self, synthesis: InsightSynthesis, narratives: List[tuple[str, ComparativeNarrative]], aggregate_metrics: Dict[str, Dict[str, Any]], filename: str = "paper_snippets.md") -> Path:
        path = self.output_dir / filename
        lines = ["# Paper Snippets", "\n## Results Section\n"]
        
        if aggregate_metrics and len(aggregate_metrics) >= 2:
            profiles = list(aggregate_metrics.keys())
            p1, p2 = profiles[0], profiles[1]
            m1, m2 = aggregate_metrics[p1], aggregate_metrics[p2]
            lines.append(f"Our evaluation compared {p1} (n={m1.get('count', 0)}) against {p2} (n={m2.get('count', 0)}). The {p1} configuration achieved {m1.get('success_rate', 0):.1f}% success rate with average cost of ${m1.get('avg_cost', 0):.4f}, while {p2} achieved {m2.get('success_rate', 0):.1f}% success rate at ${m2.get('avg_cost', 0):.4f} average cost.")
        
        lines.extend(["\n## Per-Task Narratives\n", *[f"### {tid}\n{n.narrative_paragraph}\n" for tid, n in narratives]])
        lines.extend(["\n## Key Insights\n", *[f"- **{tid}**: {n.key_insight}" for tid, n in narratives if n.key_insight]])
        lines.extend(["\n## Supported Claims\n", *[f"- {c.get('claim')}" for c in synthesis.paper_claims if c.get('confidence') == 'high']])
        path.write_text("\n".join(lines))
        return path
    
    def write_codecanvas_analysis(self, metrics: List[tuple[str, str, CodeCanvasMetrics]], visual_analyses: Optional[List[tuple[str, str, CodeCanvasVisualAnalysis]]] = None, filename: str = "codecanvas_analysis.json") -> Path:
        path = self.output_dir / filename
        all_metrics = [m for _, _, m in metrics]
        data = {
            "per_run": [{"task_id": tid, "profile": p, **m.to_dict()} for tid, p, m in metrics],
            "aggregate": aggregate_codecanvas_metrics(all_metrics) if all_metrics else {},
            "visual_analyses": [{"task_id": tid, "profile": p, **v.to_dict()} for tid, p, v in visual_analyses] if visual_analyses else [],
        }
        path.write_text(json.dumps(data, indent=2, default=list))
        return path
    
    def write_codecanvas_comparison(self, metrics_by_profile: Dict[str, List[DeterministicMetrics]], filename: str = "codecanvas_comparison.md") -> Path:
        path = self.output_dir / filename
        lines = [
            "# CodeCanvas vs Baselines Comparison", f"\nGenerated: {datetime.now().isoformat()}",
            "\n## Informed Editing Score Comparison\n",
            "| Profile | Runs | Avg Score | Blast Radius Edit Rate | Deliberation Depth |",
            "|---------|------|-----------|------------------------|-------------------|",
        ]
        
        for profile, mlist in metrics_by_profile.items():
            cc = [m for m in mlist if m.codecanvas_informed_editing_score is not None]
            if cc:
                avg_score = sum(m.codecanvas_informed_editing_score for m in cc if m.codecanvas_informed_editing_score is not None) / len(cc)
                avg_blast = sum(m.codecanvas_blast_radius_edit_rate or 0 for m in cc) / len(cc)
                avg_depth = sum(m.codecanvas_deliberation_depth or 0 for m in cc) / len(cc)
                lines.append(f"| {profile} | {len(cc)} | {avg_score:.3f} | {avg_blast:.3f} | {avg_depth:.1f} |")
            else:
                lines.append(f"| {profile} | {len(mlist)} | N/A | N/A | N/A |")
        
        lines.extend([
            "\n## Evidence Board Usage\n",
            "| Profile | Avg Evidence | Avg Claims | Avg Decisions | Reasoning Density |",
            "|---------|--------------|------------|---------------|-------------------|",
        ])
        
        for profile, mlist in metrics_by_profile.items():
            cc = [m for m in mlist if m.codecanvas_evidence_count is not None]
            if cc:
                lines.append(f"| {profile} | {sum(m.codecanvas_evidence_count or 0 for m in cc)/len(cc):.1f} | {sum(m.codecanvas_claims_count or 0 for m in cc)/len(cc):.1f} | {sum(m.codecanvas_decisions_count or 0 for m in cc)/len(cc):.1f} | {sum(m.codecanvas_reasoning_density or 0 for m in cc)/len(cc):.2f} |")
            else:
                lines.append(f"| {profile} | N/A | N/A | N/A | N/A |")
        
        lines.extend([
            "\n## Key Insight",
            "\nThe **Informed Editing Score** measures whether visual impact analysis changed agent behavior:",
            "- **Blast Radius Edit Rate**: % of edits within analyzed impact zones",
            "- **Anticipated Failure Rate**: % of test failures in blast radius (expected)",
            "- **Deliberation Depth**: Claims + decisions made before first edit",
        ])
        path.write_text("\n".join(lines))
        return path
