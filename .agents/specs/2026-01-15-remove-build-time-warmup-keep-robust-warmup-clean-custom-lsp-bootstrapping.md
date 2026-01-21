## Goals
- Remove the TerminalBench **build-time** “LSP warmup” (multilspy downloads), while keeping LSP reliability.
- Keep/replace the multilspy **download timeout monkeypatch** somewhere appropriate (so clangd/etc downloads don’t fail).
- Replace the “ugly” hardcoded R install logic with a **config-driven, generic** custom-LSP bootstrap mechanism.
- Update `docs/CODECANVAS.md`, `docs/TERMINALBENCH.md`, and `docs/usage/RUNANALYTICS.md` after a deliberate critique + plan.

## Key observations (current state)
- `codecanvas/hooks/lsp_warmup.py` is the right place for runtime prewarming, but it currently only *warms* languages where `has_lsp_support(lang)` is already true; it does not cleanly bootstrap missing custom servers.
- The TerminalBench install script previously:
  - monkeypatched multilspy download timeout (critical for big downloads),
  - downloaded multilspy servers,
  - and installed custom servers (notably R).
- If we remove the install-script warmup entirely, we must ensure:
  - multilspy downloads still don’t time out,
  - and custom servers (R) get installed *somewhere* in a principled way.

## Decision point: where to bootstrap custom LSP servers?
### Option A (safer)
- **Remove build-time multilspy downloads**.
- **Keep build-time custom server installs** when `needs_codecanvas=true` (e.g., install `r-base` + `languageserver`, keep `bash-language-server` via npm).
- SessionStart warmup remains “first-pass” for multilspy only.
- Pros: no apt/network work during SessionStart; fewer runtime surprises.
- Cons: heavier image even if R never used.

### Option B (your request)
- Remove **all** build-time warmup/installs.
- SessionStart hook performs **config-driven bootstrapping** for custom servers *only when needed*.
- Pros: leaner image; installs only when repo needs it.
- Cons: SessionStart can become slow/flaky (apt/network), must be very carefully guarded.

## Implementation plan (common pieces)
1. **Move/keep multilspy download-timeout patch in Python code** (recommended regardless of option)
   - Add a small helper (e.g. `codecanvas/parser/multilspy_patches.py` or inside `codecanvas/parser/lsp.py`) that patches multilspy’s downloader with a configurable timeout.
   - Control via env var `MULTILSPY_DOWNLOAD_TIMEOUT` (default `300`).
   - Ensure the patch is applied **before** multilspy triggers any download (i.e., before creating sessions).
   - This keeps reliability even without install-script warmup.

2. **Replace hardcoded custom install logic with config-driven bootstrap**
   - Extend `codecanvas/parser/config.py` `CUSTOM_LSP_SERVERS` entries to optionally include a `bootstrap` stanza, e.g.:
     - `bootstrap.kind: "apt+r"` (or a generic list of steps)
     - `bootstrap.requires_root: true`
     - `bootstrap.allowed_in_paths: ["/app"]` (TerminalBench guard)
   - In `codecanvas/hooks/lsp_warmup.py`, after scanning `present_langs`, run:
     - `ensure_custom_lsp_ready(lang)` for each present custom lang when `has_lsp_support(lang)` is false.
   - Record bootstrap outcomes in `lsp_warmup.json` so we don’t repeatedly retry apt installs.

3. **Finalize TerminalBench install script changes**
   - Option A: keep only the minimal custom installs (R), remove multilspy warmup.
   - Option B: remove the warmup/install blocks entirely.

4. **Docs update process (disciplined)**
   - For each doc, do: (a) list mismatches vs current code, (b) propose section-level edits, (c) then apply.
   - `docs/CODECANVAS.md`:
     - Clarify SessionStart warmup as “best-effort first-pass”; document latency tradeoff.
     - Document empty-file parsing skip + “LSP empty => per-file tree-sitter defs fallback”.
     - Document artifact dir precedence: `CANVAS_ARTIFACT_DIR` vs `.codecanvas`.
     - Document how custom LSP bootstrap works and how to disable it.
   - `docs/TERMINALBENCH.md`:
     - Fix the `RUNANALYTICS.md` reference to the correct path: `docs/usage/RUNANALYTICS.md`.
     - Update the install/warmup description to match Option A/B.
     - Mention deterministic session-dir selection behavior.
   - `docs/usage/RUNANALYTICS.md`:
     - Verify paths + any references to CodeCanvas artifacts and ensure they match the current `results/` mirror behavior.

5. **Validation + cleanup**
   - Run `uv run ty check --exclude locagent --exclude .factory && uv run ruff check --fix codecanvas terminalbench && uv run pytest`.

## What I need from you
- Pick **Option A** or **Option B**.
- If Option B: confirm you’re OK with SessionStart potentially running `apt-get` in Harbor (guarded to `/app` + root) and that we should add a kill-switch env var (e.g. `CODECANVAS_DISABLE_LSP_INSTALL=1`).