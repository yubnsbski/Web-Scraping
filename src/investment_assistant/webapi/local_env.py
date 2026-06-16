"""Load local, ignored environment files for the single-user web app."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

LOCAL_ENV_FILENAMES = (".env.local", ".env")
LOCAL_ENV_ROOT_ENV = "INVESTMENT_ASSISTANT_ENV_ROOT"
_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


def load_local_env_files(
    root: str | Path | None = None,
    *,
    override: bool = False,
) -> JsonDict:
    """Load ``.env.local`` / ``.env`` without logging or returning secret values."""

    roots = _candidate_env_roots(Path(root or Path.cwd()))
    loaded_files: list[str] = []
    loaded_keys: list[str] = []
    skipped_keys: list[str] = []

    for base in roots:
        for filename in LOCAL_ENV_FILENAMES:
            path = base / filename
            if not path.exists():
                continue
            loaded_files.append(str(path))
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                parsed = _parse_env_line(raw_line)
                if parsed is None:
                    continue
                key, value = parsed
                if not _KEY_PATTERN.fullmatch(key):
                    skipped_keys.append(key)
                    continue
                if not override and os.getenv(key) is not None:
                    skipped_keys.append(key)
                    continue
                os.environ[key] = value
                loaded_keys.append(key)

    return {
        "checked_roots": [str(path) for path in roots],
        "loaded_files": loaded_files,
        "loaded_keys": sorted(set(loaded_keys)),
        "skipped_keys": sorted(set(skipped_keys)),
        "override": override,
    }


def _candidate_env_roots(base: Path) -> list[Path]:
    roots: list[Path] = []
    explicit = os.getenv(LOCAL_ENV_ROOT_ENV, "").strip()
    if explicit:
        roots.append(Path(explicit))

    resolved = base.resolve()
    roots.append(resolved)

    for parent in (resolved, *resolved.parents):
        if parent.name == ".codex-worktrees":
            roots.append(parent.parent)
            break

    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        path = root.resolve()
        if path not in seen:
            seen.add(path)
            deduped.append(path)
    return deduped


def _parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line.removeprefix("export ").strip()
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return key, value
