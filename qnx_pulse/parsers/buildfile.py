"""Authentic QNX 8.0 `mkifs` `.build` file parser."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

VIRTUAL_RE = re.compile(r"\[virtual=(?P<arch>[a-zA-Z0-9_]+)(?:,(?P<boot>[a-zA-Z0-9_+-]+))?\]")
SCRIPT_RE = re.compile(r"\[\+\\?script\]")
ATTR_RE = re.compile(r"\[(?P<attrs>[^\]]+)\]")
ON_CMD_RE = re.compile(r"^on\s+(?P<rest>.+)$")


@dataclass
class BuildLine:
    line_no: int
    text: str
    section: str  # "boot" | "script" | "files" | "top"
    attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedBuildfile:
    arch: Optional[str] = None
    boot_type: Optional[str] = None
    startup_cmd: Optional[str] = None
    startup_line: Optional[int] = None
    kernel_binary: Optional[str] = None
    kernel_flags: list[str] = field(default_factory=list)
    kernel_line: Optional[int] = None
    env_vars: dict[str, str] = field(default_factory=dict)
    script_commands: list[dict[str, Any]] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    waitfor_paths: list[dict[str, Any]] = field(default_factory=list)
    symlinks: list[dict[str, Any]] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    libraries: list[str] = field(default_factory=list)
    secpolpush_line: Optional[int] = None
    secpolpush_path: Optional[str] = None
    has_slogger2: bool = False
    slogger2_line: Optional[int] = None
    raw_lines: list[BuildLine] = field(default_factory=list)


def _parse_attrs(attr_str: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in attr_str.split():
        if "=" in token:
            k, v = token.split("=", 1)
            result[k.strip()] = v.strip()
        else:
            result[token.strip()] = "true"
    return result


def _parse_on_command(line_no: int, cmd: str) -> dict[str, Any]:
    tokens = cmd.split()
    secpol_type: Optional[str] = None
    uid_gid: Optional[str] = None
    prio: Optional[str] = None
    cpu_mask: Optional[str] = None
    binary: Optional[str] = None
    args: list[str] = []

    i = 1  # skip 'on'
    while i < len(tokens):
        tok = tokens[i]
        if tok == "-T" and i + 1 < len(tokens):
            secpol_type = tokens[i + 1]
            i += 2
        elif tok in ("-U", "-u") and i + 1 < len(tokens):
            uid_gid = tokens[i + 1]
            i += 2
        elif tok == "-p" and i + 1 < len(tokens):
            prio = tokens[i + 1]
            i += 2
        elif tok in ("-C", "-R") and i + 1 < len(tokens):
            cpu_mask = tokens[i + 1]
            i += 2
        elif tok.startswith("-"):
            # Flag with or without argument
            if tok in ("-d", "-f", "-W"):
                i += 1
            else:
                i += 2 if (i + 1 < len(tokens) and not tokens[i + 1].startswith("/")) else 1
        else:
            binary = tok
            args = tokens[i + 1 :]
            break

    return {
        "line": line_no,
        "cmd": cmd,
        "binary": binary or "",
        "name": (binary or "").split("/")[-1],
        "secpol_type": secpol_type,
        "uid_gid": uid_gid,
        "priority": prio,
        "cpu": cpu_mask,
        "background": cmd.rstrip().endswith("&"),
        "via_on": True,
        "args": [a for a in args if a != "&"],
    }


def parse_buildfile(text: str) -> ParsedBuildfile:
    """Parse a QNX 8.0 `mkifs` `.build` file into structured sections and metadata."""
    parsed = ParsedBuildfile()
    section = "top"
    brace_depth = 0
    active_attrs: dict[str, str] = {}

    for idx, raw_line in enumerate(text.splitlines(), start=1):
        # Strip inline comments unless inside quotes
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        code_part = stripped.split("#", 1)[0].strip()
        if not code_part:
            continue

        vm = VIRTUAL_RE.search(code_part)
        if vm:
            parsed.arch = vm.group("arch")
            parsed.boot_type = vm.group("boot") or "raw"
            if "{" in code_part:
                section = "boot"
                brace_depth = 1
            else:
                section = "boot"
            continue

        if SCRIPT_RE.search(code_part):
            section = "script"
            if "{" in code_part:
                brace_depth = 1
            continue

        if code_part == "{":
            brace_depth += 1
            if section == "top":
                section = "files"
            continue

        if code_part == "}":
            brace_depth = max(0, brace_depth - 1)
            if brace_depth == 0:
                section = "files"
            continue

        # Attribute directive line (e.g., [uid=0 gid=0 perms=0755] or [type=link])
        if code_part.startswith("[") and code_part.endswith("]") and "=" in code_part:
            active_attrs.update(_parse_attrs(code_part[1:-1]))
            if section == "top":
                section = "files"
            continue
        if code_part.startswith("[") and "{" in code_part:
            am = ATTR_RE.search(code_part)
            if am:
                active_attrs.update(_parse_attrs(am.group("attrs")))
            section = "files"
            brace_depth += 1
            continue

        parsed.raw_lines.append(BuildLine(line_no=idx, text=code_part, section=section, attrs=dict(active_attrs)))

        if section == "boot":
            if code_part.startswith("startup-"):
                parsed.startup_cmd = code_part
                parsed.startup_line = idx
            else:
                # Handle both standalone `KEY=VAL` lines and QNX inline `PATH=... LD_LIBRARY_PATH=... procnto-smp-instr -v`
                tokens = code_part.split()
                cmd_idx = 0
                while cmd_idx < len(tokens) and "=" in tokens[cmd_idx] and not tokens[cmd_idx].startswith("-"):
                    k, v = tokens[cmd_idx].split("=", 1)
                    if k.isupper() or k in ("PATH", "LD_LIBRARY_PATH"):
                        parsed.env_vars[k.strip()] = v.strip()
                        cmd_idx += 1
                    else:
                        break
                if cmd_idx < len(tokens) and tokens[cmd_idx].startswith("procnto"):
                    parsed.kernel_binary = tokens[cmd_idx]
                    parsed.kernel_flags = tokens[cmd_idx + 1 :]
                    parsed.kernel_line = idx

        elif section == "script":
            parsed.script_commands.append({"line": idx, "cmd": code_part})
            # Strip optional mkifs script prefix attributes like `[+session]`
            cmd_body = code_part
            if cmd_body.startswith("[") and "]" in cmd_body:
                cmd_body = cmd_body[cmd_body.index("]") + 1 :].strip()
            tokens = cmd_body.split()
            head = tokens[0] if tokens else ""

            if head == "secpolpush" or head.endswith("/secpolpush"):
                parsed.secpolpush_line = idx
                for i, t in enumerate(tokens):
                    if t == "-i" and i + 1 < len(tokens):
                        parsed.secpolpush_path = tokens[i + 1]
                if not parsed.secpolpush_path:
                    for t in tokens[1:]:
                        if not t.startswith("-"):
                            parsed.secpolpush_path = t
                            break
            elif head == "waitfor":
                if len(tokens) >= 2:
                    parsed.waitfor_paths.append({"line": idx, "path": tokens[1]})
            elif head == "procmgr_symlink":
                if len(tokens) >= 3:
                    parsed.symlinks.append({"line": idx, "target": tokens[1], "link": tokens[2]})
            elif head == "slogger2" or head.endswith("/slogger2"):
                parsed.has_slogger2 = True
                parsed.slogger2_line = idx
                parsed.services.append({
                    "line": idx,
                    "cmd": code_part,
                    "binary": head,
                    "name": "slogger2",
                    "secpol_type": None,
                    "uid_gid": "0:0",
                    "priority": None,
                    "cpu": None,
                    "background": code_part.endswith("&"),
                    "via_on": False,
                    "args": tokens[1:],
                })
            elif head == "on":
                svc = _parse_on_command(idx, code_part)
                if svc["name"] == "slogger2":
                    parsed.has_slogger2 = True
                    parsed.slogger2_line = idx
                parsed.services.append(svc)
            elif head not in ("display_msg", "reopen", "echo", "export", "if", "fi", "else", "then", "PATH=", "LD_LIBRARY_PATH="):
                if "=" not in head:
                    parsed.services.append({
                        "line": idx,
                        "cmd": code_part,
                        "binary": head,
                        "name": head.split("/")[-1],
                        "secpol_type": None,
                        "uid_gid": "0:0",
                        "priority": None,
                        "cpu": None,
                        "background": code_part.endswith("&"),
                        "via_on": False,
                        "args": [t for t in tokens[1:] if t != "&"],
                    })

        else:
            # Filesystem entries
            line_attrs = dict(active_attrs)
            entry_text = code_part
            am = ATTR_RE.match(entry_text)
            if am:
                line_attrs.update(_parse_attrs(am.group("attrs")))
                entry_text = entry_text[am.end() :].strip()
            if not entry_text:
                continue
            target_path = entry_text.split("=", 1)[0].strip()
            source_path = entry_text.split("=", 1)[1].strip() if "=" in entry_text else target_path
            parsed.files.append({
                "line": idx,
                "target": target_path,
                "source": source_path,
                "attrs": line_attrs,
            })
            if ".so" in target_path or ".so" in source_path:
                lib_name = target_path.split("/")[-1]
                if lib_name not in parsed.libraries:
                    parsed.libraries.append(lib_name)

    return parsed
