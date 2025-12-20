"""
Report Generation - Output artifacts for analysis results.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .deterministic import DeterministicMetrics, compute_aggregate_metrics
from .comparisons import ComparisonResult, format_comparison_table
from .llm_analysis import (
    StrategyAnalysis,
    FailureAnalysis,
    MCPUtilizationAnalysis,
    ComparativeNarrative,
    InsightSynthesis,
)


class ReportGenerator:
    """Generate analysis reports in multiple formats."""
    
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def write_metrics_csv(
        self,
        metrics: List[DeterministicMetrics],
        filename: str = "metrics_detail.csv",
    ) -> Path:
        """Write per-trajectory metrics to CSV."""
        path = self.output_dir / filename
        
        if not metrics:
            return path
        
        # Get all field names
        fieldnames = list(metrics[0].to_dict().keys())
        
        with open(path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for m in metrics:
                row = m.to_dict()
                # Convert complex types to strings
                for k, v in row.items():
                    if isinstance(v, (list, dict, set)):
                        row[k] = json.dumps(v) if v else ""
                writer.writerow(row)
        
        return path
    
    def write_summary_csv(
        self,
        metrics_by_profile: Dict[str, List[DeterministicMetrics]],
        filename: str = "metrics_summary.csv",
    ) -> Path:
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
                # Convert complex types
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
    
    def write_comparison_report(
        self,
        comparisons: List[ComparisonResult],
        filename: str = "comparison_report.md",
    ) -> Path:
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
                    pct_key = f"{key}_pct_change"
                    pct = comp.deltas.get(pct_key)
                    pct_str = f" ({pct:+.1f}%)" if pct else ""
                    lines.append(f"- {key}: {delta:+.2f}{pct_str}")
            
            lines.append("\n**Statistical Tests**:")
            for name, test in comp.tests.items():
                sig = "***" if test.significant else ""
                effect = f", effect={test.effect_interpretation}" if test.effect_interpretation else ""
                lines.append(f"- {name}: p={test.p_value:.4f}{sig}{effect}")
        
        path.write_text("\n".join(lines))
        return path
    
    def write_strategy_analysis(
        self,
        analyses: List[tuple[str, str, StrategyAnalysis]],
        filename: str = "strategy_analysis.json",
    ) -> Path:
        """Write strategy analyses to JSON."""
        path = self.output_dir / filename
        
        data = []
        for task_id, profile, analysis in analyses:
            data.append({
                "task_id": task_id,
                "profile": profile,
                "primary_strategy": analysis.primary_strategy,
                "strategy_quality": analysis.strategy_quality,
                "reasoning_coherence": analysis.reasoning_coherence,
                "adaptation_events": analysis.adaptation_events,
                "strengths": analysis.strengths,
                "weaknesses": analysis.weaknesses,
                "key_decisions": analysis.key_decisions,
            })
        
        path.write_text(json.dumps(data, indent=2))
        return path
    
    def write_failure_analysis(
        self,
        analyses: List[tuple[str, str, FailureAnalysis]],
        filename: str = "failure_analyses.json",
    ) -> Path:
        """Write failure analyses to JSON."""
        path = self.output_dir / filename
        
        data = []
        for task_id, profile, analysis in analyses:
            if analysis.root_cause != "not_applicable":
                data.append({
                    "task_id": task_id,
                    "profile": profile,
                    "root_cause": analysis.root_cause,
                    "confidence": analysis.confidence,
                    "critical_step": analysis.critical_step,
                    "critical_step_explanation": analysis.critical_step_explanation,
                    "missed_insight": analysis.missed_insight,
                    "counterfactual": analysis.counterfactual,
                    "contributing_factors": analysis.contributing_factors,
                    "task_specific_difficulty": analysis.task_specific_difficulty,
                })
        
        path.write_text(json.dumps(data, indent=2))
        return path
    
    def write_mcp_analysis(
        self,
        analyses: List[tuple[str, str, MCPUtilizationAnalysis]],
        filename: str = "mcp_utilization.json",
    ) -> Path:
        """Write MCP utilization analyses to JSON."""
        path = self.output_dir / filename
        
        data = []
        for task_id, profile, analysis in analyses:
            data.append({
                "task_id": task_id,
                "profile": profile,
                "utilization_quality": analysis.utilization_quality,
                "init_timing": analysis.init_timing,
                "init_quality": analysis.init_quality,
                "dependency_leverage": analysis.dependency_leverage,
                "search_effectiveness": analysis.search_effectiveness,
                "structural_understanding": analysis.structural_understanding,
                "missed_opportunities": analysis.missed_opportunities,
                "effective_uses": analysis.effective_uses,
                "recommendation": analysis.recommendation,
            })
        
        path.write_text(json.dumps(data, indent=2))
        return path
    
    def write_comparative_narratives(
        self,
        narratives: List[tuple[str, ComparativeNarrative]],
        filename: str = "comparative_narratives.md",
    ) -> Path:
        """Write comparative narratives as markdown."""
        path = self.output_dir / filename
        
        lines = [
            "# Comparative Narratives",
            f"\nGenerated: {datetime.now().isoformat()}",
        ]
        
        for task_id, narrative in narratives:
            lines.extend([
                f"\n## {task_id}\n",
                f"**Winner**: {narrative.winner}",
                f"\n**Reason**: {narrative.winner_reason}\n",
                "\n### Performance Delta\n",
            ])
            
            for key, val in narrative.performance_delta.items():
                lines.append(f"- **{key}**: {val}")
            
            lines.extend([
                f"\n### Exploration Comparison\n{narrative.exploration_comparison}",
                f"\n### Key Insight\n> {narrative.key_insight}",
                f"\n### Paper-Ready Paragraph\n{narrative.narrative_paragraph}",
            ])
            
            if narrative.quote_worthy_moment:
                lines.append(f"\n### Quote-Worthy Moment\nStep {narrative.quote_worthy_moment.get('step')}: {narrative.quote_worthy_moment.get('description')}")
        
        path.write_text("\n".join(lines))
        return path
    
    def write_synthesis(
        self,
        synthesis: InsightSynthesis,
        filename: str = "synthesis.md",
    ) -> Path:
        """Write insight synthesis as markdown."""
        path = self.output_dir / filename
        
        lines = [
            "# Cross-Run Insight Synthesis",
            f"\nGenerated: {datetime.now().isoformat()}",
            "\n## Task Difficulty Ranking\n",
        ]
        
        for item in synthesis.task_difficulty_ranking:
            lines.append(f"- **{item.get('task')}** ({item.get('difficulty')}): {item.get('reason')}")
        
        lines.extend([
            "\n## MCP Benefit Patterns\n",
            *[f"- {p}" for p in synthesis.mcp_benefit_patterns],
            "\n## MCP Overhead Patterns\n",
            *[f"- {p}" for p in synthesis.mcp_overhead_patterns],
            "\n## Emergent Findings\n",
            *[f"- {f}" for f in synthesis.emergent_findings],
            "\n## Recommended Improvements\n",
        ])
        
        for item in synthesis.recommended_improvements:
            lines.append(f"- **{item.get('tool')}**: {item.get('improvement')}")
        
        lines.extend([
            "\n## Paper Claims\n",
        ])
        
        for claim in synthesis.paper_claims:
            conf = claim.get('confidence', 'medium')
            lines.extend([
                f"\n### Claim ({conf} confidence)",
                f"> {claim.get('claim')}",
                f"\n**Evidence**: {claim.get('evidence')}",
            ])
        
        lines.extend([
            "\n## Limitations\n",
            *[f"- {l}" for l in synthesis.limitations],
            "\n## Future Work\n",
            *[f"- {f}" for f in synthesis.future_work],
        ])
        
        path.write_text("\n".join(lines))
        return path
    
    def write_paper_snippets(
        self,
        synthesis: InsightSynthesis,
        narratives: List[tuple[str, ComparativeNarrative]],
        aggregate_metrics: Dict[str, Dict[str, Any]],
        filename: str = "paper_snippets.md",
    ) -> Path:
        """Write ready-to-use paper snippets."""
        path = self.output_dir / filename
        
        lines = [
            "# Paper Snippets",
            "\n## Results Section\n",
        ]
        
        # Aggregate results paragraph
        if aggregate_metrics:
            profiles = list(aggregate_metrics.keys())
            if len(profiles) >= 2:
                p1, p2 = profiles[0], profiles[1]
                m1, m2 = aggregate_metrics[p1], aggregate_metrics[p2]
                
                lines.append(f"""
Our evaluation compared {p1} (n={m1.get('count', 0)}) against {p2} (n={m2.get('count', 0)}) 
across {len(set(m1.get('task_distribution', {}).keys()) | set(m2.get('task_distribution', {}).keys()))} tasks. 
The {p1} configuration achieved {m1.get('success_rate', 0):.1f}% success rate 
with average cost of ${m1.get('avg_cost', 0):.4f}, while {p2} achieved 
{m2.get('success_rate', 0):.1f}% success rate at ${m2.get('avg_cost', 0):.4f} average cost.
""")
        
        # Narrative paragraphs
        lines.append("\n## Per-Task Narratives\n")
        for task_id, narrative in narratives:
            lines.extend([
                f"### {task_id}\n",
                narrative.narrative_paragraph,
                "",
            ])
        
        # Key insights
        lines.append("\n## Key Insights\n")
        for task_id, narrative in narratives:
            if narrative.key_insight:
                lines.append(f"- **{task_id}**: {narrative.key_insight}")
        
        # Claims
        lines.append("\n## Supported Claims\n")
        for claim in synthesis.paper_claims:
            if claim.get('confidence') == 'high':
                lines.append(f"- {claim.get('claim')}")
        
        path.write_text("\n".join(lines))
        return path
