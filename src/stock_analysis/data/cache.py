"""TTL-aware disk cache for JSON blobs and Parquet DataFrames."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from loguru import logger


class DiskCache:
    """
    Simple file-based cache with per-entry TTL.

    Layout on disk:
        <cache_dir>/<namespace>/<key>.json         — JSON entries
        <cache_dir>/<namespace>/<key>.parquet      — DataFrame entries
        <cache_dir>/<namespace>/<key>.meta.json    — metadata (written_at, ttl_hours)
    """

    def __init__(self, cache_dir: Path) -> None:
        self._root = Path(cache_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def get_json(self, namespace: str, key: str) -> Any | None:
        """Return cached JSON value or None if missing / expired."""
        path = self._path(namespace, key, "json")
        if not self._is_valid(namespace, key):
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def set_json(self, namespace: str, key: str, value: Any, ttl_hours: float) -> None:
        """Persist a JSON-serialisable value."""
        ns_dir = self._ns_dir(namespace)
        ns_dir.mkdir(parents=True, exist_ok=True)
        path = ns_dir / f"{key}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, default=str)
        self._write_meta(namespace, key, ttl_hours)

    def get_df(self, namespace: str, key: str) -> pd.DataFrame | None:
        """Return cached DataFrame or None if missing / expired."""
        path = self._path(namespace, key, "parquet")
        if not path.exists() or not self._is_valid(namespace, key):
            return None
        return pd.read_parquet(path)

    def set_df(self, namespace: str, key: str, df: pd.DataFrame, ttl_hours: float) -> None:
        """Persist a DataFrame as Parquet."""
        ns_dir = self._ns_dir(namespace)
        ns_dir.mkdir(parents=True, exist_ok=True)
        path = ns_dir / f"{key}.parquet"
        df.to_parquet(path, index=True)
        self._write_meta(namespace, key, ttl_hours)

    def get_or_fetch_json(
        self,
        namespace: str,
        key: str,
        fetch_fn: Callable[[], Any],
        ttl_hours: float,
    ) -> Any:
        """Return cached JSON value; call fetch_fn and cache result if stale."""
        cached = self.get_json(namespace, key)
        if cached is not None:
            logger.debug(f"Cache hit [{namespace}/{key}]")
            return cached
        logger.debug(f"Cache miss [{namespace}/{key}] — fetching")
        value = fetch_fn()
        self.set_json(namespace, key, value, ttl_hours)
        return value

    def get_or_fetch_df(
        self,
        namespace: str,
        key: str,
        fetch_fn: Callable[[], pd.DataFrame],
        ttl_hours: float,
    ) -> pd.DataFrame:
        """Return cached DataFrame; call fetch_fn and cache result if stale."""
        cached = self.get_df(namespace, key)
        if cached is not None:
            logger.debug(f"Cache hit [{namespace}/{key}]")
            return cached
        logger.debug(f"Cache miss [{namespace}/{key}] — fetching")
        df = fetch_fn()
        self.set_df(namespace, key, df, ttl_hours)
        return df

    def invalidate(self, namespace: str, key: str) -> None:
        """Remove all cache files for a given entry."""
        for ext in ("json", "parquet", "meta.json"):
            p = self._ns_dir(namespace) / f"{key}.{ext}"
            if p.exists():
                p.unlink()

    def is_cached(self, namespace: str, key: str) -> bool:
        return self._is_valid(namespace, key)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _ns_dir(self, namespace: str) -> Path:
        return self._root / namespace

    def _path(self, namespace: str, key: str, ext: str) -> Path:
        return self._ns_dir(namespace) / f"{key}.{ext}"

    def _meta_path(self, namespace: str, key: str) -> Path:
        return self._ns_dir(namespace) / f"{key}.meta.json"

    def _write_meta(self, namespace: str, key: str, ttl_hours: float) -> None:
        meta = {"written_at": time.time(), "ttl_hours": ttl_hours}
        with self._meta_path(namespace, key).open("w") as f:
            json.dump(meta, f)

    def _is_valid(self, namespace: str, key: str) -> bool:
        meta_path = self._meta_path(namespace, key)
        if not meta_path.exists():
            return False
        with meta_path.open() as f:
            meta = json.load(f)
        age_hours = (time.time() - meta["written_at"]) / 3600
        return age_hours < meta["ttl_hours"]
