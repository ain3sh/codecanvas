## Parallel LSP Warmup Optimization

### Current State
The warmup in `install-claude-code-mcp.sh.j2` runs sequentially:
```python
for lang in langs:
    # Download + full server start/stop (~10-30s per language)
    lsp = SyncLanguageServer.create(config, logger, td)
    with lsp.start_server():
        pass
```

### Problem Analysis
1. **Sequential execution**: Each language waits for the previous to complete
2. **Full server lifecycle**: `start_server()` does complete initialization, not just binary download
3. **Network bottleneck**: Binary downloads are the slowest part (~100MB total)

### Proposed Changes

**File: `terminalbench/harbor/install-claude-code-mcp.sh.j2`**

Replace the warmup Python block with parallel execution:

```python
from multilspy import SyncLanguageServer
from multilspy.multilspy_config import MultilspyConfig
from multilspy.multilspy_logger import MultilspyLogger
from concurrent.futures import ThreadPoolExecutor, as_completed
import tempfile, os, time

logger = MultilspyLogger()
langs = '$LANGS'.split()
ext_map = {...}  # same as current

def warmup_lang(lang):
    '''Warmup single language - downloads binary + starts/stops server'''
    start = time.time()
    config = MultilspyConfig.from_dict({'code_language': lang})
    with tempfile.TemporaryDirectory() as td:
        ext = ext_map.get(lang, '.txt')
        dummy = os.path.join(td, f'test{ext}')
        open(dummy, 'w').write('// dummy')
        lsp = SyncLanguageServer.create(config, logger, td)
        with lsp.start_server():
            pass  # Binary downloaded, server verified
    return lang, time.time() - start

# Run up to 4 languages in parallel (balance I/O vs CPU)
max_workers = min(4, len(langs))
print(f'Warming up {len(langs)} languages with {max_workers} workers...')

with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(warmup_lang, lang): lang for lang in langs}
    for future in as_completed(futures):
        try:
            lang, elapsed = future.result()
            print(f'  {lang} ready ({elapsed:.1f}s)')
        except Exception as e:
            lang = futures[future]
            print(f'  Warning: {lang} warmup failed: {e}')
```

### Key Design Decisions

1. **ThreadPoolExecutor over asyncio**: multilspy's `SyncLanguageServer` is synchronous; thread pool is simpler and avoids event loop complexity in a shell script.

2. **max_workers=4**: Balances parallel network I/O against container CPU/memory limits. Most tasks need 1-2 languages, so this caps overhead.

3. **Keep full server start/stop**: Considered skipping `start_server()` (just trigger download via `create()`), but:
   - Some servers download during `create()`, others during `start_server()`
   - Full cycle ensures binaries are verified and any one-time setup completes
   - Latency during agent execution matters more than warmup time

### Expected Improvement

| Scenario | Before | After |
|----------|--------|-------|
| 1 language (Python) | ~15s | ~15s (no change) |
| 2 languages (Python + TS) | ~30s | ~15-18s (parallel) |
| 4 languages | ~60s | ~20-25s |
| 10 languages (worst case) | ~150s | ~50-60s |

**~2-3x speedup** for multi-language tasks.

### Files to Modify
- `terminalbench/harbor/install-claude-code-mcp.sh.j2` (warmup block only)