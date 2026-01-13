## Summary
Implement a TB-optimized, simpler pipeline:
1) Default repo root anchor to `/app`.
2) Derive an **effective content root** for labeling + scanning:
   - if `/app` has exactly one “project” subtree, label relative to that;
   - if multiple, preserve the top-level folder prefixes.
3) Move `.codecanvas` artifacts **outside `/app`** via an explicit artifact-root setting.
4) Make LSP warmup **per-language + full-scan-driven** so TS can’t poison Python.

This matches your decisions and removes the earlier deep/heuristic root-resolution logic from the hot path.

---

## 0) Key design clarifications (aligning with your decisions)
### Repo root vs content root
- **Repo root (execution anchor):** `/app` (TB guarantee).
- **Content root (label base + language scan base):** derived from `/app` top-level structure.
  - If there’s only one meaningful project root under `/app` (any nesting), treat that as the label base.
  - If multiple distinct project roots exist, preserve prefixes for clarity.

### Artifact root outside `/app`
- Introduce a single canonical “artifact root” (outside `/app`) used for all `.codecanvas` files.
- This avoids verifier complaints and prevents `.codecanvas` from polluting scans.

---

## 1) Root / labeling behavior (simple, no deep heuristics)
### 1.1 Default root
- In hooks, set project root to `/app` when it exists; otherwise fallback to `cwd`.
- Keep the older complex workspace resolution code **disabled** (commented out / behind a single toggle) per your instruction.

### 1.2 Content-root detection for labeling (lightweight, top-level)
Compute “project roots” as:
- Immediate children of `/app` that contain any project marker (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `.git`, …).

Rules:
- If **0** candidate project roots: labels are relative to `/app`.
- If **1** candidate project root: labels drop that prefix (labels become relative to that directory).
- If **2+** roots: keep prefixes (`pyknotid/...`, `bobscalob/...`) for clarity.

This satisfies your “single subdir → strip prefix; multiple → preserve” rule without needing recursive “best root” heuristics.

---

## 2) Artifact dir outside `/app` (clean decoupling)
### 2.1 New configuration
- Add `CANVAS_ARTIFACT_DIR` (absolute path).
- In TB/hook context, set it to something outside `/app` (e.g. `${CLAUDE_CONFIG_DIR}/codecanvas/canvas` if available, else `/tmp/codecanvas`).

### 2.2 Centralize path resolution
Add a single helper (e.g. `codecanvas/core/paths.py`) that resolves:
- `project_root` (for scanning/parsing) — `/app`.
- `artifact_root` (for state + evidence) — from `CANVAS_ARTIFACT_DIR`.

Then update all `.codecanvas` reads/writes to use `artifact_root`.

### 2.3 Keep session mirroring working
Update the “sync artifacts to session” logic to copy from `artifact_root` (not `${project_root}/.codecanvas`).

---

## 3) Full language presence scan (repo-sized, unbounded)
### 3.1 What we scan
- Scan the effective content scope under `/app`:
  - If single project root exists → scan only that subtree.
  - If multiple roots → scan each subtree.
  - If none → scan `/app`.

### 3.2 How we scan
- Full walk (not bounded) because TB repos aren’t huge.
- Ignore known-noise dirs: `.git`, `.codecanvas`, `node_modules`, `.venv`, `venv`, `__pycache__`, etc.
- Use existing extension→lang mapping from `codecanvas/parser/config.py`.

Output: `present_langs: set[str]`.

---

## 4) Per-language warmup state + warm only what’s present
### 4.1 Warmup state schema (`lsp_warmup.json`)
Replace single `status` with per-language statuses:
```json
{
  "root": "/app",
  "content_roots": ["/app/pyknotid"],
  "updated_at": 123,
  "langs": {
    "py": {"status": "ready|running|failed|skipped", "elapsed_s": 1.2, "error": null},
    "ts": {"status": "skipped", "reason": "no_files"}
  },
  "overall": "ready|partial|failed"
}
```

### 4.2 Warmup execution
- Determine `warm_langs = present_langs ∩ LSP_SUPPORTED_LANGUAGES`.
- Warm each language independently (separate try/except + timeout), recording success/failure per lang.
- Do **not** require TS warmup if no TS files.

### 4.3 How warmup influences init (no jank)
- Warmup becomes an **enabler**, not a global gate.
- If `py` warmup is ready → allow Python LSP.
- If `ts` warmup failed/skipped → do not attempt TS LSP.

To make that last line possible cleanly, we need selective LSP enablement:

---

## 5) Selective LSP enablement (clean, avoids TS poisoning Python)
### 5.1 Extend init API
Extend `canvas_action(init)` / parser init to accept `lsp_langs` (allowed set), e.g.:
- `use_lsp: bool` (existing)
- `lsp_langs: list[str] | None` (new)

### 5.2 Parser behavior
- If `use_lsp` is false → tree-sitter only.
- If `use_lsp` true and `lsp_langs` provided → attempt LSP only for those languages; everything else uses tree-sitter.

### 5.3 Hook behavior
- Build `lsp_langs` from warmup results (only `status==ready`).
- Init with `use_lsp = bool(lsp_langs)`.

This is the “for good” fix: warmup failures for one language never disable LSP for another.

---

## 6) What gets simplified/removed
- The previous deep `resolve_workspace_root(...)` logic is disabled/commented out for TB runs per your request; the system uses `/app` + the top-level project-root heuristic only.
- Warmup no longer tries to warm TS on Python-only repos.

---

## 7) Tests / validation
- Unit tests for:
  - content-root detection (single vs multi project roots under `/app`)
  - label normalization (prefix strip vs preserve)
  - artifact root path resolution
  - language presence scan (full scan)
  - warmup state schema + per-language statuses
  - selective LSP enabling in parser (`lsp_langs`)
- Run `ruff check codecanvas` and `pytest`.
- Rerun TB `build-cython-ext` and confirm:
  - `lsp_warmup.json` shows `py=ready` (and `ts=skipped` if no TS)
  - `state.json` shows `use_lsp=true` and `lsp_files>0`.

---

## Implementation steps (high level)
1) Add artifact-root plumbing (`CANVAS_ARTIFACT_DIR`) + central path resolver.
2) Update all `.codecanvas` reads/writes + session artifact mirroring to use artifact root.
3) Implement `/app`-anchored content-root detection and label normalization rules.
4) Add full language scan and per-language warmup state.
5) Add `lsp_langs` to init/parser to enable LSP selectively.
6) Tests + TB rerun verification.
