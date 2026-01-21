## Problem Analysis

The install script blindly downloads all 7 multilspy LSP binaries (360s+) regardless of:
1. **Which MCP server is being used** - only `codecanvas` needs multilspy; `locagent`/`codegraph` and `--no-mcp` don't
2. **Which languages are in the task** - downloading Java LSP for a C++ task is wasteful

## Solution: Two-Tier Optimization

### Tier 1: Profile-Based Skip (Zero-Cost for Non-CodeCanvas)

From `pyproject.toml`:
- `codecanvas` extra → includes `multilspy` (needs warmup)
- `locagent` extra → NO `multilspy` (skip warmup entirely)

**In `agent.py`**, detect if codecanvas MCP is enabled:
```python
@property
def _needs_codecanvas(self) -> bool:
    """Check if codecanvas MCP server is configured."""
    if not self.mcp_config:
        return False
    config = json.loads(self.mcp_config) if isinstance(self.mcp_config, str) else self.mcp_config
    return "codecanvas" in config.get("mcpServers", {})
```

Pass to template: `"needs_codecanvas": self._needs_codecanvas`

### Tier 2: Language Detection via `parser/config.py`

When codecanvas IS needed, use CodeCanvas's own language config as the source of truth:

**In template**, generate detection from `EXTENSION_TO_LANG` and `MULTILSPY_LANGUAGES`:

```bash
{% if needs_codecanvas %}
# Detect languages present in /app using CodeCanvas extension mappings
echo "=== Detecting task languages ==="
LANGS=""
# Scan for each extension family (derived from parser/config.py)
[ -n "$(find /app -name '*.py' -type f 2>/dev/null | head -1)" ] && LANGS="$LANGS python"
[ -n "$(find /app \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' \) -type f 2>/dev/null | head -1)" ] && LANGS="$LANGS typescript"
[ -n "$(find /app -name '*.go' -type f 2>/dev/null | head -1)" ] && LANGS="$LANGS go"
# ... etc for rust, java, ruby, cpp, csharp, kotlin, dart

echo "Detected: $LANGS"

# Only warmup detected languages
if [ -n "$LANGS" ]; then
    /opt/venv/bin/python3 -c "
import sys
from multilspy import SyncLanguageServer
from multilspy.multilspy_config import MultilspyConfig
import tempfile, os

langs = '$LANGS'.split()
ext_map = {'python': '.py', 'typescript': '.ts', 'go': '.go', ...}
for lang in langs:
    # warmup only this language
"
fi
{% endif %}
```

### Tier 3: Custom LSP Handling

Per `LANGUAGE_SERVERS` in `parser/config.py`:
- `bash-language-server` → already installed via npm (keep as-is)
- R `languageserver` → only install if `.R`/`.r` files present in `/app`

```bash
{% if needs_codecanvas %}
# R languageserver only if R files present
if [ -n "$(find /app -name '*.R' -o -name '*.r' -type f 2>/dev/null | head -1)" ]; then
    apt-get install -y r-base
    R --slave -e "install.packages('languageserver', ...)" &
fi
{% endif %}
```

### Tier 4: Token Security Fix

Replace URL-embedded token with credential helper (token never written to disk):
```bash
{% if mcp_git_source %}
if [ -n "$GITHUB_TOKEN" ]; then
    git config --global credential.helper '!f() { echo "password=$GITHUB_TOKEN"; }; f'
fi
git clone {{ mcp_git_source }} mcp-repo
{% endif %}
```

## File Changes

| File | Changes |
|------|---------|
| `terminalbench/harbor/agent.py` | Add `_needs_codecanvas` property; add to `_template_variables`; remove `github_token` from template vars |
| `terminalbench/harbor/install-claude-code-mcp.sh.j2` | Wrap LSP warmup in `{% if needs_codecanvas %}`; add language detection; conditional R install; use credential helper |

## Expected Performance

| Profile | Before | After |
|---------|--------|-------|
| `--no-mcp` (baseline) | 360s+ (all LSPs) | ~30s (skip entirely) |
| `--mcp-server codegraph` | 360s+ (all LSPs) | ~45s (skip multilspy) |
| `--mcp-server codecanvas` + C++ task | 360s+ (7 LSPs) | ~60s (cpp only) |
| `--mcp-server codecanvas` + Python task | 360s+ (7 LSPs) | ~50s (python only) |