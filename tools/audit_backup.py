"""Audit sanitized source and application constants without executing binaries.

Run with Python 3.11 and PyInstaller installed. Values are never printed.
"""
import ast
import json
import marshal
from pathlib import Path
import re
import sys
import types

from PyInstaller.archive.readers import CArchiveReader


PATTERNS = {
    "long-hex-value": re.compile(r"\b[a-fA-F0-9]{32,}\b"),
    "provider-token": re.compile(r"(?:gh[pousr]_|github_pat_|sk-proj-|AKIA)[A-Za-z0-9_-]{16,}"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "legacy-ftp-password": re.compile(r"password" + r"123"),
}
APP_MODULES = {"maifocus_edge_agent", "local_agent", "camera_simulator", "app", "ftp_server"}
EXCLUDE = {".git", "build", "dist", "__pycache__", "build-simulator", "dist-simulator"}


def constants(code):
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from constants(value)
        elif isinstance(value, str):
            yield value


def check(text, label):
    errors = []
    for name, pattern in PATTERNS.items():
        if pattern.search(text):
            errors.append(f"{label}: {name}")
    return errors


def main():
    root = Path(sys.argv[1]).resolve()
    errors = []
    count = 0
    for path in root.rglob("*"):
        if not path.is_file() or any(part in EXCLUDE for part in path.relative_to(root).parts):
            continue
        if path.suffix in {".exe", ".zip", ".dll"}:
            continue
        if path.name == "audit_backup.py":
            continue
        text = path.read_text(encoding="utf-8-sig")
        errors.extend(check(text, str(path.relative_to(root))))
        if path.suffix == ".py":
            ast.parse(text, filename=str(path))
        if path.suffix == ".json":
            data = json.loads(text)
            if path.name == "cameras.json":
                assert data["cameras"] == [], path
                assert data["server"]["api_token"] == "", path
                assert data["rtsp"]["password"] == "CHANGE_ME", path
        count += 1
    binary_count = 0
    for argument in sys.argv[2:]:
        path = Path(argument)
        archive = CArchiveReader(str(path))
        found = set()
        for name, entry in archive.toc.items():
            if entry[-1] == "s" and name in APP_MODULES:
                code = marshal.loads(archive.extract(name))
                errors.extend(check("\n".join(constants(code)), path.name + ":" + name))
                found.add(name)
            elif entry[-1] == "z":
                pyz = archive.open_embedded_archive(name)
                for module in APP_MODULES.intersection(pyz.toc):
                    code = pyz.extract(module)
                    errors.extend(check("\n".join(constants(code)), path.name + ":" + module))
                    found.add(module)
        if not found:
            errors.append(path.name + ": no application modules audited")
        print(f"Inspected {path.name}: modules={','.join(sorted(found))}")
        binary_count += 1
    print(f"Checked {count} source/config files and {binary_count} executables; findings={len(errors)}")
    for error in errors:
        print(error)
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
