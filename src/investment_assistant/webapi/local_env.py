"""Load local, ignored environment files for the single-user web app."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
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


def inspect_local_env_keys(
    expected_keys: Sequence[str],
    root: str | Path | None = None,
    *,
    include_key_contains: Sequence[str] = (),
) -> JsonDict:
    """Inspect local env files for key names only, never secret values."""

    expected = {key for key in expected_keys if key}
    contains = tuple(token.upper() for token in include_key_contains if token)
    roots = _candidate_env_roots(Path(root or Path.cwd()))
    files_found: list[str] = []
    entries: list[JsonDict] = []

    for base in roots:
        for filename in LOCAL_ENV_FILENAMES:
            path = base / filename
            if not path.exists():
                continue
            files_found.append(str(path))
            lines = path.read_text(encoding="utf-8").splitlines()
            for line_number, raw_line in enumerate(lines, start=1):
                parsed = _parse_env_line(raw_line)
                if parsed is None:
                    continue
                key, value = parsed
                upper_key = key.upper()
                is_expected = key in expected
                is_related = any(token in upper_key for token in contains)
                if not is_expected and not is_related:
                    continue
                entries.append(
                    {
                        "file": str(path),
                        "line": line_number,
                        "key": key,
                        "is_expected": is_expected,
                        "has_value": bool(value.strip()),
                        "valid_name": bool(_KEY_PATTERN.fullmatch(key)),
                    }
                )

    expected_status = []
    for key in sorted(expected):
        matches = [entry for entry in entries if entry["key"] == key]
        expected_status.append(
            {
                "key": key,
                "present": bool(matches),
                "has_value": any(bool(entry["has_value"]) for entry in matches),
                "valid_name": (
                    all(bool(entry["valid_name"]) for entry in matches)
                    if matches
                    else None
                ),
            }
        )

    related_keys = sorted(
        {
            str(entry["key"])
            for entry in entries
            if not bool(entry["is_expected"])
        }
    )
    return {
        "checked_roots": [str(path) for path in roots],
        "files_found": files_found,
        "expected": expected_status,
        "related_keys": related_keys,
        "entries": entries,
    }


def save_local_env_key(
    key: str,
    value: str,
    root: str | Path | None = None,
    *,
    filename: str = ".env.local",
    apply_to_process: bool = True,
) -> JsonDict:
    """Upsert one local env key without returning the secret value."""

    normalized_key = key.strip()
    secret = value.strip()
    if not _KEY_PATTERN.fullmatch(normalized_key):
        raise ValueError(f"invalid env key: {normalized_key}")
    if not secret:
        raise ValueError(f"{normalized_key} must not be empty")
    if "\n" in secret or "\r" in secret or "\x00" in secret:
        raise ValueError(f"{normalized_key} must be a single-line value")
    if filename not in LOCAL_ENV_FILENAMES:
        raise ValueError(f"unsupported local env file: {filename}")

    roots = _candidate_env_roots(Path(root or Path.cwd()))
    path = _select_env_write_path(roots, filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    existed = path.exists()
    original_lines = path.read_text(encoding="utf-8").splitlines() if existed else []
    new_line = f"{normalized_key}={_format_env_value(secret)}"
    updated = False
    line_number = len(original_lines) + 1
    next_lines: list[str] = []

    for index, raw_line in enumerate(original_lines, start=1):
        parsed = _parse_env_line(raw_line)
        if parsed is not None and parsed[0] == normalized_key:
            if not updated:
                next_lines.append(new_line)
                updated = True
                line_number = index
            continue
        next_lines.append(raw_line)

    if not updated:
        if next_lines and next_lines[-1].strip():
            next_lines.append("")
        next_lines.append(new_line)

    path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")
    if apply_to_process:
        os.environ[normalized_key] = secret

    return {
        "saved": True,
        "file": str(path),
        "key": normalized_key,
        "has_value": True,
        "created_file": not existed,
        "updated_existing_key": updated,
        "line": line_number,
        "applied_to_process": apply_to_process,
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


def _select_env_write_path(roots: list[Path], filename: str) -> Path:
    for root in roots:
        path = root / filename
        if path.exists():
            return path
    return roots[-1] / filename if len(roots) > 1 else roots[0] / filename


def _format_env_value(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:=@+-]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


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
