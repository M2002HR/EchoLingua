from __future__ import annotations

from typing import Any


def loads(text: str) -> dict[str, Any]:
    """Small YAML subset parser for EchoLingua example configs.

    Supports nested mappings, lists of mappings, strings, booleans, integers, and null.
    PyYAML is still the supported dependency; this keeps local tests runnable offline.
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    last_key_at_indent: dict[int, tuple[Any, str]] = {}
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            item_text = line[2:]
            if not isinstance(parent, list):
                owner, key = last_key_at_indent[indent]
                new_list: list[Any] = []
                owner[key] = new_list
                parent = new_list
                stack.append((indent - 1, parent))
            if ":" in item_text:
                key, value = item_text.split(":", 1)
                item: dict[str, Any] = {key.strip(): _parse_scalar(value.strip())}
                parent.append(item)
                stack.append((indent, item))
                last_key_at_indent[indent + 2] = (item, key.strip())
            else:
                parent.append(_parse_scalar(item_text))
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            node: dict[str, Any] = {}
            parent[key] = node
            stack.append((indent, node))
            last_key_at_indent[indent + 2] = (parent, key)
        else:
            parent[key] = _parse_scalar(value)
            last_key_at_indent[indent + 2] = (parent, key)
    return root


def _parse_scalar(value: str) -> Any:
    if value in {"null", "None", "~"}:
        return None
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value
