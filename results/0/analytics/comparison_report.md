# Profile Comparison Report

Generated: 2025-12-22T14:10:42.163863

## Summary Table

| Task | Profile A | Profile B | Success A | Success B | Delta | p-value | Effect |
|------|-----------|-----------|-----------|-----------|-------|---------|--------|
| All | codecanvas | codegraph | 57.1% | 42.9% | -14.3% | 0.593 | small |
| sanitize-git-repo | codecanvas | codegraph | 0.0% | 0.0% | +0.0% | 1.000 | negligible |
| build-cython-ext | codecanvas | codegraph | 100.0% | 100.0% | +0.0% | 1.000 | negligible |
| custom-memory-heap-crash | codecanvas | codegraph | 100.0% | 100.0% | +0.0% | 1.000 | negligible |
| db-wal-recovery | codecanvas | codegraph | 0.0% | 0.0% | +0.0% | 1.000 | negligible |
| modernize-scientific-stack | codecanvas | codegraph | 100.0% | 100.0% | +0.0% | 1.000 | negligible |
| rstan-to-pystan | codecanvas | codegraph | 100.0% | 0.0% | -100.0% | 0.157 | large |
| fix-code-vulnerability | codecanvas | codegraph | 0.0% | 0.0% | +0.0% | 1.000 | negligible |

## Detailed Comparisons


### All Tasks: codecanvas vs codegraph

**Sample Sizes**: n_a=7, n_b=7


**Key Deltas** (B - A):
- success_rate: -14.29 (-25.0%)
- avg_tokens: -481936.14 (-18.5%)
- avg_cost: +0.00
- avg_steps: -11.71 (-16.1%)
- avg_tool_calls: -5.29 (-12.4%)
- avg_unique_tools: -0.43 (-8.8%)
- avg_elapsed_sec: -128.92 (-30.4%)
- mcp_usage_rate: -28.57 (-100.0%)
- avg_mcp_calls: -2.14 (-100.0%)

**Statistical Tests**:
- success_rate: p=0.5930, effect=small

### sanitize-git-repo: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +0.00
- avg_tokens: -1713699.00 (-58.3%)
- avg_cost: +0.00
- avg_steps: -27.00 (-36.0%)
- avg_tool_calls: -16.00 (-31.4%)
- avg_unique_tools: -2.00 (-28.6%)
- avg_elapsed_sec: -80.97 (-35.4%)
- mcp_usage_rate: -100.00 (-100.0%)
- avg_mcp_calls: -4.00 (-100.0%)

**Statistical Tests**:
- success_rate: p=1.0000, effect=negligible
- tokens: p=1.0000
- steps: p=1.0000

### build-cython-ext: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +0.00
- avg_tokens: +910568.00 (+20.7%)
- avg_cost: +0.00
- avg_steps: +2.00 (+1.8%)
- avg_tool_calls: +12.00 (+18.8%)
- avg_unique_tools: +1.00 (+20.0%)
- avg_elapsed_sec: +57.83 (+11.4%)
- mcp_usage_rate: +0.00
- avg_mcp_calls: +0.00

**Statistical Tests**:
- success_rate: p=1.0000, effect=negligible
- tokens: p=1.0000
- steps: p=1.0000

### custom-memory-heap-crash: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +0.00
- avg_tokens: -189052.00 (-9.2%)
- avg_cost: +0.00
- avg_steps: -9.00 (-13.6%)
- avg_tool_calls: -7.00 (-18.4%)
- avg_unique_tools: +0.00
- avg_elapsed_sec: -149.85 (-40.2%)
- mcp_usage_rate: +0.00
- avg_mcp_calls: +0.00

**Statistical Tests**:
- success_rate: p=1.0000, effect=negligible
- tokens: p=1.0000
- steps: p=1.0000

### db-wal-recovery: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +0.00
- avg_tokens: -1505186.00 (-47.5%)
- avg_cost: +0.00
- avg_steps: -24.00 (-25.8%)
- avg_tool_calls: -11.00 (-21.2%)
- avg_unique_tools: +0.00
- avg_elapsed_sec: -139.48 (-31.2%)
- mcp_usage_rate: +0.00
- avg_mcp_calls: +0.00

**Statistical Tests**:
- success_rate: p=1.0000, effect=negligible
- tokens: p=1.0000
- steps: p=1.0000

### modernize-scientific-stack: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +0.00
- avg_tokens: -21337.00 (-7.5%)
- avg_cost: +0.00
- avg_steps: +1.00 (+5.6%)
- avg_tool_calls: +1.00 (+10.0%)
- avg_unique_tools: +0.00
- avg_elapsed_sec: +0.99 (+1.4%)
- mcp_usage_rate: +0.00
- avg_mcp_calls: +0.00

**Statistical Tests**:
- success_rate: p=1.0000, effect=negligible
- tokens: p=1.0000
- steps: p=1.0000

### rstan-to-pystan: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: -100.00 (-100.0%)
- avg_tokens: -1247345.00 (-65.7%)
- avg_cost: +0.00
- avg_steps: -28.00 (-49.1%)
- avg_tool_calls: -12.00 (-38.7%)
- avg_unique_tools: +0.00
- avg_elapsed_sec: -656.24 (-66.2%)
- mcp_usage_rate: +0.00
- avg_mcp_calls: +0.00

**Statistical Tests**:
- success_rate: p=0.1573, effect=large
- tokens: p=1.0000
- steps: p=1.0000

### fix-code-vulnerability: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +0.00
- avg_tokens: +392498.00 (+11.2%)
- avg_cost: +0.00
- avg_steps: +3.00 (+3.4%)
- avg_tool_calls: -4.00 (-7.5%)
- avg_unique_tools: -2.00 (-25.0%)
- avg_elapsed_sec: +65.29 (+18.5%)
- mcp_usage_rate: -100.00 (-100.0%)
- avg_mcp_calls: -11.00 (-100.0%)

**Statistical Tests**:
- success_rate: p=1.0000, effect=negligible
- tokens: p=1.0000
- steps: p=1.0000