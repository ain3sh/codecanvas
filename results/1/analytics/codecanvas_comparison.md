# CodeCanvas vs Baselines Comparison

Generated: 2025-12-23T05:07:38.622712

## Informed Editing Score Comparison

| Profile | Runs | Avg Score | Blast Radius Edit Rate | Deliberation Depth |
|---------|------|-----------|------------------------|-------------------|
| codecanvas | 4 | 0.375 | 0.312 | 3.5 |
| codegraph | 7 | N/A | N/A | N/A |
| text | 7 | N/A | N/A | N/A |

## Evidence Board Usage

| Profile | Avg Evidence | Avg Claims | Avg Decisions | Reasoning Density |
|---------|--------------|------------|---------------|-------------------|
| codecanvas | 6.2 | 2.8 | 4.8 | 0.46 |
| codegraph | N/A | N/A | N/A | N/A |
| text | N/A | N/A | N/A | N/A |

## Key Insight

The **Informed Editing Score** measures whether visual impact analysis changed agent behavior:
- **Blast Radius Edit Rate**: % of edits within analyzed impact zones
- **Anticipated Failure Rate**: % of test failures in blast radius (expected)
- **Deliberation Depth**: Claims + decisions made before first edit