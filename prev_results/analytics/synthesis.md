# Cross-Run Insight Synthesis

Generated: 2025-12-22T14:27:10.683806

## Task Difficulty Ranking

- **build-cython-ext** (easy): Succeeded for all profiles (codecanvas/codegraph/text all SUCCESS), indicating high solvability under multiple interaction styles.
- **modernize-scientific-stack** (easy): Succeeded for all profiles (all SUCCESS) and was approached via systematic_exploration across profiles, suggesting the task structure is robust to tool/profile differences.
- **custom-memory-heap-crash** (medium): Mixed outcomes (codecanvas SUCCESS, codegraph SUCCESS, text FAIL). Debugging requires correct hypothesis selection; not all profiles converged.
- **fix-code-vulnerability** (medium): Only text succeeded (text SUCCESS; codecanvas/codegraph FAIL), implying that success depends on specific investigative behavior or coverage rather than baseline capability.
- **rstan-to-pystan** (medium): Only codecanvas succeeded (codecanvas SUCCESS; codegraph/text FAIL), suggesting translation/migration complexity where certain tooling/workflow helps but is not universally sufficient.
- **sanitize-git-repo** (hard): All profiles failed (all FAIL) despite all using a similar grep_and_fix approach, indicating deeper pitfalls (e.g., history rewriting edge cases, repo constraints) not resolved by current strategies.
- **db-wal-recovery** (hard): All profiles failed (all FAIL) across differing strategies (hypothesis_driven vs trial_and_error), indicating the benchmark likely requires specialized domain knowledge or nontrivial recovery procedures beyond current workflows.

## MCP Benefit Patterns

- Selective advantage on complex cross-ecosystem migration: codecanvas is the only profile that succeeded on rstan-to-pystan (SUCCESS vs codegraph/text FAIL), and it is also the only profile with MCP usage (mcp_usage_rate 28.57%, avg_mcp_calls 2.14). This suggests MCP-backed canvas/workspace structuring can help coordinate multi-step translation tasks.
- Overall success uplift coincides with MCP availability: codecanvas achieved the highest aggregate success_rate (57.14%) versus codegraph/text (both 42.86%) while being the only profile to use MCP tools.

## MCP Overhead Patterns

- No benefit on uniformly failing tasks: sanitize-git-repo and db-wal-recovery failed for all profiles, including codecanvas, implying MCP/canvas did not overcome core task difficulty and may add interaction overhead without changing outcomes in these domains.
- Potential efficiency cost without commensurate gains on grep_and_fix-style tasks: sanitize-git-repo and fix-code-vulnerability are labeled grep_and_fix for codecanvas, yet codecanvas did not outperform others on those tasks (sanitize-git-repo: all FAIL; fix-code-vulnerability: codecanvas FAIL while text SUCCESS), suggesting canvas structure is not the bottleneck for localized search/patch tasks.

## Emergent Findings

- More interaction does not imply higher success: text has the highest avg_tokens (3342636.57), avg_steps (86.14), avg_tool_calls (53.57), and avg_elapsed_sec (599.86) yet ties for the lowest success_rate (42.86). This indicates additional exploration/backtracking can increase cost/time without improving pass rate.
- Backtracking/looping aligns with inefficiency: text shows higher avg_backtrack_count (4.57) and avg_loop_count (0.86) compared to codecanvas (2.14, 0.14) and codegraph (2.86, 0.14), consistent with longer runtimes and higher token usage without aggregate success gains.
- Success cases are not necessarily shorter in token usage across profiles: codegraph’s avg_tokens_success (2481975.67) exceeds codecanvas (2161188.00) and text (1903308.00), suggesting that when codegraph succeeds it may require more extensive reasoning/verification rather than quick fixes.

## Recommended Improvements

- **Grep**: Increase pre-edit localization rigor: grep_before_edit_rate is only 42.86% for all profiles. Enforce a policy of locating all relevant call sites/definitions (multi-file grep) before the first Edit to reduce mis-edits and backtracking.
- **Bash**: Add structured “diagnostic runbooks” and capture key outputs: Bash dominates tool usage (codecanvas 144, codegraph 93, text 162). Introduce standardized commands per task type (build, test, minimal repro, environment introspection) and automatically summarize failures to prevent repeated ad-hoc reruns.
- **TodoWrite**: Reduce planning churn and tie todos to verification steps: TodoWrite usage is high (31–38). Require each todo item to include an explicit validation command/output expectation, improving convergence and reducing loop/backtrack behavior.
- **mcp__codecanvas__canvas**: Trigger MCP/canvas only for tasks with high dependency coordination (migrations, multi-module refactors). Add a lightweight heuristic classifier to avoid canvas overhead on simple grep_and_fix tasks.
- **Read/Edit**: Promote ‘read-before-edit’ on critical files and add patch scoping: text has very high Reads (81) and Edits (47). Introduce bounded-edit strategies (small diffs, compile/test between edits) to reduce backtracks and long debugging sessions.

## Paper Claims


### Claim (medium confidence)
> MCP-enabled canvas workflows can improve aggregate success rate and may be particularly beneficial for complex migration tasks.

**Evidence**: Only codecanvas uses MCP (mcp_usage_rate 28.57%, avg_mcp_calls 2.14) and it has the highest success_rate (57.14% vs 42.86% for codegraph/text). Additionally, rstan-to-pystan succeeds only under codecanvas (SUCCESS vs FAIL for others).

### Claim (high confidence)
> Higher token/tool/step consumption does not reliably translate into higher task success, indicating diminishing returns from unstructured exploration.

**Evidence**: Text profile: avg_tokens 3342636.57 (highest), avg_steps 86.14 (highest), avg_tool_calls 53.57 (highest), avg_elapsed_sec 599.86 (highest), yet success_rate is 42.86 (tied lowest).

### Claim (high confidence)
> Some tasks are intrinsically hard for all profiles and require new domain-specific strategies rather than tool/profile tuning.

**Evidence**: sanitize-git-repo: FAIL for codecanvas/codegraph/text. db-wal-recovery: FAIL for codecanvas/codegraph/text despite differing analysis styles (hypothesis_driven vs trial_and_error).

### Claim (medium confidence)
> The primary differentiator between profiles is not search behavior prior to edits, as pre-edit grepping is identical across profiles.

**Evidence**: grep_before_edit_rate is 42.86 for codecanvas, codegraph, and text.

### Claim (medium confidence)
> Lower backtracking and looping correlates with improved efficiency and may contribute to better overall outcomes.

**Evidence**: Text shows higher avg_backtrack_count (4.57) and avg_loop_count (0.86) alongside the highest elapsed time (599.86s) and no success advantage (42.86%). Codecanvas shows lower backtracking/looping (2.14, 0.14) with higher success_rate (57.14%).

## Limitations

- Small sample size: only 7 runs per profile (21 total), limiting statistical power and making results sensitive to outliers.
- Task set is heterogeneous (build, migration, security fix, recovery), so aggregate averages (tokens/steps/tool calls) may mix fundamentally different workflows.
- Costs are reported as 0.00 for all profiles, preventing cost-effectiveness comparisons and suggesting missing/disabled accounting.
- MCP usage occurs only in one profile (codecanvas), making it hard to isolate MCP effects from other profile differences.
- Per-task outcomes are binary (SUCCESS/FAIL) without graded measures (partial correctness, time-to-first-fix), potentially obscuring meaningful improvements.

## Future Work

- Run a larger repeated-measures study (multiple seeds per task/profile) to estimate variance and compute significance for success_rate differences.
- Ablate MCP within codecanvas: compare codecanvas with MCP disabled vs enabled to isolate causal impact on success and efficiency.
- Stratify tasks by archetype (grep_and_fix vs hypothesis_driven vs systematic_exploration) and test whether profile/tooling benefits are archetype-specific.
- Introduce enforced workflow policies (e.g., mandatory grep/read-before-edit, bounded edit sizes, test-after-each-edit) and measure changes in backtrack_count, loop_count, and success_rate.
- For the universally failing tasks (sanitize-git-repo, db-wal-recovery), develop domain-specific tool support (specialized git history rewrite checks; WAL forensic/recovery helpers) and re-evaluate performance.