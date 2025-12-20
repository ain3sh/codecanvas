"""Background asyncio runtime for LSP.

CodeCanvas' public API is largely synchronous (e.g. `canvas_action`, `Parser`).
Language servers, however, are easiest to manage with asyncio.

This module runs a dedicated event loop in a background thread and provides a
sync bridge for running coroutines without `asyncio.run()` (which breaks when
called from within an existing event loop).
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Coroutine, Optional, TypeVar

T = TypeVar("T")


class LspRuntime:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

    def ensure_started(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive() and self._loop is not None:
                return

            self._ready.clear()
            self._thread = threading.Thread(target=self._run_loop, name="codecanvas-lsp", daemon=True)
            self._thread.start()

        self._ready.wait(timeout=5.0)

    def _run_loop(self) -> None:
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
    return _GLOBAL_RUNTIME
