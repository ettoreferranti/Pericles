"""Backends, cache and call log for a run directory (ADR-0017 §5-§8, §11)."""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pericles.experiment.rundir import RunDirectory
from pericles.llm.backend import Backend, LLMSetupError
from pericles.llm.cache import ResponseCache
from pericles.llm.calls import CallLog
from pericles.llm.config import LLMConfig
from pericles.llm.fake import FakeBackend
from pericles.llm.gateway import FailurePolicy, Gateway
from pericles.llm.mlx import MLXBackend
from pericles.llm.ollama import OllamaBackend

CACHE_DIR = "llm_cache"
CACHE_FILE = "responses.sqlite"
CALLS_FILE = "llm_calls.sqlite"


def build_backends(config: LLMConfig) -> dict[str, Backend]:
    backends: dict[str, Backend] = {}
    for key in sorted(config.backends):
        spec = config.backends[key]
        if spec.kind == "ollama":
            assert spec.url is not None  # LLMConfig requires it
            backends[key] = OllamaBackend(spec.url, spec.timeout_s, spec.concurrency)
        elif spec.kind == "mlx":
            backends[key] = MLXBackend(spec.concurrency)
        elif spec.replies is not None:
            backends[key] = FakeBackend.from_file(Path(spec.replies), concurrency=spec.concurrency)
        else:
            backends[key] = FakeBackend(concurrency=spec.concurrency)
    return backends


def policy_of(config: LLMConfig) -> FailurePolicy:
    return FailurePolicy(
        config.mode,
        config.backoff_base_s,
        config.backoff_factor,
        config.backoff_max_s,
        config.max_backend_failures,
    )


def replay_source(path: Path) -> Path:
    """The responses.sqlite of a run directory, its llm_cache directory, or the file itself."""
    for candidate in (path, path / CACHE_FILE, path / CACHE_DIR / CACHE_FILE):
        if candidate.is_file():
            _check_cache(candidate)
            return candidate
    raise LLMSetupError(f"llm.cache_from: no {CACHE_FILE} under {path}")


def _check_cache(path: Path) -> None:
    """Fail before a run directory exists when `path` is not a response cache."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            found = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'responses'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as error:
        raise LLMSetupError(f"llm.cache_from: {path} is not a response cache ({error})") from None
    if found is None:
        raise LLMSetupError(f"llm.cache_from: {path} is not a response cache (no responses table)")


def run_meta(config: LLMConfig) -> dict[str, Any]:
    return {
        "llm_mode": config.mode,
        "cache_mode": config.cache,
        "reproducible": config.mode != "live",
    }


def open_gateway(
    config: LLMConfig, backends: Mapping[str, Backend], run_dir: RunDirectory
) -> Gateway:
    """The run's gateway. A replay run first copies its source cache into its own llm_cache."""
    cache_path = run_dir.path / CACHE_DIR / CACHE_FILE
    if config.cache == "replay" and not cache_path.exists():
        assert config.cache_from is not None  # LLMConfig requires it
        shutil.copyfile(replay_source(Path(config.cache_from)), cache_path)
    return Gateway(
        config.models,
        backends,
        ResponseCache(cache_path, config.cache),
        policy_of(config),
        CallLog(run_dir.path / CALLS_FILE),
    )
