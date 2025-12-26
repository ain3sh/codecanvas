# Context / Constraints
- `tree-sitter-language-pack` only standardizes **grammar loading** (`get_binding/get_language/get_parser`) and exposes a large `SupportedLanguage` set; it does **not** give a universal semantic AST for “defs/imports/calls”.
- CodeCanvas currently needs exactly three tree-sitter artifacts:
  1) `TsDefinition` (class/func + range + parent_class)
  2) import spec strings (`List[str]`) used to build `EdgeType.IMPORT`
  3) `TsCallSite` (line/char) used to drive LSP `definition` lookups (call graph)
- LSP: after commit `535a66f` you now use multilspy for 10 languages; LSP is great for **definitions** (document symbols) and **resolving callsites** (definition), but there is no portable LSP request for “give me import edges”.

# Answer: should LSP be primary for imports?
**No, keep Tree-sitter/text as primary**.
- The LSP spec doesn’t standardize “list imports / dependencies” for a document; any solution becomes server-specific again.
- Tree-sitter import extraction is fast, deterministic, and already matches your repo-local `resolve_import_label()` logic.
- (Optional future) LSP can be used as a *secondary resolver* for ambiguous/unresolved imports, but not as the primary producer.

# Design goal
Replace `codecanvas/parser/treesitter/__init__.py` + `codecanvas/parser/treesitter/{lang}.py` with a single module `codecanvas/parser/treesitter.py` that:
- preserves the public API (`parse_source`, `definitions_from_parsed`, `import_specs_from_parsed`, `extract_call_sites`, etc.)
- keeps thread-local parser caching
- keeps current test semantics (notably: ignore nested functions)

# Key idea (the “general surface”)
Use Tree-sitter **queries** + a tiny amount of post-processing. Queries are a declarative, grammar-native way to express “things that look like definitions/imports/calls”; the engine is universal, per-language variation is data.

# Resulting directory tree (post-implementation)
## Option 1 (single-file, no new dirs)
```
codecanvas/parser/
  __init__.py
  call_graph.py
  config.py
  lsp.py
  utils.py
  treesitter.py          # NEW (replaces the directory)
  # (deleted) treesitter/ # OLD package removed
```

## Option 2 (cleaner separation of data)
```
codecanvas/parser/
  __init__.py
  call_graph.py
  config.py
  lsp.py
  utils.py
  treesitter.py                 # NEW engine
  treesitter_queries/           # NEW data-only query pack
    python.scm
    javascript.scm
    typescript.scm
    tsx.scm
    go.scm
    rust.scm
    java.scm
    ruby.scm
    c.scm
    cpp.scm
    bash.scm
  # (deleted) treesitter/        # OLD package removed
```

# Implementation plan (common to both options)
## 1) Replace the package with a module
- Delete `codecanvas/parser/treesitter/`.
- Add `codecanvas/parser/treesitter.py`.
- Update `tests/treesitters.py` imports (it currently imports `parser.treesitter.{python,typescript,...}` modules).

## 2) Keep the same core types + parser cache
- Preserve: `TsRange`, `TsDefinition`, `TsCallSite`, `TsParsed`.
- Preserve `parse_source(text, file_path, lang_key)` and the `lang_key -> language-pack language` mapping, but extend mapping for new LSP-era keys where sensible:
  - `cs -> csharp`, `kotlin -> kotlin`, `dart -> dart`, `r -> r` (all supported by language-pack).

## 3) Universal query runner + normalizer
- Compile per-language queries via `Language.query()` and execute via `QueryCursor`.
- Standard capture names used by the engine:
  - `@cc.def.class.node`, `@cc.def.class.name`
  - `@cc.def.func.node`, `@cc.def.func.name`
  - `@cc.import.spec`
  - `@cc.call.target`
- Normalization rules (matches current behavior):
  - Build `TsDefinition` from captured nodes; compute `parent_class` by nearest enclosing captured class node.
  - Exclude nested functions by dropping any func whose `@cc.def.func.node` has an ancestor that is also a func node.
  - Callsites use the captured `@cc.call.target` start_point.

## 4) Language coverage to reach parity with today
Ship query/spec coverage for the languages you already test/support:
- Python
- TypeScript / TSX / JavaScript
- Go
- Rust
- Java
- Ruby
- C / C++
- Bash

Where grammars need non-trivial extraction (e.g., C declarators, Go receiver types, Rust impl targets), keep that logic as small helper functions inside the single `treesitter.py` (still “one module”, no per-language files).

## 5) Integrate with existing parser flow
- `Parser` continues to call `import_specs_from_parsed(parsed_ts)` and resolve edges via `resolve_import_label()`.
- `call_graph.py` continues to call `extract_call_sites()` (py/ts). No behavioral change required.

### Optional but strongly recommended (ties directly to your `feat(lsp)` change)
Your `Parser._parse_file()` currently early-returns for `lang == "c"`/`"sh"`/`"r"`, which prevents the new multilspy-backed LSP from ever running for C/C++ and prevents tree-sitter defs fallback for those languages.
- Adjust early-return logic so it only applies to truly “no-TS/no-LSP” cases, or at least so `c` can go through LSP-first as intended.

## 6) Validation
- Run `python3 -m pytest -q`.

# Selection guidance
- **Pick Option 1** if you want the smallest diff and literally a single new module.
- **Pick Option 2** if you want cleaner long-term maintenance (query edits don’t touch Python code) and easier language additions.

If you confirm an option, I’ll implement it end-to-end and keep `tests/treesitters.py` passing.