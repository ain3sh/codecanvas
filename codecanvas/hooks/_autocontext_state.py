from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


def _get_state_dir() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir) / "codecanvas"
    return Path.home() / ".claude" / "codecanvas"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        return


@dataclass
class ImpactThrottle:
    last_at: float
    symbol: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Optional["ImpactThrottle"]:
        try:
            last_at = float(d.get("last_at", 0))
            symbol = str(d.get("symbol", ""))
        except Exception:
            return None
        if not symbol:
            return None
        return cls(last_at=last_at, symbol=symbol)

    def to_dict(self) -> Dict[str, Any]:
        return {"last_at": float(self.last_at), "symbol": self.symbol}


class AutoContextState:
    def __init__(self) -> None:
        self._path = _get_state_dir() / "autocontext_state.json"
        self._cache_path = _get_state_dir() / "autocontext_cache.json"

    def read_active_root(self) -> str:
        d = _read_json(self._path)
        root = d.get("active_root")
        return root if isinstance(root, str) else ""

    def write_active_root(self, root: str, *, reason: str) -> None:
        _write_json_atomic(
            self._path,
            {
                "active_root": root,
                "updated_at": time.time(),
                "reason": reason,
            },
        )

    def get_impact_throttle(self, *, root: str, file_path: str) -> Optional[ImpactThrottle]:
        key = f"{root}::{file_path}"
        d = _read_json(self._cache_path)
        raw = d.get(key)
        return ImpactThrottle.from_dict(raw) if isinstance(raw, dict) else None

    def set_impact_throttle(self, *, root: str, file_path: str, symbol: str) -> None:
        key = f"{root}::{file_path}"
        d = _read_json(self._cache_path)
        if not isinstance(d, dict):
            d = {}
        d[key] = ImpactThrottle(last_at=time.time(), symbol=symbol).to_dict()
        _write_json_atomic(self._cache_path, d)

    def is_init_announced(self, *, root: str) -> bool:
        key = f"init_announced::{root}"
        d = _read_json(self._cache_path)
        return bool(isinstance(d, dict) and d.get(key) is True)

    def set_init_announced(self, *, root: str) -> None:
        key = f"init_announced::{root}"
        d = _read_json(self._cache_path)
        if not isinstance(d, dict):
            d = {}
        d[key] = True
        _write_json_atomic(self._cache_path, d)

    def get_init_inflight_at(self, *, root: str) -> Optional[float]:
        key = f"init_inflight::{root}"
        d = _read_json(self._cache_path)
        if not isinstance(d, dict):
            return None
        v = d.get(key)
        try:
            return float(v)
        except Exception:
            return None

    def set_init_inflight_at(self, *, root: str, at: float) -> None:
        key = f"init_inflight::{root}"
        d = _read_json(self._cache_path)
        if not isinstance(d, dict):
            d = {}
        d[key] = float(at)
        _write_json_atomic(self._cache_path, d)

    def clear_init_inflight(self, *, root: str) -> None:
        key = f"init_inflight::{root}"
        d = _read_json(self._cache_path)
        if not isinstance(d, dict) or key not in d:
            return
        d.pop(key, None)
        _write_json_atomic(self._cache_path, d)

    def get_init_next_allowed_at(self, *, root: str) -> Optional[float]:
        key = f"init_next_allowed_at::{root}"
        d = _read_json(self._cache_path)
        if not isinstance(d, dict):
            return None
        v = d.get(key)
        try:
            return float(v)
        except Exception:
            return None

    def set_init_next_allowed_at(self, *, root: str, at: float) -> None:
        key = f"init_next_allowed_at::{root}"
        d = _read_json(self._cache_path)
        if not isinstance(d, dict):
            d = {}
        d[key] = float(at)
        _write_json_atomic(self._cache_path, d)

    def get_lsp_init_attempts(self, *, root: str) -> int:
        key = f"lsp_init_attempts::{root}"
        d = _read_json(self._cache_path)
        if not isinstance(d, dict):
            return 0
        v = d.get(key)
        try:
            return int(v)
        except Exception:
            return 0

    def inc_lsp_init_attempts(self, *, root: str) -> int:
        key = f"lsp_init_attempts::{root}"
        d = _read_json(self._cache_path)
        if not isinstance(d, dict):
            d = {}
        cur = 0
        try:
            cur = int(d.get(key) or 0)
        except Exception:
            cur = 0
        cur += 1
        d[key] = cur
        _write_json_atomic(self._cache_path, d)
        return cur
