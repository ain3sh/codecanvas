# Profile Comparison Report

Generated: 2025-12-23T05:07:38.615932

## Summary Table

| Task | Profile A | Profile B | Success A | Success B | Delta | p-value | Effect |
|------|-----------|-----------|-----------|-----------|-------|---------|--------|
| All | codecanvas | codegraph | 28.6% | 42.9% | +14.3% | 0.577 | small |
| sanitize-git-repo | codecanvas | codegraph | 0.0% | 0.0% | +0.0% | 1.000 | negligible |
| build-cython-ext | codecanvas | codegraph | 0.0% | 0.0% | +0.0% | 1.000 | negligible |
| custom-memory-heap-crash | codecanvas | codegraph | 100.0% | 100.0% | +0.0% | 1.000 | negligible |
| db-wal-recovery | codecanvas | codegraph | 0.0% | 0.0% | +0.0% | 1.000 | negligible |
| modernize-scientific-stack | codecanvas | codegraph | 100.0% | 100.0% | +0.0% | 1.000 | negligible |
| rstan-to-pystan | codecanvas | codegraph | 0.0% | 0.0% | +0.0% | 1.000 | negligible |
| fix-code-vulnerability | codecanvas | codegraph | 0.0% | 100.0% | +100.0% | 0.157 | large |

## Detailed Comparisons


### All Tasks: codecanvas vs codegraph

**Sample Sizes**: n_a=7, n_b=7


**Key Deltas** (B - A):
- success_rate: +14.29 (+50.0%)
- avg_tokens: -709349.00 (-22.2%)
- avg_cost: +0.00
- avg_steps: -4.00 (-5.0%)
- avg_tool_calls: -4.00 (-7.9%)
- avg_unique_tools: +1.71 (+35.3%)
- avg_elapsed_sec: +28.57 (+6.0%)
- mcp_usage_rate: +0.00
- avg_mcp_calls: -4.14 (-78.4%)

**Statistical Tests**:
- success_rate: p=0.5770, effect=small

### sanitize-git-repo: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +0.00
- avg_tokens: +1603921.00 (+134.3%)
- avg_cost: +0.00
- avg_steps: +23.00 (+48.9%)
- avg_tool_calls: +20.00 (+62.5%)
- avg_unique_tools: +4.00 (+80.0%)
- avg_elapsed_sec: +65.18 (+42.3%)
- mcp_usage_rate: +0.00
- avg_mcp_calls: -1.00 (-25.0%)

**Statistical Tests**:
- success_rate: p=1.0000, effect=negligible
- tokens: p=1.0000
- steps: p=1.0000

### build-cython-ext: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +0.00
- avg_tokens: -2751605.00 (-46.2%)
- avg_cost: +0.00
- avg_steps: -23.00 (-19.8%)
- avg_tool_calls: -23.00 (-28.7%)
- avg_unique_tools: -1.00 (-14.3%)
- avg_elapsed_sec: -146.90 (-25.6%)
- mcp_usage_rate: -100.00 (-100.0%)
- avg_mcp_calls: -17.00 (-100.0%)

**Statistical Tests**:
- success_rate: p=1.0000, effect=negligible
- tokens: p=1.0000
- steps: p=1.0000

### custom-memory-heap-crash: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +0.00
- avg_tokens: -4855993.00 (-70.6%)
- avg_cost: +0.00
- avg_steps: -68.00 (-49.3%)
- avg_tool_calls: -40.00 (-49.4%)
- avg_unique_tools: +4.00 (+133.3%)
- avg_elapsed_sec: -386.24 (-50.3%)
- mcp_usage_rate: +100.00
- avg_mcp_calls: +1.00

**Statistical Tests**:
- success_rate: p=1.0000, effect=negligible
- tokens: p=1.0000
- steps: p=1.0000

### db-wal-recovery: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +0.00
- avg_tokens: -49140.00 (-1.3%)
- avg_cost: +0.00
- avg_steps: -4.00 (-3.4%)
- avg_tool_calls: -18.00 (-23.7%)
- avg_unique_tools: +1.00 (+50.0%)
- avg_elapsed_sec: +35.58 (+7.6%)
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
- avg_tokens: -229194.00 (-38.5%)
- avg_cost: +0.00
- avg_steps: -6.00 (-21.4%)
- avg_tool_calls: -3.00 (-20.0%)
- avg_unique_tools: +1.00 (+20.0%)
- avg_elapsed_sec: -11.01 (-13.5%)
- mcp_usage_rate: +0.00
- avg_mcp_calls: -3.00 (-60.0%)

**Statistical Tests**:
- success_rate: p=1.0000, effect=negligible
- tokens: p=1.0000
- steps: p=1.0000

### rstan-to-pystan: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +0.00
- avg_tokens: +1133469.00 (+132.0%)
- avg_cost: +0.00
- avg_steps: +11.00 (+28.2%)
- avg_tool_calls: +6.00 (+25.0%)
- avg_unique_tools: +1.00 (+20.0%)
- avg_elapsed_sec: +532.64 (+52.1%)
- mcp_usage_rate: +0.00
- avg_mcp_calls: +0.00

**Statistical Tests**:
- success_rate: p=1.0000, effect=negligible
- tokens: p=1.0000
- steps: p=1.0000

### fix-code-vulnerability: codecanvas vs codegraph

**Sample Sizes**: n_a=1, n_b=1


**Key Deltas** (B - A):
- success_rate: +100.00
- avg_tokens: +183099.00 (+5.9%)
- avg_cost: +0.00
- avg_steps: +39.00 (+51.3%)
- avg_tool_calls: +30.00 (+66.7%)
- avg_unique_tools: +2.00 (+28.6%)
- avg_elapsed_sec: +110.77 (+37.7%)
- mcp_usage_rate: +0.00
- avg_mcp_calls: -9.00 (-81.8%)

**Statistical Tests**:
- success_rate: p=0.1573, effect=large
- tokens: p=1.0000
- steps: p=1.0000