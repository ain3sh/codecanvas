# Cross-Run Insight Synthesis

Generated: 2025-12-23T05:21:32.511280

## Task Difficulty Ranking

- **custom-memory-heap-crash** (easy): Uniform success across all profiles (codecanvas/codegraph/text all SUCCESS), suggesting the task is solvable with standard debugging workflows independent of profile/tooling.
- **modernize-scientific-stack** (easy): Uniform success across all profiles (all SUCCESS), indicating well-trodden dependency/compatibility upgrades with clear feedback loops.
- **fix-code-vulnerability** (medium): Mixed outcomes (codegraph and text SUCCESS; codecanvas FAIL) imply solvable but sensitive to strategy/tooling; systematic exploration profiles performed better than grep-and-fix here.
- **build-cython-ext** (medium): Only text succeeded while both MCP-enabled profiles failed, indicating moderate complexity with environment/build-chain pitfalls where extra tooling did not translate into higher success.
- **sanitize-git-repo** (hard): All profiles failed (all FAIL), consistent with tasks requiring precise, multi-step history rewriting and verification where errors are easy to make and hard to validate.
- **db-wal-recovery** (hard): All profiles failed (all FAIL), suggesting specialized domain knowledge and/or careful procedural correctness not achieved by any profile in these runs.
- **rstan-to-pystan** (hard): All profiles failed (all FAIL), consistent with high complexity migration work (API, statistical modeling semantics, and dependency ecosystem changes) that exceeded current agent capabilities in this setting.

## MCP Benefit Patterns

- Possible benefit in vulnerability fixing when paired with systematic exploration: codegraph (systematic_exploration) succeeded on fix-code-vulnerability while codecanvas (grep_and_fix) failed, suggesting that structured repository-level reasoning (which MCP tools are intended to support) may help when the task requires more than localized edits.
- MCP usage did not prevent success on tasks that were inherently straightforward (custom-memory-heap-crash, modernize-scientific-stack), implying MCP is not necessary for tasks with strong, direct tool-feedback loops and well-defined fixes.

## MCP Overhead Patterns

- Higher interaction and token overhead with MCP-enabled profiles without corresponding success gains: codecanvas had the highest avg_tokens (3,190,841.86) and lowest success_rate (28.57%) despite a 57.14% MCP usage rate and high avg_mcp_calls (5.29).
- Repository-graph tooling appeared underutilized relative to overall tool activity: codegraph had 57.14% MCP usage rate but only 1.14 avg_mcp_calls, while still exhibiting longer avg_elapsed_sec (508.47) than text (281.66), suggesting overhead from tool orchestration/context switching without consistent payoff.
- For build-chain tasks (build-cython-ext), both MCP-enabled profiles failed while text succeeded, indicating MCP layers can add friction when rapid iteration on compiler/build errors is required.

## Emergent Findings

- The no-MCP 'text' profile outperformed MCP-enabled profiles on both success_rate (57.14% vs 42.86% codegraph vs 28.57% codecanvas) and efficiency (lowest avg_tokens 1,774,353.14; lowest avg_steps 59.00; lowest avg_elapsed_sec 281.66), contradicting the expectation that richer MCP tooling automatically improves outcomes.
- Success was more aligned with strategy choice than with tool richness: tasks labeled hypothesis_driven or systematic_exploration tended to succeed when the problem had clear diagnostic signals (heap crash, stack modernization), whereas grep_and_fix did not reliably rescue tasks requiring global correctness (e.g., sanitize-git-repo).
- Codecanvas exhibited substantially higher backtracking (avg_backtrack_count 4.86) than text (1.29) and codegraph (2.57), suggesting that certain UI/representation choices may increase rework even when tool access is broader.

## Recommended Improvements

- **mcp__codecanvas__canvas**: Add mechanism to produce compact, action-prioritized diffs/next-steps (e.g., top-3 hypotheses + required file edits) to reduce token-heavy narrative exploration; enforce a tighter summarize-and-act loop when repeated backtracking is detected.
- **mcp__codegraph__init_repository**: Make repository initialization outputs more directly actionable by returning a short 'navigation plan' (key modules, entry points, likely files) and caching across steps to reduce repeated context-building overhead.
- **mcp__codegraph__get_dependencies**: Surface dependency conflicts as ranked fix suggestions (e.g., minimum version sets, known migration paths) and provide an 'apply patch' option for common upgrade patterns to better support modernization/build tasks.
- **mcp__codegraph__search_code**: Integrate semantic search results with grep outputs (dedupe, rank, show call chains) so the agent does fewer redundant Grep/Read cycles and can jump to root-cause locations faster.
- **Grep**: Add structured grep templates for common task types (security fix, build failure, WAL recovery, history rewrite) and automatic expansion to adjacent context (imports/callers/tests) to reduce trial-and-error navigation.
- **Bash**: Introduce a standardized build/debug script harness per task type (e.g., build-cython-ext) that captures compiler output, environment state, and minimal repro logs in a single artifact to accelerate iterative fixes.

## Paper Claims


### Claim (medium confidence)
> In this benchmark, a lightweight text-centric workflow achieved higher success and lower resource use than MCP-augmented profiles.

**Evidence**: Success rates: text 57.14% (4/7) vs codegraph 42.86% (3/7) vs codecanvas 28.57% (2/7). Efficiency: text avg_tokens 1,774,353.14 vs codegraph 2,481,492.86 vs codecanvas 3,190,841.86; text avg_elapsed_sec 281.66 vs codegraph 508.47 vs codecanvas 479.90; text avg_steps 59.00 vs 76.29 vs 80.29.

### Claim (high confidence)
> Some tasks form a clear 'unsolved set' across all profiles, indicating task-intrinsic difficulty dominates tooling differences.

**Evidence**: sanitize-git-repo: all FAIL; db-wal-recovery: all FAIL; rstan-to-pystan: all FAIL (3 tasks × 3 profiles = 9/9 failures).

### Claim (high confidence)
> Tooling overhead can manifest as higher tokens and backtracking without improved success, especially in canvas-based MCP interaction.

**Evidence**: codecanvas has lowest success_rate (28.57%) yet highest avg_tokens (3,190,841.86) and highest avg_backtrack_count (4.86) with 57.14% MCP usage rate and avg_mcp_calls 5.29.

### Claim (medium confidence)
> Strategy choice appears correlated with success on tasks requiring broader reasoning, while localized grep-and-fix is insufficient for globally constrained tasks.

**Evidence**: sanitize-git-repo labeled grep_and_fix across all profiles and all failed; fix-code-vulnerability succeeded for codegraph/text with systematic_exploration while codecanvas (grep_and_fix) failed.

## Limitations

- Small sample size per profile (n=7) and per task (single outcome per profile), preventing robust statistical inference and making results sensitive to run-to-run variability.
- Outcomes are aggregated without per-run confidence intervals, error types, or partial-credit scoring; binary success may obscure meaningful progress differences.
- MCP usage is measured coarsely (usage rate and call counts) without attributing causal impact (e.g., which specific MCP call changed the chosen edit).
- Costs are reported as 0.00, so cost-effectiveness conclusions cannot be drawn; token counts may not be comparable if logging differs across profiles.
- Task set mixes heterogeneous domains (security, builds, DB recovery, VCS history rewriting, statistical stack migration), limiting generalization about any single domain.

## Future Work

- Run a controlled ablation study within the same profile: identical prompts with MCP disabled vs enabled, holding strategy constant, to isolate MCP causal effects on success and efficiency.
- Increase repetitions per (task, profile) to estimate variance and compute statistically meaningful differences in success_rate and time/tokens.
- Add fine-grained outcome labeling (root-cause identified, fix implemented, tests passing, regression introduced) to move beyond binary success and better explain failures in the 'unsolved set'.
- Instrument tool-level traces to measure redundancy (e.g., repeated Grep/Read cycles), and evaluate interventions like semantic search ranking, caching, and auto-generated minimal repro scripts.
- Introduce task-specific expert baselines or scaffolds (e.g., guided WAL recovery checklist, git filter-repo playbook, Stan migration map) to determine whether failures are due to missing domain knowledge vs orchestration limitations.