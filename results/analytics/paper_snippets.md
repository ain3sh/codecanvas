# Paper Snippets

## Results Section

Our evaluation compared codecanvas (n=7) against codegraph (n=7). The codecanvas configuration achieved 28.6% success rate with average cost of $0.0000, while codegraph achieved 42.9% success rate at $0.0000 average cost.

## Per-Task Narratives

### sanitize-git-repo
Both trajectories detected and began replacing common credential patterns (AWS keys, GitHub tokens, HuggingFace tokens) but ultimately failed to fully sanitize the repository. Trajectory A prioritized direct regex-based searches and quickly executed edits in the highest-signal files, resulting in fewer steps and lower runtime. Trajectory B broadened discovery using code-graph initialization, dependency inspection, and additional glob-based sweeps across documentation and configuration files, but incurred substantial overhead and still did not complete full repository sanitization.

### build-cython-ext
Across both trajectories, the agents quickly achieved an initial `build_ext --inplace` success under Python 3.13/NumPy 2.3.0, but neither completed an end-to-end confirmation of NumPy 2.x compatibility for the Cython extensions as the primary deliverable. Trajectory A introduced MCP CodeCanvas annotations and decision logging, increasing steps and tool calls, while Trajectory B followed a leaner execution-and-test loop and reached comparable intermediate results faster. Notably, both trajectories subsequently pivoted to fixing a Python-level `fractions.gcd` compatibility issue, suggesting goal drift as a key failure mode independent of tooling.

### custom-memory-heap-crash
Both agents isolated the RELEASE-only segfault to libstdc++ locale cleanup, then traced it to allocator lifetime: facets allocated while the custom heap was active were later freed during global teardown after the heap had been destroyed. Trajectory B achieved the same causal explanation with substantially fewer steps by combining repository initialization and todo-based control of the debugging plan, and by earlier pivoting to a constraint-satisfying remedy confined to user.cpp. Trajectory A reached the correct model as well but incurred additional exploration and replanning overhead before committing to the constraint-compatible solution.

### db-wal-recovery
Both agents began with conventional triage—enumerating database artifacts, querying schema/content, and attempting to inspect the WAL header—but each encountered the same critical anomaly: the WAL file became inaccessible after initial probing. Profile_b converged to a plausible mechanism (SQLite auto-checkpointing on access) with fewer tool invocations, while profile_a invested more in byte-level validation and broader filesystem searches. Neither trajectory operationalized the implication by snapshotting artifacts prior to querying, leading both to fail the recovery/export objective.

### modernize-scientific-stack
Both profiles successfully ported the legacy Python 2.7 climate analysis workflow to a runnable Python 3 script and produced a requirements file, confirming correctness via an execution test. Profile_b completed the task with fewer interactions and lower latency, attributable to an early repository-structure query that streamlined orientation and reduced subsequent coordination overhead. In contrast, profile_a invested additional steps in process instrumentation (claim/decide/mark) and incurred a brief correction cycle, yielding comparable outputs at higher interaction cost.

### rstan-to-pystan
Both agents successfully extracted the Stan/R workflow context and attempted a direct port to PyStan 3.10.0, but neither completed the task end-to-end. Trajectory A was faster and used fewer tool calls, yet it primarily cycled through API inspection and trial invocations without a decisive correction. Trajectory B incurred higher interaction cost but demonstrated stronger recovery behavior by applying a concrete edit aligned with PyStan 3’s interface, reaching an intermediate “sampling running” state despite the final recorded failure.

### fix-code-vulnerability
Trajectory A quickly homed in on likely Bottle hotspots (notably static_file and eval) and referenced a targeted test to reason about path traversal, but it transitioned into planning/report orchestration without demonstrating a completed, validated remediation, culminating in failure. Trajectory B invested more steps and tool calls to systematically enumerate the framework’s security-relevant entry points (cookies, escaping, redirects, uploads, response/error handling) before converging on implementation-relevant loci, yielding a successful end-to-end result. The comparison suggests that, for vulnerability repair tasks, broader early exploration can reduce downstream risk of incomplete fixes despite higher upfront interaction cost.


## Key Insights

- **sanitize-git-repo**: Graph-augmented code search increased breadth of candidate secret locations, but the added initialization and exploration overhead did not translate into end-to-end success in sanitization, highlighting that remediation completeness depends more on systematic verification loops than on richer indexing alone.
- **build-cython-ext**: Adding orchestration/annotation tooling increased operational overhead but did not improve outcome when both agents prematurely shifted from the stated NumPy 2.x Cython-compatibility goal to a broader runtime-compatibility bug (fractions.gcd).
- **custom-memory-heap-crash**: When a custom allocator is torn down before process-wide destructors run, allocations owned by the C++ runtime (e.g., locale facets) can be freed through a now-invalid heap in optimized builds, so the fix must ensure allocator validity through global teardown or prevent runtime allocations while the custom heap is active.
- **db-wal-recovery**: In WAL-recovery tasks, premature interaction with SQLite (even read queries) can change on-disk state via checkpointing, so robust recovery workflows must snapshot WAL/SHM/db files before any access.
- **modernize-scientific-stack**: Specialized structure-aware MCP tooling can measurably reduce end-to-end modernization time by compressing the orientation phase, even when final code outputs and validation steps are equivalent.
- **rstan-to-pystan**: In API-migration tasks, targeted code edits guided by a concise conceptual model of the original program outperform prolonged signature introspection when library interfaces differ subtly but critically.
- **fix-code-vulnerability**: Systematic, breadth-oriented exploration (even with higher tool-call overhead) is more strongly associated with successful vulnerability remediation than early convergence on a small set of suspected hotspots.

## Supported Claims

- Some tasks form a clear 'unsolved set' across all profiles, indicating task-intrinsic difficulty dominates tooling differences.
- Tooling overhead can manifest as higher tokens and backtracking without improved success, especially in canvas-based MCP interaction.