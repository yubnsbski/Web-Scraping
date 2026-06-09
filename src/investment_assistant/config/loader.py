"""Configuration loading utilities.

This project intentionally keeps Phase 1 free of mandatory third-party runtime
packages, so this loader supports the small YAML subset used by repository
configuration files: nested mappings, lists, booleans, numbers, strings, and
empty lists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a repository YAML config file and return a dictionary."""

    config_path = Path(path)
    lines = _normalized_lines(config_path.read_text(encoding="utf-8"))
    parsed, next_index = _parse_mapping(lines, 0, 0)
    if next_index != len(lines):
        msg = f"Could not parse full YAML config: {config_path}"
        raise ValueError(msg)
    return parsed


def _normalized_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        without_comment = raw_line.split("#", 1)[0].rstrip()
        if not without_comment.strip():
            continue
        indent = len(without_comment) - len(without_comment.lstrip(" "))
        lines.append((indent, without_comment.strip()))
    return lines


def _parse_mapping(
    lines: list[tuple[int, str]],
    start_index: int,
    indent: int,
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    index = start_index
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent != indent:
            msg = f"Unexpected indentation at line {index + 1}"
            raise ValueError(msg)
        if ":" not in content:
            msg = f"Expected mapping entry at line {index + 1}"
            raise ValueError(msg)

        key, raw_value = content.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value:
            result[key] = _parse_scalar(raw_value)
            index += 1
            continue

        index += 1
        if index >= len(lines) or lines[index][0] <= current_indent:
            result[key] = {}
            continue
        if lines[index][1].startswith("- "):
            result[key], index = _parse_list(lines, index, lines[index][0])
        else:
            result[key], index = _parse_mapping(lines, index, lines[index][0])
    return result, index


def _parse_list(
    lines: list[tuple[int, str]],
    start_index: int,
    indent: int,
) -> tuple[list[Any], int]:
    result: list[Any] = []
    index = start_index
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent != indent or not content.startswith("- "):
            break

        item_content = content[2:].strip()
        index += 1
        if _looks_like_inline_mapping(item_content):
            item, index = _parse_list_mapping_item(lines, index, indent, item_content)
            result.append(item)
            continue
        result.append(_parse_scalar(item_content))
    return result, index


def _looks_like_inline_mapping(content: str) -> bool:
    if not content or ":" not in content:
        return False
    key, _raw_value = content.split(":", 1)
    return bool(key.strip())


def _parse_list_mapping_item(
    lines: list[tuple[int, str]],
    start_index: int,
    list_indent: int,
    first_entry: str,
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    key, raw_value = first_entry.split(":", 1)
    result[key.strip()] = _parse_scalar(raw_value.strip()) if raw_value.strip() else {}

    index = start_index
    child_indent = list_indent + 2
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent <= list_indent:
            break
        if current_indent != child_indent:
            msg = f"Unexpected indentation at line {index + 1}"
            raise ValueError(msg)
        if ":" not in content:
            msg = f"Expected mapping entry at line {index + 1}"
            raise ValueError(msg)
        key, raw_value = content.split(":", 1)
        result[key.strip()] = _parse_scalar(raw_value.strip()) if raw_value.strip() else {}
        index += 1
    return result, index


def _parse_scalar(value: str) -> Any:
    if value == "[]":
        return []
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value.strip('"').strip("'")
