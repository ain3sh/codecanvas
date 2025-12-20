## Goals
1) Eliminate memory spikes by avoiding unnecessary Harbor rebuilds while keeping results fresh for the paper.
2) Add a simple way to run multiple agent config variants (e.g., no-MCP and MCP locagent) in one CLI invocation without extra user complexity.

## Key Facts
- Harbor default `delete=True` does `docker compose down --rmi all --volumes`, so every run rebuilds the heavy image (nvm+node+npm claude-code+uv+pip), causing RAM spikes.
- Functional changes requiring rebuild are limited to install inputs: install template content, claude_version, mcp_git_source (and token presence), not per-run MCP/hook configs.
- MCP/hook configs are already injected at runtime via temp files; they don’t need rebuilds.

## Proposed Changes (backend + UX, minimal surface)
A) **Smart reuse with auto-rebuild**
- Default to `--no-delete` so the built image is kept between runs.
- Compute a build fingerprint (hash) from: `terminalbench/install-claude-code-mcp.sh.j2` content, `claude_version` (if set), `mcp_git_source` string, and presence flag of `github_token` (not the token value). Store in a small cache file (e.g., `.terminalbench/build-hash.json`).
- On each run: if fingerprint changed or cache missing → add `--force-build` once; otherwise reuse. Update cache after decision. This keeps builds fresh when inputs change, without manual flags.
- Optional env escape hatch (no new CLI flags): `TERMINALBENCH_FORCE_REBUILD=1` forces rebuild regardless of hash.

B) **Parallel config executions (single CLI)**
- Extend CLI to accept multiple agent configs in one call via repeated `--config-set` options (or a short `-C`). Each config-set can specify: `--mcp-server` list (or `--no-mcp`), `--hooks`, `--mcp-config`, `--mcp-git-source`, `--reasoning`, `--model`, and a label `--key` (default derived from settings, e.g., `nomcp`, `locagent`).
- The wrapper builds a list of `AgentProfile` objects, one per config-set. If none provided, fall back to current single-profile path (backward compatible).
- Runner executes tasks for each profile sequentially by default (preserving Harbor’s internal `-n` parallelism). Optional `--profiles-parallel N` to run profiles concurrently if desired.
- Results are tagged with profile key in output/CSV/JSON, preserving current schema with an added field if needed; CLI output stays simple (prepend key in logs).

C) **Non-breaking UX**
- Existing single-run usage unchanged; defaults remain sensible.
- No new mandatory flags; multi-config is opt-in via additional `--config-set ...` groups.
- No extra per-invocation complexity for the user; rebuild logic is automatic.

## Validation Plan
- Run two back-to-back single-profile runs; confirm first builds, second reuses (no rebuild logs, flat memory).
- Modify install template or `mcp_git_source`; confirm one rebuild triggers, then reuse.
- Use new multi-config: `--config-set --no-mcp --key nomcp --config-set --mcp-server locagent --key loc` on a single task; verify two Harbor runs fire under one CLI call, both tagged, no forced rebuild between them.

## Deliverables
- Updated wrapper logic (fingerprint + --no-delete/--force-build orchestration).
- Extended CLI and Runner to support multiple profiles in one invocation, with sensible defaults and labeling.
- Documentation inline in code (minimal comments) and brief usage help text for the new option; no README changes unless requested.
