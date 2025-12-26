"""LSP backend for CodeCanvas parser.

Provides language server protocol client, session management, background async runtime,
and protocol utilities for LSP communication.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Coroutine, Dict, List, Optional, Tuple, TypeVar
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp
from lsprotocol.converters import get_converter

T = TypeVar("T")
FileSig = Tuple[int, int]  # (mtime_ns, size)


# =============================================================================
# Exceptions
# =============================================================================


class LSPError(Exception):
    """LSP communication or protocol error."""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


# =============================================================================
# URI and Protocol Utilities
# =============================================================================


def uri_to_path(uri: str) -> str:
    """Convert file:// URI to filesystem path."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Expected file:// URI, got: {uri}")
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path


def path_to_uri(path: str) -> str:
    """Convert filesystem path to file:// URI."""
    abs_path = os.path.abspath(path)
    if os.name == "nt":
        return "file:///" + abs_path.replace("\\", "/")
    return "file://" + abs_path


def _coerce_file_uri(path_or_uri: str) -> str:
    """Accept either an absolute/relative path or a file:// URI."""
    s = str(path_or_uri)
    if s.startswith("file://"):
        return s
    parsed = urlparse(s)
    if parsed.scheme == "file":
        return s
    return path_to_uri(s)


def _guess_language_id(path: str) -> str:
    """Guess LSP language ID from file path."""
    ext = Path(path).suffix.lower()
    mapping = {
        ".py": "python",
        ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".c": "c", ".h": "c", ".cc": "c", ".hh": "c", ".cpp": "c", ".hpp": "c",
        ".sh": "shellscript", ".bash": "shellscript",
    }
    return mapping.get(ext, "plaintext")


def _parse_definition_locations(result: Any) -> List[Dict[str, Any]]:
    """Normalize textDocument/definition results to a list of {uri, range} dicts."""

    def _one(obj: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(obj, dict):
            return None
        if "uri" in obj and "range" in obj:
            return {"uri": obj.get("uri"), "range": obj.get("range")}
        if "targetUri" in obj and "targetRange" in obj:
            return {"uri": obj.get("targetUri"), "range": obj.get("targetRange")}
        return None

    if result is None:
        return []
    if isinstance(result, list):
        return [loc for item in result if (loc := _one(item)) is not None]
    loc = _one(result)
    return [loc] if loc is not None else []


def _parse_document_symbol(data: Dict[str, Any]) -> lsp.DocumentSymbol:
    """Parse DocumentSymbol from JSON response."""
    children = [_parse_document_symbol(c) for c in data.get("children", [])]
    return lsp.DocumentSymbol(
        name=data["name"],
        kind=lsp.SymbolKind(data["kind"]),
        range=_parse_range(data["range"]),
        selection_range=_parse_range(data["selectionRange"]),
        detail=data.get("detail"),
        children=children or None,
    )


def _parse_range(data: Dict[str, Any]) -> lsp.Range:
    """Parse Range from JSON response."""
    return lsp.Range(
        start=lsp.Position(line=data["start"]["line"], character=data["start"]["character"]),
        end=lsp.Position(line=data["end"]["line"], character=data["end"]["character"]),
    )


_LSP_CONVERTER = get_converter()
_LSP_CONVERTER.register_unstructure_hook(Path, lambda p: str(p))
_LSP_CONVERTER.register_unstructure_hook(Enum, lambda e: e.value)


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert lsprotocol attrs types to JSON-serializable dicts."""
    try:
        raw = _LSP_CONVERTER.unstructure(obj)
    except Exception:
        raw = obj
    return _json_clean(raw)


def _json_clean(obj: Any) -> Any:
    """Recursively remove None values and ensure JSON-compatible containers."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): _json_clean(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, (list, tuple, set)):
        return [_json_clean(v) for v in obj if v is not None]
    return obj


# =============================================================================
# Background Async Runtime
# =============================================================================


class LspRuntime:
    """Background asyncio runtime for running LSP coroutines.

    Runs a dedicated event loop in a daemon thread, providing a sync bridge
    for running coroutines without asyncio.run().
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

    def ensure_started(self) -> None:
        """Ensure the background event loop is running."""
        with self._lock:
            if self._thread and self._thread.is_alive() and self._loop is not None:
                return
            self._ready.clear()
            self._thread = threading.Thread(target=self._run_loop, name="codecanvas-lsp", daemon=True)
            self._thread.start()
        self._ready.wait(timeout=5.0)

    def _run_loop(self) -> None:
        """Run the event loop in background thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        finally:
            loop.close()

    def run(self, coro: Coroutine[Any, Any, T], *, timeout: Optional[float] = None) -> T:
        """Run a coroutine on the background loop and block for its result."""
        self.ensure_started()
        assert self._loop is not None
        fut: Future[T] = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)


_GLOBAL_RUNTIME = LspRuntime()


def get_lsp_runtime() -> LspRuntime:
    """Get the global LSP runtime instance."""
    return _GLOBAL_RUNTIME


# =============================================================================
# LSP Client
# =============================================================================


@dataclass
class LSPConfig:
    """Configuration for LSP client."""

    retry_attempts: int = 3
    retry_delay_ms: int = 100
    request_timeout: float = 30.0


class LSPClient:
    """Async LSP client with subprocess-based JSON-RPC communication."""

    def __init__(self, cmd: List[str], workspace: str, config: Optional[LSPConfig] = None):
        self.cmd = cmd
        self.workspace = os.path.abspath(workspace)
        self.config = config or LSPConfig()

        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._pending: Dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._send_lock = asyncio.Lock()
        self._initialized = False
        self._open_documents: Dict[str, int] = {}

    async def __aenter__(self) -> "LSPClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    async def start(self) -> None:
        """Start the language server process and initialize."""
        self._process = await asyncio.create_subprocess_exec(
            *self.cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader_task = asyncio.create_task(self._read_responses())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self._initialize()

    async def stop(self) -> None:
        """Shutdown language server gracefully."""
        if self._initialized:
            try:
                await self._request("shutdown", {})
                await self._notify("exit", {})
            except Exception:
                pass

        for task in (self._reader_task, self._stderr_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._process.kill()

    async def _initialize(self) -> None:
        """Send initialize request with workspace folder."""
        workspace_uri = path_to_uri(self.workspace)
        init_params = lsp.InitializeParams(
            process_id=os.getpid(),
            root_uri=workspace_uri,
            capabilities=lsp.ClientCapabilities(
                text_document=lsp.TextDocumentClientCapabilities(
                    document_symbol=lsp.DocumentSymbolClientCapabilities(
                        hierarchical_document_symbol_support=True,
                    ),
                ),
            ),
            workspace_folders=[lsp.WorkspaceFolder(uri=workspace_uri, name=Path(self.workspace).name)],
        )
        await self._request("initialize", _to_dict(init_params))
        await self._notify("initialized", {})
        self._initialized = True

    async def document_symbols(self, file_path_or_uri: str) -> List[lsp.DocumentSymbol]:
        """Get document symbols (textDocument/documentSymbol)."""
        uri = _coerce_file_uri(file_path_or_uri)
        await self._ensure_document_open(uri)
        result = await self._request_with_retry("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
        return [_parse_document_symbol(s) for s in result] if result else []

    async def definition(self, file_path_or_uri: str, *, line: int, character: int) -> List[Dict[str, Any]]:
        """Get definition locations (textDocument/definition)."""
        uri = _coerce_file_uri(file_path_or_uri)
        await self._ensure_document_open(uri)
        params = {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}}
        return _parse_definition_locations(await self._request_with_retry("textDocument/definition", params))

    async def _request(self, method: str, params: Dict[str, Any]) -> Any:
        """Send JSON-RPC request and wait for response."""
        self._request_id += 1
        req_id = self._request_id
        message = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future
        await self._send(message)

        try:
            return await asyncio.wait_for(future, timeout=self.config.request_timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            try:
                await self._notify("$/cancelRequest", {"id": req_id})
            except Exception:
                pass
            raise LSPError(f"Request {method} timed out")
        except asyncio.CancelledError:
            self._pending.pop(req_id, None)
            try:
                await self._notify("$/cancelRequest", {"id": req_id})
            except Exception:
                pass
            raise

    async def _request_with_retry(self, method: str, params: Dict[str, Any]) -> Any:
        """Send request with retry logic for flaky servers."""
        last_error = None
        for attempt in range(self.config.retry_attempts):
            try:
                return await self._request(method, params)
            except LSPError as e:
                last_error = e
                if attempt < self.config.retry_attempts - 1:
                    await asyncio.sleep(self.config.retry_delay_ms / 1000.0)
        raise last_error or LSPError(f"Request {method} failed after retries")

    async def _notify(self, method: str, params: Dict[str, Any]) -> None:
        """Send JSON-RPC notification (no response expected)."""
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send(self, message: Dict[str, Any]) -> None:
        """Send message with Content-Length header."""
        if not self._process or not self._process.stdin:
            raise LSPError("LSP process not running")
        async with self._send_lock:
            content = json.dumps(message).encode("utf-8")
            self._process.stdin.write(f"Content-Length: {len(content)}\r\n\r\n".encode("utf-8"))
            self._process.stdin.write(content)
            await self._process.stdin.drain()

    async def _read_responses(self) -> None:
        """Background task to read and dispatch responses."""
        if not self._process or not self._process.stdout:
            return
        while True:
            try:
                headers: Dict[str, str] = {}
                while True:
                    line = await self._process.stdout.readline()
                    if not line:
                        return
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        break
                    if ":" in line_str:
                        key, value = line_str.split(":", 1)
                        headers[key.strip().lower()] = value.strip()

                content_length = int(headers.get("content-length", 0))
                if content_length == 0:
                    continue

                content = await self._process.stdout.readexactly(content_length)
                message = json.loads(content.decode("utf-8"))

                if "id" in message and message["id"] in self._pending:
                    future = self._pending.pop(message["id"])
                    if "error" in message:
                        err = message["error"]
                        future.set_exception(LSPError(err.get("message", "Unknown error"), err.get("code")))
                    else:
                        future.set_result(message.get("result"))
            except asyncio.CancelledError:
                break
            except Exception:
                continue

    async def _drain_stderr(self) -> None:
        """Continuously drain stderr to avoid subprocess backpressure/deadlocks."""
        if not self._process or not self._process.stderr:
            return
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    return
        except (asyncio.CancelledError, Exception):
            return

    async def open_document(self, uri: str, text: str, *, language_id: str | None = None, version: int | None = None) -> None:
        """Open a document on the server (textDocument/didOpen)."""
        if uri in self._open_documents:
            return
        lang = language_id or _guess_language_id(uri_to_path(uri)) if not language_id else language_id
        params = lsp.DidOpenTextDocumentParams(
            text_document=lsp.TextDocumentItem(uri=uri, language_id=lang or "plaintext", version=version or 1, text=text)
        )
        await self._notify("textDocument/didOpen", _to_dict(params))
        self._open_documents[uri] = version or 1

    async def _ensure_document_open(self, uri: str) -> None:
        """Ensure the document is opened on the server."""
        if uri in self._open_documents:
            return
        try:
            path = uri_to_path(uri)
            text = Path(path).read_text(encoding="utf-8")
            await self.open_document(uri, text, language_id=_guess_language_id(path), version=1)
        except Exception:
            pass


# =============================================================================
# LSP Session Management
# =============================================================================


@dataclass
class _CachedSymbols:
    sig: FileSig
    symbols: List[Any]


class LspSession:
    """A persistent language server session for a single (lang, workspace_root)."""

    def __init__(self, *, lang: str, workspace_root: str, cmd: List[str], config: Optional[LSPConfig] = None, max_concurrency: int = 4):
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
        """Ensure the LSP client is started and return it."""
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
        """Shutdown the LSP client."""
        if self._client is None:
            return
        try:
            await self._client.stop()
        finally:
            self._client = None
            self._doc_symbol_cache.clear()
            self._definition_cache.clear()

    def _file_sig(self, uri_or_path: str) -> Optional[FileSig]:
        """Get file signature (mtime, size) for cache invalidation."""
        try:
            path = uri_to_path(uri_or_path) if uri_or_path.startswith("file://") else uri_or_path
            st = os.stat(path)
            return (st.st_mtime_ns, st.st_size)
        except Exception:
            return None

    async def document_symbols(self, uri_or_path: str, *, text: str | None = None) -> List[Any]:
        """Get document symbols with caching keyed by file (mtime, size)."""
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
                    await client.open_document(_coerce_file_uri(uri_or_path), text)
                except Exception:
                    pass
            symbols = await client.document_symbols(uri_or_path)

        if sig is not None:
            self._doc_symbol_cache[uri_or_path] = _CachedSymbols(sig=sig, symbols=symbols)
        return symbols

    async def definition(self, uri_or_path: str, *, line: int, char: int, text: str | None = None) -> List[Any]:
        """Get definition locations with caching."""
        self._last_used = time.monotonic()
        sig = self._file_sig(uri_or_path)
        key = (uri_or_path, int(line), int(char), sig)

        if sig is not None and (cached := self._definition_cache.get(key)) is not None:
            return cached

        async with self._semaphore:
            client = await self.ensure_started()
            if text is not None:
                try:
                    await client.open_document(_coerce_file_uri(uri_or_path), text)
                except Exception:
                    pass
            locations = await client.definition(uri_or_path, line=int(line), character=int(char))

        if sig is not None:
            self._definition_cache[key] = locations
        return locations

    async def definitions(self, uri_or_path: str, *, positions: List[tuple[int, int]], text: str | None = None) -> List[Any]:
        """Get many definition lookups for a single file."""
        self._last_used = time.monotonic()
        if not positions:
            return []

        norm = [(int(line), int(char)) for (line, char) in positions]
        sig = self._file_sig(uri_or_path)
        out: List[Any] = [None] * len(norm)
        missing: List[tuple[int, int, int]] = []

        if sig is not None:
            for idx, (line, char) in enumerate(norm):
                if (cached := self._definition_cache.get((uri_or_path, line, char, sig))) is not None:
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
                    await client.open_document(_coerce_file_uri(uri_or_path), text)
                except Exception:
                    pass
            tasks = [client.definition(uri_or_path, line=line, character=char) for (_, line, char) in missing]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for (idx, line, char), res in zip(missing, results):
            if isinstance(res, Exception):
                out[idx] = res
            else:
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
        self._lock = asyncio.Lock()

    async def get(self, *, lang: str, workspace_root: str, cmd: List[str], config: Optional[LSPConfig] = None) -> LspSession:
        """Get or create an LSP session for the given language and workspace."""
        async with self._lock:
            key = (lang, os.path.abspath(workspace_root))
            if (sess := self._sessions.get(key)) is None:
                sess = LspSession(lang=lang, workspace_root=key[1], cmd=cmd, config=config)
                self._sessions[key] = sess
            await self._evict_if_needed()
            return sess

    async def _evict_if_needed(self) -> None:
        """Evict idle or excess sessions."""
        now = time.monotonic()
        for k in [k for k, s in self._sessions.items() if now - s.last_used > self.idle_ttl_s]:
            if (sess := self._sessions.pop(k, None)) is not None:
                try:
                    await sess.shutdown()
                except Exception:
                    pass

        while len(self._sessions) > self.max_sessions:
            k, sess = min(self._sessions.items(), key=lambda kv: kv[1].last_used)
            self._sessions.pop(k, None)
            try:
                await sess.shutdown()
            except Exception:
                pass


_GLOBAL_MANAGER = LspSessionManager()


def get_lsp_session_manager() -> LspSessionManager:
    """Get the global LSP session manager instance."""
    return _GLOBAL_MANAGER
