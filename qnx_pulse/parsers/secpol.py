"""Authentic QNX 8.0 `secpol` security policy text parser."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

TYPE_RE = re.compile(r"^type\s+(?P<name>[^\s;]+)\s*;")
ALLOW_ABILITY_RE = re.compile(
    r"allow\s+(?P<type>[A-Za-z0-9_-]+)\s+self:ability\s*\{(?P<body>[^}]*)\}\s*;",
    re.MULTILINE | re.DOTALL,
)
ALLOW_SINGLE_ABILITY_RE = re.compile(
    r"allow\s+(?P<type>[A-Za-z0-9_-]+)\s+self:ability\s+(?P<ability>[A-Za-z0-9_:,./-]+)\s*;"
)
ALLOW_ATTACH_RE = re.compile(
    r"^allow_attach\s+(?P<type>[A-Za-z0-9_-]+)\s+(?P<path>[^\s;]+)\s*;"
)
ALLOW_CHANNEL_RE = re.compile(
    r"^allow\s+(?P<src>[A-Za-z0-9_-]+)\s+(?P<dst>[A-Za-z0-9_-]+):(?P<obj>channel|connection|process)\s+(?P<perms>[^;]+);"
)
ON_TYPE_RE = re.compile(
    r"^(?:on_type|derive_type)\s+(?P<src>[A-Za-z0-9_-]+)\s+(?P<deriv>[A-Za-z0-9_-]+)\s+(?P<dst>[A-Za-z0-9_-]+)\s*;"
)
USE_RE = re.compile(r"^use\s+(?P<name>[A-Za-z0-9_-]+)\s*;")


@dataclass
class ParsedSecpol:
    types: list[dict[str, Any]] = field(default_factory=list)
    abilities: list[dict[str, Any]] = field(default_factory=list)
    attach_rules: list[dict[str, Any]] = field(default_factory=list)
    channel_rules: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    uses: list[dict[str, Any]] = field(default_factory=list)


def _line_number_at_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _strip_comments_preserve_lines(text: str) -> str:
    cleaned: list[str] = []
    for line in text.splitlines():
        if "#" in line:
            cleaned.append(line.split("#", 1)[0])
        else:
            cleaned.append(line)
    return "\n".join(cleaned)


def parse_secpol(text: str) -> ParsedSecpol:
    """Parse a QNX 8.0 `secpol` policy text file with accurate line tracking."""
    parsed = ParsedSecpol()
    clean_text = _strip_comments_preserve_lines(text)

    # Multi-line `allow <type> self:ability { ... };`
    for m in ALLOW_ABILITY_RE.finditer(clean_text):
        tname = m.group("type")
        line_no = _line_number_at_offset(clean_text, m.start())
        body = m.group("body")
        for token in body.split():
            tok = token.strip().rstrip(",")
            if tok:
                parsed.abilities.append({
                    "line": line_no,
                    "type": tname,
                    "ability": tok,
                })

    # Line-by-line rules
    for idx, raw_line in enumerate(clean_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        tm = TYPE_RE.match(line)
        if tm:
            parsed.types.append({"line": idx, "name": tm.group("name")})
            continue

        am = ALLOW_ATTACH_RE.match(line)
        if am:
            parsed.attach_rules.append({
                "line": idx,
                "type": am.group("type"),
                "path": am.group("path"),
            })
            continue

        sm = ALLOW_SINGLE_ABILITY_RE.match(line)
        if sm:
            parsed.abilities.append({
                "line": idx,
                "type": sm.group("type"),
                "ability": sm.group("ability"),
            })
            continue

        cm = ALLOW_CHANNEL_RE.match(line)
        if cm:
            obj = cm.group("obj")
            perms = cm.group("perms").strip()
            if obj == "process" and "transition" in perms:
                parsed.transitions.append({
                    "line": idx,
                    "from": cm.group("src"),
                    "to": cm.group("dst"),
                    "derivation": "transition",
                })
            else:
                parsed.channel_rules.append({
                    "line": idx,
                    "source": cm.group("src"),
                    "target": cm.group("dst"),
                    "object": obj,
                    "perms": perms,
                })
            continue

        om = ON_TYPE_RE.match(line)
        if om:
            parsed.transitions.append({
                "line": idx,
                "from": om.group("src"),
                "derivation": om.group("deriv"),
                "to": om.group("dst"),
            })
            continue

        um = USE_RE.match(line)
        if um:
            parsed.uses.append({"line": idx, "type": um.group("name")})

    return parsed
