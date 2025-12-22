"""
Profile Comparison - Statistical comparison between profiles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import math

from .deterministic import DeterministicMetrics, compute_aggregate_metrics


@dataclass
class StatisticalTest:
    """Result of a statistical test."""
    test_name: str
    statistic: float
    p_value: float
    significant: bool  # at alpha=0.05
    effect_size: Optional[float] = None
    effect_interpretation: Optional[str] = None


@dataclass 
class ComparisonResult:
    """Result of comparing two profiles."""
    profile_a: str
    profile_b: str
    task_id: Optional[str]  # None for aggregate
    
    # Sample sizes
    n_a: int
    n_b: int
    
    # Metric deltas (B - A)
    deltas: Dict[str, float]
    
    # Statistical tests
    tests: Dict[str, StatisticalTest]
    
    # Aggregate metrics per profile
    metrics_a: Dict[str, Any]
    metrics_b: Dict[str, Any]


class ProfileComparator:
    """Compare profiles with statistical rigor."""
    
    def compare(
        self,
        metrics_a: List[DeterministicMetrics],
        metrics_b: List[DeterministicMetrics],
        profile_a: str,
        profile_b: str,
        task_id: Optional[str] = None,
    ) -> ComparisonResult:
        """Compare two sets of metrics."""
        
        agg_a = compute_aggregate_metrics(metrics_a)
        agg_b = compute_aggregate_metrics(metrics_b)
        
        # Compute deltas (B - A)
        deltas = self._compute_deltas(agg_a, agg_b)
        
        # Statistical tests
        tests = {}
        
        # Success rate comparison (proportion test)
        if len(metrics_a) > 0 and len(metrics_b) > 0:
            tests["success_rate"] = self._proportion_test(
                sum(1 for m in metrics_a if m.success),
                len(metrics_a),
                sum(1 for m in metrics_b if m.success),
                len(metrics_b),
            )
        
        # Token comparison (if paired by task)
        if task_id:
            # Wilcoxon for paired samples
            tokens_a = [m.total_tokens for m in metrics_a]
            tokens_b = [m.total_tokens for m in metrics_b]
            if len(tokens_a) == len(tokens_b) and len(tokens_a) > 0:
                tests["tokens"] = self._wilcoxon_test(tokens_a, tokens_b)
            
            steps_a = [m.total_steps for m in metrics_a]
            steps_b = [m.total_steps for m in metrics_b]
            if len(steps_a) == len(steps_b) and len(steps_a) > 0:
                tests["steps"] = self._wilcoxon_test(steps_a, steps_b)
        
        # Effect size for success rate
        if "success_rate" in tests:
            tests["success_rate"].effect_size = self._cohens_h(
                agg_a.get("success_rate", 0) / 100,
                agg_b.get("success_rate", 0) / 100,
            )
            tests["success_rate"].effect_interpretation = self._interpret_effect_size(
                tests["success_rate"].effect_size
            )
        
        return ComparisonResult(
            profile_a=profile_a,
            profile_b=profile_b,
            task_id=task_id,
            n_a=len(metrics_a),
            n_b=len(metrics_b),
            deltas=deltas,
            tests=tests,
            metrics_a=agg_a,
            metrics_b=agg_b,
        )
    
    def _compute_deltas(
        self,
        agg_a: Dict[str, Any],
        agg_b: Dict[str, Any],
    ) -> Dict[str, float]:
        """Compute metric deltas (B - A)."""
        deltas = {}
        numeric_keys = [
            "success_rate", "avg_tokens", "avg_cost", "avg_steps",
            "avg_tool_calls", "avg_unique_tools", "avg_elapsed_sec",
            "mcp_usage_rate", "avg_mcp_calls",
        ]
        
        for key in numeric_keys:
            val_a = agg_a.get(key, 0) or 0
            val_b = agg_b.get(key, 0) or 0
            if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
                deltas[key] = val_b - val_a
                # Also compute percentage change
                if val_a != 0:
                    deltas[f"{key}_pct_change"] = (val_b - val_a) / val_a * 100
        
        return deltas
    
    def _proportion_test(
        self,
        successes_a: int,
        n_a: int,
        successes_b: int,
        n_b: int,
    ) -> StatisticalTest:
        """Two-proportion z-test."""
        if n_a == 0 or n_b == 0:
            return StatisticalTest(
                test_name="proportion_z_test",
                statistic=0.0,
                p_value=1.0,
                significant=False,
            )
        
        p_a = successes_a / n_a
        p_b = successes_b / n_b
        p_pooled = (successes_a + successes_b) / (n_a + n_b)
        
        if p_pooled == 0 or p_pooled == 1:
            return StatisticalTest(
                test_name="proportion_z_test",
                statistic=0.0,
                p_value=1.0,
                significant=False,
            )
        
        se = math.sqrt(p_pooled * (1 - p_pooled) * (1/n_a + 1/n_b))
        if se == 0:
            return StatisticalTest(
                test_name="proportion_z_test",
                statistic=0.0,
                p_value=1.0,
                significant=False,
            )
        
        z = (p_b - p_a) / se
        
        # Two-tailed p-value approximation
        p_value = 2 * (1 - self._normal_cdf(abs(z)))
        
        return StatisticalTest(
            test_name="proportion_z_test",
            statistic=z,
            p_value=p_value,
            significant=p_value < 0.05,
        )
    
    def _wilcoxon_test(
        self,
        values_a: List[float],
        values_b: List[float],
    ) -> StatisticalTest:
        """Wilcoxon signed-rank test for paired samples."""
        try:
            from scipy.stats import wilcoxon
            stat, p_value = wilcoxon(values_a, values_b, alternative='two-sided')
            return StatisticalTest(
                test_name="wilcoxon_signed_rank",
                statistic=stat,
                p_value=p_value,
                significant=p_value < 0.05,
            )
        except ImportError:
            # Fallback without scipy
            return StatisticalTest(
                test_name="wilcoxon_signed_rank",
                statistic=0.0,
                p_value=1.0,
                significant=False,
                effect_interpretation="scipy not available",
            )
        except Exception:
            return StatisticalTest(
                test_name="wilcoxon_signed_rank",
                statistic=0.0,
                p_value=1.0,
                significant=False,
            )
    
    def _cohens_h(self, p1: float, p2: float) -> float:
        """Cohen's h effect size for proportions."""
        phi1 = 2 * math.asin(math.sqrt(max(0, min(1, p1))))
        phi2 = 2 * math.asin(math.sqrt(max(0, min(1, p2))))
        return abs(phi2 - phi1)
    
    def _interpret_effect_size(self, h: float) -> str:
        """Interpret Cohen's h."""
        if h < 0.2:
            return "negligible"
        elif h < 0.5:
            return "small"
        elif h < 0.8:
            return "medium"
        else:
            return "large"
    
    def _normal_cdf(self, x: float) -> float:
        """Approximation of normal CDF."""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def format_comparison_table(results: List[ComparisonResult]) -> str:
    """Format comparison results as markdown table."""
    lines = [
        "| Task | Profile A | Profile B | Success A | Success B | Delta | p-value | Effect |",
        "|------|-----------|-----------|-----------|-----------|-------|---------|--------|",
    ]
    
    for r in results:
        task = r.task_id or "All"
        success_a = r.metrics_a.get("success_rate", 0)
        success_b = r.metrics_b.get("success_rate", 0)
        delta = r.deltas.get("success_rate", 0)
        
        test = r.tests.get("success_rate")
        p_val = f"{test.p_value:.3f}" if test else "N/A"
        effect = test.effect_interpretation if test else "N/A"
        sig = "*" if test and test.significant else ""
        
        lines.append(
            f"| {task} | {r.profile_a} | {r.profile_b} | "
            f"{success_a:.1f}% | {success_b:.1f}% | "
            f"{delta:+.1f}% | {p_val}{sig} | {effect} |"
        )
    
    return "\n".join(lines)
