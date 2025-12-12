## Goal
Build a Python harness to run TerminalBench tasks with three agent configs using Claude Code Haiku 4.5 (medium reasoning): text-only baseline, +codegraph, and +codecanvas.

## Plan
1) Clarify benchmark inputs
- Confirm TerminalBench task list from docs and paper; identify task IDs/names and required assets.
- Decide how to invoke tasks (tbench CLI/Harbor instructions) and where to store workspace/output.

2) Environment & dependencies
- Add Python deps: terminalbench/harbor runner, Claude client SDK, CodeGraph/CodeCanvas helpers (reuse existing project modules if present; otherwise add minimal stubs).
- Configuration for Claude Haiku 4.5 with medium reasoning; handle API key via env.

3) Harness structure
- Create module (e.g., `terminal_harness/`) with:
  - Task loader: reads task manifest (YAML/JSON) describing TerminalBench tasks, assets, and time limits.
  - Agent registry: three agent types share a base interface (init, plan, step, observe) with different toolsets.
  - Runner: executes tasks sequentially (or optionally parallel), captures transcripts, metrics (success/fail, steps, tokens, wallclock), and artifacts.
  - Logging: write per-run JSONL plus summary CSV; store traces per agent/task.

4) Agent configurations
- Text-only: standard Claude Code toolset (shell/file ops) only.
- CodeGraph: add graph-query tool wiring to Harbor/tbench if available; otherwise shim using repo graph from task bundle.
- CodeCanvas: add codemap rendering/overlay hooks; ensure deterministic seed; expose visual tool to agent.
- All agents use same prompt scaffolding with role/system messages; set reasoning effort to medium; enforce step/time limits from manifest.

5) CLI entrypoints
- CLI `python -m terminal_harness run --agent {text,graph,canvas} --tasks all|task_id --out out_dir`.
- Optional `--list` to show tasks and `--summary` to aggregate results.

6) Validation
- Add lightweight unit tests for loader/runner/CLI; dry-run mode for agents (mock Claude) to keep tests fast.
- After implementation, run project validators/tests.

## Deliverables
- New harness package with runner, agents, CLI, configs/manifests.
- JSON/CSV output format documented in code docstrings.
- Minimal tests verifying wiring and dry-run behavior.

## Open points
- Need exact TerminalBench task IDs and available graph/canvas hooks from docs; will align during implementation.
- Confirm existing CodeGraph/CodeCanvas modules in repo; reuse instead of new implementations if present.