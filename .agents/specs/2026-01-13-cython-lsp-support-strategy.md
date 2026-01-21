## Context (local venv reality)
- `multilspy`’s Python backend is `jedi-language-server` (see `/.venv/lib/python3.14/site-packages/multilspy/language_servers/jedi_language_server/jedi_server.py`).
- There is **no Cython LSP server** installed (no `cython-language-server`, no `python-lsp-server`/`pylsp` packages in the venv).
- Therefore, “real” Cython LSP support cannot be enabled without adding a new dependency/binary.

## Goal
Decide how CodeCanvas should behave for `.pyx/.pxd/.pxi` files wrt LSP so that:
- hooks don’t stall,
- parsing/impact works deterministically,
- any LSP use is explicit and safe.

## Option A: No Cython LSP (default)
### Behavior
- `.pyx/.pxd/.pxi` are treated as a distinct language key (e.g. `cython`).
- `has_lsp_support("cython")` is `False` → CodeCanvas never starts LSP for Cython files.
- Tree-sitter parsing is used (aliasing to the `python` grammar as available in `tree_sitter_language_pack`).

### Implementation outline
- `codecanvas/parser/config.py`: add extensions → `"cython"` and include `"cython"` in `TREESITTER_LANGUAGES`.
- `codecanvas/parser/treesitter.py`: map `lang_key == "cython"` → tree-sitter language name `"python"`.
- `codecanvas/parser/utils.py`: treat `lang in {"py", "cython"}` equivalently for `resolve_import_label()`.
- (Optional but recommended) `codecanvas/parser/lsp.py`: map `.pyx/.pxd/.pxi` to `languageId="python"` in `_guess_language_id` only if those files ever reach the custom LSP client.

### Pros/cons
- ✅ Most reliable; avoids jedi parsing unknown syntax.
- ✅ Zero new dependencies.
- ❌ No “go to definition” via LSP for Cython; relies on tree-sitter schemas.

## Option B: Treat Cython as Python LSP (opt-in)
### Behavior
- Default remains Option A.
- If env var (example) `CODECANVAS_CYTHON_USE_PYTHON_LSP=1` is set, `.pyx/.pxd/.pxi` use the Python multilspy backend (jedi).

### Implementation outline
- Keep `lang_key` as `"cython"` for file classification.
- In parser LSP selection (where the `lang` key is used to choose `MultilspyBackend`), special-case:
  - if `lang == "cython"` and env enabled → use `MultilspyBackend("py", workspace_root)`.
- Ensure didOpen `languageId` is `"python"` for these files (multilspy already sends `python`).
- Add strict timeout/cooldown handling to avoid regressions if jedi struggles on Cython syntax.

### Pros/cons
- ✅ Might give partial symbols/defs “for free”.
- ❌ Likely low quality / error-prone on real Cython.
- ❌ Risk of performance issues if jedi chokes on `.pyx`.

## Option C: Custom external Cython LSP (opt-in)
### Behavior
- Default remains Option A.
- If user provides an installed binary via config/env, CodeCanvas uses the existing `CustomLspBackend` mechanism for `cython`.

### Implementation outline
- `codecanvas/parser/config.py`: add `CUSTOM_LSP_SERVERS["cython"]` only if a binary is present, e.g.:
  - command sourced from env `CODECANVAS_CYTHON_LSP_CMD` (JSON array or space-split string), or
  - hardcode `cython-language-server` *only if* it’s installed (checked via `shutil.which`).
- `codecanvas/parser/lsp.py`: extend `_guess_language_id` for `.pyx/.pxd/.pxi` to `"cython"` (or `"python"` depending on the server).

### Pros/cons
- ✅ Best path to “real” Cython LSP if/when such a server is available.
- ✅ Keeps core repo dependency-free.
- ❌ Requires user-managed installation; we can’t validate correctness without the binary.

## Tests / validation (for whichever option you pick)
- Add unit tests around `detect_language()` for `.pyx/.pxd/.pxi` → `"cython"`.
- Add tests ensuring `has_lsp_support("cython")` respects chosen option (env on/off).
- Run `ruff check codecanvas` and `pytest`.

## Recommendation
- Recommend **Option A** as default (reliable), with **Option B or C** only if you explicitly want LSP behavior and accept the risk / manage the server.
