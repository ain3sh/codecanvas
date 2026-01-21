## Overview

Replace our custom 450-line LSP client (`parser/lsp.py`) with Microsoft's `multilspy` library, which provides:
- Auto-download of platform-specific LSP binaries
- Tested/maintained by Microsoft Research (NeurIPS 2023)
- Support for 11 languages out of the box
- Same API pattern we already use

## Language Support Matrix

| Language | Current | Multilspy | Action |
|----------|---------|-----------|--------|
| Python | basedpyright | jedi | Use multilspy (can override later) |
| TypeScript/JS | typescript-language-server | tsserver | Use multilspy |
| Go | gopls | gopls | Use multilspy |
| Rust | rust-analyzer | rust-analyzer | Use multilspy |
| Java | jdtls | Eclipse JDTLS | Use multilspy |
| Ruby | solargraph | Solargraph | Use multilspy |
| C/C++ | clangd | clangd | Use multilspy |
| C# | - | OmniSharp | NEW via multilspy |
| Kotlin | - | Kotlin LSP | NEW via multilspy |
| Dart | - | Dart LSP | NEW via multilspy |
| **Bash/Shell** | bash-language-server | NOT SUPPORTED | Keep custom fallback |
| **R** | languageserver | NOT SUPPORTED | Keep custom fallback |

## File Changes

### 1. `pyproject.toml`
Add `multilspy>=0.0.15` to codecanvas dependencies.

### 2. `parser/lsp.py` → Refactor to Adapter Pattern (~200 lines, down from 450)

```python
# New structure:
class LspBackend(Protocol):
    """Unified LSP backend interface."""
    async def document_symbols(self, path: str) -> List[DocumentSymbol]
    async def definition(self, path: str, line: int, char: int) -> List[Location]

class MultilspyBackend(LspBackend):
    """Wraps multilspy for 11 supported languages."""
    SUPPORTED = {"py", "ts", "go", "rs", "java", "rb", "c", "cs", "kotlin", "dart"}
    
class CustomLspBackend(LspBackend):
    """Our slim fallback for Bash and R only."""
    SUPPORTED = {"sh", "r"}

def get_lsp_backend(lang: str, workspace: str) -> LspBackend:
    """Route to appropriate backend based on language."""
```

### 3. `parser/config.py` - Simplify
- Remove `LANGUAGE_SERVERS` entries for multilspy-supported languages (9 languages)
- Keep only `sh` and `r` entries for custom fallback
- Update `EXTENSION_TO_LANG` to include new languages (C#, Kotlin, Dart)

### 4. `install-claude-code-mcp.sh.j2` - Dramatic Simplification

**Remove** (handled by multilspy auto-download):
- rust-analyzer download
- Go + gopls installation
- jdtls tar.gz + wrapper script
- solargraph gem install
- typescript-language-server npm

**Keep** (for custom fallback):
- `clangd` from apt (multilspy also uses it, but apt is faster than download)
- `bash-language-server` from npm
- `r-base` + R languageserver

**Add**: Multilspy warmup step to pre-cache binaries during container build:
```bash
python3 -c "
from multilspy import SyncLanguageServer
from multilspy.multilspy_config import MultilspyConfig
import tempfile, os

for lang in ['java', 'python', 'rust', 'typescript', 'go', 'ruby', 'cpp', 'csharp', 'kotlin']:
    try:
        config = MultilspyConfig.from_dict({'code_language': lang})
        with tempfile.TemporaryDirectory() as td:
            # Trigger binary download
            lsp = SyncLanguageServer.create(config, None, td)
            with lsp.start_server():
                pass
    except: pass
"
```

### 5. Harbor Install Script Size Reduction

**Before**: ~130 lines with manual downloads, parallel curl, version pinning
**After**: ~60 lines - apt, npm (bash-ls only), R, multilspy warmup

## Benefits

1. **Less code to maintain**: 450 → ~200 lines for LSP layer
2. **Auto-updates**: Multilspy handles LSP binary version management
3. **Platform handling**: Windows/Mac/Linux binaries automatic
4. **New languages free**: C#, Kotlin, Dart without any work
5. **Tested upstream**: Microsoft maintains and tests the library
6. **Faster container builds**: One warmup step vs 6+ parallel downloads

## Python LSP Note

Multilspy uses `jedi-language-server` instead of our `basedpyright`. For symbol extraction (our use case), both work. Jedi is faster; basedpyright has better type inference. We can add a basedpyright override later if needed - the adapter pattern makes this trivial.

## Migration Steps

1. Add multilspy dependency
2. Create adapter layer with MultilspyBackend + CustomLspBackend
3. Update config.py (remove 9 language entries)
4. Simplify Harbor install script
5. Run tests to verify parity
6. Remove old LSPClient/LspSession code

## Risk Mitigation

- Keep custom fallback code for Bash/R (and potential future edge cases)
- Adapter pattern allows easy per-language overrides
- Can revert to basedpyright for Python if jedi proves insufficient