# Paper Snippets

## Results Section

Our evaluation compared codecanvas (n=7) against codegraph (n=7). The codecanvas configuration achieved 57.1% success rate with average cost of $0.0000, while codegraph achieved 42.9% success rate at $0.0000 average cost.

## Per-Task Narratives

### sanitize-git-repo
Both agents identified and edited the same primary leakage points (notably the Ray cluster YAML and the processing script) and performed post-edit verification via grep. However, the MCP-enabled trajectory introduced additional stateful documentation steps and subsequently surfaced residual secret material in an auxiliary tool state file, increasing iteration time and complexity. The text-only trajectory reached comparable remediation actions with fewer operations, suggesting that lightweight workflows may reduce the risk of tool-induced secret persistence while improving efficiency.

### build-cython-ext
Both agents ultimately produced a successful NumPy 2.x-compatible build of pyknotid’s Cython extensions, but Trajectory A reached the working state with fewer tool interactions and less time by attempting compilation early and validating behavior through execution. Trajectory B conducted broader up-front inspection and formalized a plan, yet encountered an “apparently successful” editable install that did not compile extensions, necessitating additional corrective iterations. Notably, Trajectory A’s tight build–test cycle also uncovered and addressed an unrelated Python 3.13 runtime incompatibility during validation, improving end-to-end usability beyond the nominal build objective.

### custom-memory-heap-crash
Across both trajectories, the failure was localized to libstdc++ locale facet cleanup during exit, consistent with a teardown-time use-after-free of allocator state. Trajectory A arrived at this model through more extensive source forensics and then explored lifecycle-hook remedies under code-modification constraints. Trajectory B achieved the same endpoint more quickly by foregrounding the NDEBUG-controlled switch between malloc/free and new/delete in facet management, yielding a more direct explanation for the RELEASE-only crash and a tighter path to mitigation.

### db-wal-recovery
Both trajectories started with a conventional recovery workflow—querying the base database state, inspecting schema, and attempting to hex-dump the WAL—before encountering the same critical failure: the WAL file disappeared during investigation, eliminating access to uncheckpointed changes. Trajectory A responded with a longer, more granular forensic exploration of the main database file and cautious copying, while Trajectory B pivoted more quickly to broad searches and header-level checks; neither could reconstruct the missing records, but B reached the impasse with substantially less interaction cost.

### modernize-scientific-stack
Both agents successfully ported the legacy Python 2.7 climate analysis workflow to Python 3 by inspecting the same three inputs (script, CSV, and configuration) and then producing a modernized script plus a requirements file, validated by executing the new entry point. However, Trajectory A reached completion with marginally fewer steps and tool calls, reflecting a more direct read→implement→run loop. Trajectory B’s repeated explicit task-tracking (TodoWrite) introduced small overhead without altering the final outcome, suggesting planning granularity can be tuned to the complexity of the migration.

### rstan-to-pystan
Trajectory A achieved a successful RStan-to-PyStan conversion by iteratively executing the generated script, identifying a PyStan 3 API mismatch, applying a targeted edit, and rerunning until completion, followed by explicit output-file verification. Trajectory B performed similar initial reading and script generation steps and encountered the same control-parameter issue, but stopped after making an edit without demonstrating a successful rerun or validating produced artifacts. The results suggest that execution-driven iteration and artifact checks, while increasing step count and wall time, materially improve end-to-end task success.

### fix-code-vulnerability
Both trajectories identified plausible security issues in Bottle (notably path traversal risk in `static_file` and unsafe deserialization via `pickle.loads`), yet neither produced a completed remediation with confirmed test success. Trajectory A converged more quickly by combining targeted greps with MCP CodeCanvas symbol-level analysis, while Trajectory B emphasized broader manual exploration through shell enumeration and sequential reads. The results suggest MCP-based summarization improves exploratory efficiency, but robust end-to-end repair still depends on translating findings into concrete patches and verification.


## Key Insights

- **sanitize-git-repo**: Adding an external planning/state layer (MCP canvas) can inadvertently create a new secret-bearing surface (tool state) that complicates sanitization and may negate otherwise-correct code edits.
- **build-cython-ext**: In build/compatibility tasks, an early “compile-and-run a minimal import/test” probe tends to dominate extensive static inspection because it quickly reveals whether the toolchain actually produced binary extensions and surfaces any latent runtime breakages.
- **custom-memory-heap-crash**: The crash occurs during process teardown when libstdc++ locale facet destructors attempt to delete memory allocated via operator new in RELEASE (thus routed to the custom heap), after the application has already destroyed that heap—whereas DEBUG uses malloc/free and sidesteps the custom allocator entirely.
- **db-wal-recovery**: When WAL-based recovery is attempted in-place, simply opening the database with standard SQLite tooling can eliminate the very evidence needed for recovery via checkpointing or WAL file deletion, making immutable snapshots a prerequisite for reliable experimentation.
- **modernize-scientific-stack**: When the migration surface is small and well-bounded, plan-heavy scaffolding (frequent todo updates) can add measurable overhead without improving solution quality relative to a direct read→write→test loop.
- **rstan-to-pystan**: In code translation tasks with evolving library APIs (PyStan 3 control/parameter semantics), iterative execution with explicit post-run verification is a stronger predictor of success than faster, linear code generation.
- **fix-code-vulnerability**: MCP-assisted semantic summarization can improve time-to-hypothesis in large single-file codebases, but neither approach translated hypotheses (path traversal/symlink edge cases, unsafe deserialization) into validated patches and passing tests, highlighting the remaining gap between detection and repair.

## Supported Claims

- Higher token/tool/step consumption does not reliably translate into higher task success, indicating diminishing returns from unstructured exploration.
- Some tasks are intrinsically hard for all profiles and require new domain-specific strategies rather than tool/profile tuning.