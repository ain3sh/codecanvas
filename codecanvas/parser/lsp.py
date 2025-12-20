"""Language server configuration and LSP client for CodeCanvas.

Provides centralized configuration for LSP servers, file extension mappings,
and async LSP communication.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp
from lsprotocol.converters import get_converter

# Language server configurations
# Maps language key -> server command and initialization options
LANGUAGE_SERVERS: Dict[str, Dict[str, Any]] = {
    "py": {
        "cmd": ["basedpyright-langserver", "--stdio"],
        "init_options": {},
    },
    "ts": {
        "cmd": ["typescript-language-server", "--stdio"],
        "init_options": {},
    },
    "go": {
        "cmd": ["gopls", "serve"],
        "init_options": {},
    },
    "rs": {
        "cmd": ["rust-analyzer"],
        "init_options": {},
    },
    "java": {
        "cmd": ["jdtls"],
        "init_options": {},
    },
    "rb": {
        "cmd": ["solargraph", "stdio"],
        "init_options": {},
    },
    "c": {
        "cmd": ["clangd"],
        "init_options": {},
    },
    "sh": {
        "cmd": ["bash-language-server", "start"],
        "init_options": {},
    },
}


@lru_cache
def is_language_server_installed(lang: str) -> bool:
    cfg = LANGUAGE_SERVERS.get(lang)
    if not cfg:
        return False

    cmd = cfg.get("cmd")
    if not cmd:
        return False

    return shutil.which(cmd[0]) is not None


# File extension to language key mapping
EXTENSION_TO_LANG: Dict[str, str] = {
    # Python
    ".py": "py",
    # TypeScript/JavaScript (consolidated under 'ts')
    ".ts": "ts",
    ".tsx": "ts",
    ".js": "ts",
    ".jsx": "ts",
    # Go
    ".go": "go",
    # Rust
    ".rs": "rs",
    # Java
    ".java": "java",
    # Ruby
    ".rb": "rb",
    # C/C++ (consolidated under 'c')
    ".c": "c",
    ".h": "c",
    ".cpp": "c",
    ".hpp": "c",
    ".cc": "c",
    # Shell
    ".sh": "sh",
    ".bash": "sh",
}


def detect_language(path: str) -> Optional[str]:
    """Detect language from file path.

    Args:
        path: File path (e.g., "/path/to/file.py")

    Returns:
        Language key (e.g., "py") or None if extension is unknown
    """
    # Extract extension
    if "." not in path:
        return None

    # Handle paths with multiple dots (e.g., "file.test.ts")
    ext = "." + path.rsplit(".", 1)[-1]

    return EXTENSION_TO_LANG.get(ext)


def has_lsp_support(lang: str) -> bool:
    """Check if a language has LSP server support.

    Args:
        lang: Language key (e.g., "py")

    Returns:
        True if language server is configured for this language
    """
    return lang in LANGUAGE_SERVERS


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
        out: List[Dict[str, Any]] = []
        for item in result:
            loc = _one(item)
            if loc is not None:
                out.append(loc)
        return out

    loc = _one(result)
    return [loc] if loc is not None else []


# --- LSP Client ---


class LSPError(Exception):
    """LSP communication or protocol error."""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


@dataclass
class LSPConfig:
    """Configuration for LSP client."""

    retry_attempts: int = 3
    retry_delay_ms: int = 100
    request_timeout: float = 30.0


def uri_to_path(uri: str) -> str:
    """Convert file:// URI to filesystem path."""
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        raise ValueError(f"Expected file:// URI, got: {uri}")
    # Handle Windows paths (e.g., file:///C:/path)
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]  # Remove leading slash on Windows
    return path


def path_to_uri(path: str) -> str:
    """Convert filesystem path to file:// URI."""
    abs_path = os.path.abspath(path)
    if os.name == "nt":
        # Windows: file:///C:/path
        return "file:///" + abs_path.replace("\\", "/")
    return "file://" + abs_path


class LSPClient:
    """Async LSP client with subprocess-based JSON-RPC communication.

    Usage:
        async with LSPClient(["pylsp"], workspace="/path/to/project") as client:
            symbols = await client.document_symbols("/path/to/file.py")
    """

    def __init__(
        self,
        cmd: List[str],
        workspace: str,
        config: Optional[LSPConfig] = None,
    ):
        """Initialize LSP client.

        Args:
            cmd: Command to start language server (e.g., ["pylsp"])
            workspace: Absolute path to workspace root
            config: Optional configuration overrides
        """
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
        self._open_documents: Dict[str, int] = {}  # uri -> version

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
                pass  # Best-effort shutdown

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
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

        result = await self._request("initialize", _to_dict(init_params))
        await self._notify("initialized", {})
        self._initialized = True
        return result

    async def document_symbols(self, file_path_or_uri: str) -> List[lsp.DocumentSymbol]:
        """Get document symbols (textDocument/documentSymbol)."""
        uri = _coerce_file_uri(file_path_or_uri)
        await self._ensure_document_open(uri)
        params = {"textDocument": {"uri": uri}}
        result = await self._request_with_retry("textDocument/documentSymbol", params)
        if result is None:
            return []
        return [_parse_document_symbol(s) for s in result]

    async def definition(self, file_path_or_uri: str, *, line: int, character: int) -> List[Dict[str, Any]]:
        """Get definition locations (textDocument/definition)."""
        uri = _coerce_file_uri(file_path_or_uri)
        await self._ensure_document_open(uri)
        params = {"textDocument": {"uri": uri}, "position": {"line": line, "character": character}}
        result = await self._request_with_retry("textDocument/definition", params)
        return _parse_definition_locations(result)

    # --- JSON-RPC Transport ---

    async def _request(self, method: str, params: Dict[str, Any]) -> Any:
        """Send JSON-RPC request and wait for response."""
        self._request_id += 1
        req_id = self._request_id

        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[req_id] = future

        await self._send(message)

        try:
            result = await asyncio.wait_for(future, timeout=self.config.request_timeout)
            return result
        except asyncio.TimeoutError:
            del self._pending[req_id]
            try:
                await self._notify("$/cancelRequest", {"id": req_id})
            except Exception:
                pass
            raise LSPError(f"Request {method} timed out")
        except asyncio.CancelledError:
            if req_id in self._pending:
                del self._pending[req_id]
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
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._send(message)

    async def _send(self, message: Dict[str, Any]) -> None:
        """Send message with Content-Length header."""
        if not self._process or not self._process.stdin:
            raise LSPError("LSP process not running")

        async with self._send_lock:
            content = json.dumps(message)
            content_bytes = content.encode("utf-8")
            header = f"Content-Length: {len(content_bytes)}\r\n\r\n"
            self._process.stdin.write(header.encode("utf-8"))
            self._process.stdin.write(content_bytes)
            await self._process.stdin.drain()

    async def _read_responses(self) -> None:
        """Background task to read and dispatch responses."""
        if not self._process or not self._process.stdout:
            return

        while True:
            try:
                # Read headers
                headers: Dict[str, str] = {}
                while True:
                    line = await self._process.stdout.readline()
                    if not line:
                        return  # EOF
                    line_str = line.decode("utf-8").strip()
                    if not line_str:
                        break
                    if ":" in line_str:
                        key, value = line_str.split(":", 1)
                        headers[key.strip().lower()] = value.strip()

                # Read content
                content_length = int(headers.get("content-length", 0))
                if content_length == 0:
                    continue

                content = await self._process.stdout.readexactly(content_length)
                message = json.loads(content.decode("utf-8"))

                # Dispatch response
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
                continue  # Ignore malformed messages

    async def _drain_stderr(self) -> None:
        """Continuously drain stderr to avoid subprocess backpressure/deadlocks."""
        if not self._process or not self._process.stderr:
            return

        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    return
        except asyncio.CancelledError:
            return
        except Exception:
            return

    async def open_document(
        self,
        uri: str,
        text: str,
        *,
        language_id: str | None = None,
        version: int | None = None,
    ) -> None:
        """Open a document on the server using in-memory text (textDocument/didOpen)."""
        if uri in self._open_documents:
            return

        lang = language_id
        if not lang:
            try:
                lang = _guess_language_id(uri_to_path(uri))
            except Exception:
                lang = "plaintext"

        ver = int(version or 1)
        params = lsp.DidOpenTextDocumentParams(
            text_document=lsp.TextDocumentItem(
                uri=uri,
                language_id=lang,
                version=ver,
                text=text,
            )
        )
        await self._notify("textDocument/didOpen", _to_dict(params))
        self._open_documents[uri] = ver

    async def _ensure_document_open(self, uri: str) -> None:
        """Ensure the document is opened on the server via textDocument/didOpen.

        Many servers require the document to be opened before responding to
        textDocument/* requests.
        """
        if uri in self._open_documents:
            return

        try:
            path = uri_to_path(uri)
        except Exception:
            # If it's not a file URI, we can't open it.
            return

        try:
            text = Path(path).read_text(encoding="utf-8")
        except Exception:
            return

        await self.open_document(uri, text, language_id=_guess_language_id(path), version=1)


# --- Response Parsers ---


def _to_dict(obj: Any) -> Dict[str, Any]:
    """Convert objects (including lsprotocol attrs types) to JSON-serializable values.

    lsprotocol types are attrs classes and require cattrs-based unstructuring
    to produce LSP-compliant camelCase keys.
    """

    try:
        raw = _LSP_CONVERTER.unstructure(obj)
    except Exception:
        raw = obj
    return _json_clean(raw)


_LSP_CONVERTER = get_converter()
_LSP_CONVERTER.register_unstructure_hook(Path, lambda p: str(p))
_LSP_CONVERTER.register_unstructure_hook(Enum, lambda e: e.value)


def _json_clean(obj: Any) -> Any:
    """Recursively remove None values and ensure JSON-compatible containers."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if v is None:
                continue
            out[str(k)] = _json_clean(v)
        return out
    if isinstance(obj, (list, tuple, set)):
        return [_json_clean(v) for v in obj if v is not None]
    return obj


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
    ext = Path(path).suffix.lower()
    if ext == ".py":
        return "python"
    if ext in {".ts", ".tsx"}:
        return "typescript"
    if ext in {".js", ".jsx"}:
        return "javascript"
    if ext == ".go":
        return "go"
    if ext == ".rs":
        return "rust"
    if ext == ".java":
        return "java"
    if ext == ".rb":
        return "ruby"
    if ext in {".c", ".h", ".cc", ".hh", ".cpp", ".hpp"}:
        return "c"
    if ext in {".sh", ".bash"}:
        return "shellscript"
    return "plaintext"


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
