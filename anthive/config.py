"""anthive config — load swarm.toml and merge with hard-coded defaults.

Uses stdlib ``tomllib`` (Python 3.11+).  No third-party TOML dependency.

Public API:
    load_config(repo_root)  -> dict
    deep_merge(base, override) -> dict
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any


__all__ = ["load_config", "deep_merge", "DEFAULTS"]


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "project": {
        "name": "anthive",
    },
    "dispatcher": {
        "default": "local",
        "local": {
            "auth": "subscription",
            "worktree_dir": "worktrees/",
            "tmux_session_prefix": "anthive-",
            "default_model": "sonnet",
            "max_concurrent_sessions": 4,
        },
        "cloud": {
            "auth": "api_key",
            "api_key_env": "ANTHROPIC_API_KEY",
            "budget_cap_usd": 5.00,
            "require_confirm": True,
            "max_concurrent": 3,
            "daily_budget_usd": 50.00,
        },
    },
    "observability": {
        "langfuse_url": "http://localhost:3000",
        "otel_endpoint": "http://localhost:3000/api/public/otel",
    },
    "paths": {
        "tasks_dir": "tasks/",
        "sessions_dir": "logs/sessions/",
        "merge_queue": "logs/merge-queue.md",
        "decisions_dir": "logs/decisions/",
        "archive_dir": "logs/archive/",
        "prompts_dir": "prompts/",
    },
    "agents": {
        "fallback": "python-developer",
        "heuristic_match": True,
    },
    "git": {
        "branch_prefix": "session/",
        "merge_strategy": "no-ff",
        "allow_force_push": False,
        "respect_hooks": True,
    },
}


# ---------------------------------------------------------------------------
# Deep merge helper
# ---------------------------------------------------------------------------


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict.

    Scalar values in *override* replace those in *base*.  Nested dicts are
    merged recursively.  Neither *base* nor *override* is mutated.

    Args:
        base:     The default / fallback values.
        override: User-supplied values that take precedence.

    Returns:
        A new dict that is the deep merge of *base* and *override*.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(repo_root: Path) -> dict[str, Any]:
    """Load ``swarm.toml`` from *repo_root* and merge with DEFAULTS.

    If ``swarm.toml`` is absent, the full DEFAULTS dict is returned unchanged.

    Args:
        repo_root: Absolute path to the repository root.  The file
                   ``<repo_root>/swarm.toml`` is read if it exists.

    Returns:
        A dict whose structure mirrors DEFAULTS, with user values overriding
        the defaults wherever present.
    """
    config_path = repo_root / "swarm.toml"

    if not config_path.exists():
        return copy.deepcopy(DEFAULTS)

    with config_path.open("rb") as fh:
        user_config = tomllib.load(fh)

    return deep_merge(DEFAULTS, user_config)
