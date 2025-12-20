"""Persistent LSP sessions.

CodeCanvas' LSP servers are expensive to start and initialize. This module keeps
one warm server per (language, workspace_root) and provides lightweight caching
for common queries.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .lsp import LSPClient, LSPConfig, LSPError, uri_to_path

FileSig = Tuple[int, int]  # (mtime_ns, size)


@dataclass
class _CachedSymbols:
    sig: FileSig
    symbols: List[Any]


class LspSession:
    """A persistent language server session for a single (lang, workspace_root)."""

    def __init__(
        self,
        *,
        lang: str,
        workspace_root: str,
        cmd: List[str],
        config: Optional[LSPConfig] = None,
        max_concurrency: int = 4,
    ):
        self.lang = lang
        self.workspace_root = os.path.abspath(workspace_root)
        self.cmd = cmd
        self.config = config or LSPConfig()

        self._client: Optional[LSPClient] = None
        self._semaphore = asyncio.Semaphore(max_concurrency)

        self._disabled_reason: str | None = None

        self._doc_symbol_cache: Dict[str, _CachedSymbols] = {}
        self._definition_cache: Dict[tuple[str, int, int, Optional[FileSig]], List[Any]] = {}
        self._last_used = time.monotonic()

    @property
    def last_used(self) -> float:
        return self._last_used

    async def ensure_started(self) -> LSPClient:
        self._last_used = time.monotonic()

        if self._disabled_reason is not None:
            raise LSPError(self._disabled_reason)

        if not self.cmd:
            self._disabled_reason = "Missing language server command"
            raise LSPError(self._disabled_reason)

        if shutil.which(self.cmd[0]) is None:
            self._disabled_reason = f"Missing language server: {self.cmd[0]}"
            raise LSPError(self._disabled_reason)

        if self._client is not None:
            proc = getattr(self._client, "_process", None)
            if proc is not None and getattr(proc, "returncode", None) is None:
                return self._client

            try:
                await self._client.stop()
            except Exception:
                pass
            self._client = None

        try:
            self._client = LSPClient(self.cmd, workspace=self.workspace_root, config=self.config)
            await self._client.start()
            return self._client
        except Exception as e:
            self._client = None
            self._disabled_reason = f"Language server failed to start: {type(e).__name__}"
            raise LSPError(self._disabled_reason) from e

    async def shutdown(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.stop()
        finally:
            self._client = None
            self._doc_symbol_cache.clear()
            self._definition_cache.clear()

    def _file_sig(self, uri_or_path: str) -> Optional[FileSig]:
        try:
            path = uri_to_path(uri_or_path) if uri_or_path.startswith("file://") else uri_or_path
            st = os.stat(path)
            return (st.st_mtime_ns, st.st_size)
        except Exception:
            return None

    async def document_symbols(self, uri_or_path: str, *, text: str | None = None) -> List[Any]:
        """Get document symbols with caching keyed by file (mtime,size)."""
        self._last_used = time.monotonic()

        sig = self._file_sig(uri_or_path)
        if sig is not None:
            cached = self._doc_symbol_cache.get(uri_or_path)
            if cached is not None and cached.sig == sig:
                return cached.symbols

        async with self._semaphore:
            client = await self.ensure_started()
            if text is not None:
                try:
                    from .lsp import _coerce_file_uri

                    uri = _coerce_file_uri(uri_or_path)
                    await client.open_document(uri, text)
                except Exception:
                    pass

            symbols = await client.document_symbols(uri_or_path)

        if sig is not None:
            self._doc_symbol_cache[uri_or_path] = _CachedSymbols(sig=sig, symbols=symbols)
        return symbols

    async def definition(self, uri_or_path: str, *, line: int, char: int, text: str | None = None) -> List[Any]:
        """Get definition locations with caching keyed by file (mtime,size)."""
        self._last_used = time.monotonic()

        sig = self._file_sig(uri_or_path)
        key = (uri_or_path, int(line), int(char), sig)
        if sig is not None:
            cached = self._definition_cache.get(key)
            if cached is not None:
                return cached

        async with self._semaphore:
            client = await self.ensure_started()
            if text is not None:
                try:
                    from .lsp import _coerce_file_uri

                    uri = _coerce_file_uri(uri_or_path)
                    await client.open_document(uri, text)
                except Exception:
                    pass

            locations = await client.definition(uri_or_path, line=int(line), character=int(char))

        if sig is not None:
            self._definition_cache[key] = locations
        return locations

    async def definitions(
        self,
        uri_or_path: str,
        *,
        positions: List[tuple[int, int]],
        text: str | None = None,
    ) -> List[Any]:
        """Get many definition lookups for a single file with one file stat and (optional) didOpen."""
        self._last_used = time.monotonic()

        if not positions:
            return []

        norm = [(int(line), int(char)) for (line, char) in positions]

        sig = self._file_sig(uri_or_path)
        out: List[Any] = [None] * len(norm)
        missing: List[tuple[int, int, int]] = []  # (idx, line, char)

        if sig is not None:
            for idx, (line, char) in enumerate(norm):
                key = (uri_or_path, line, char, sig)
                cached = self._definition_cache.get(key)
                if cached is not None:
                    out[idx] = cached
                else:
                    missing.append((idx, line, char))
        else:
            missing = [(idx, line, char) for idx, (line, char) in enumerate(norm)]

        if not missing:
            return out

        async with self._semaphore:
            client = await self.ensure_started()
            if text is not None:
                try:
                    from .lsp import _coerce_file_uri

                    uri = _coerce_file_uri(uri_or_path)
                    await client.open_document(uri, text)
                except Exception:
                    pass

            tasks = [client.definition(uri_or_path, line=line, character=char) for (_idx, line, char) in missing]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for (idx, line, char), res in zip(missing, results):
            if isinstance(res, Exception):
                out[idx] = res
                continue
            if sig is not None:
                self._definition_cache[(uri_or_path, line, char, sig)] = res
            out[idx] = res

        return out


class LspSessionManager:
    """Owns multiple persistent LSP sessions and evicts idle ones."""

    def __init__(self, *, max_sessions: int = 8, idle_ttl_s: float = 300.0):
        self.max_sessions = max_sessions
        self.idle_ttl_s = idle_ttl_s
        self._sessions: Dict[tuple[str, str], LspSession] = {}

        # This manager is intended to be used from a single asyncio event loop.
        # The lock protects against interleaving between concurrent tasks.
        self._lock = asyncio.Lock()

    async def get(
        self,
        *,
        lang: str,
        workspace_root: str,
        cmd: List[str],
        config: Optional[LSPConfig] = None,
    ) -> LspSession:
        async with self._lock:
            key = (lang, os.path.abspath(workspace_root))
            sess = self._sessions.get(key)
            if sess is None:
                sess = LspSession(lang=lang, workspace_root=key[1], cmd=cmd, config=config)
                self._sessions[key] = sess

            await self._evict_if_needed_locked()
            return sess

    async def _evict_if_needed_locked(self) -> None:
        now = time.monotonic()

        # Evict idle sessions first.
        idle_keys = [k for k, s in self._sessions.items() if now - s.last_used > self.idle_ttl_s]
        for k in idle_keys:
            sess = self._sessions.pop(k, None)
            if sess is not None:
                try:
                    await sess.shutdown()
                except Exception:
                    pass

        if len(self._sessions) <= self.max_sessions:
            return

        # Evict LRU until under cap.
        for k, sess in sorted(self._sessions.items(), key=lambda kv: kv[1].last_used):
            self._sessions.pop(k, None)
            try:
                await sess.shutdown()
            except Exception:
                pass
            if len(self._sessions) <= self.max_sessions:
                return


_GLOBAL_MANAGER = LspSessionManager()


def get_lsp_session_manager() -> LspSessionManager:
    return _GLOBAL_MANAGER
