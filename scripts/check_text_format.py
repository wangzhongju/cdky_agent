#!/usr/bin/env python3
"""Validate text files are UTF-8 and LF-only line endings."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".svgz",
    ".mp3",
    ".wav",
    ".ogg",
    ".flac",
    ".aac",
    ".m4a",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".zip",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    ".jar",
    ".war",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".so",
    ".a",
    ".o",
    ".obj",
    ".dll",
    ".exe",
    ".bin",
    ".db",
    ".sqlite",
    ".sqlite3",
}

SKIP_DIRS = {
    ".git",
    "node_modules",
    "build",
    "dist",
    "out",
    ".venv",
    "venv",
    "__pycache__",
}


def git_files() -> list[Path]:
    files: set[Path] = set()
    commands = [
        ["git", "ls-files", "-z"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ]

    for command in commands:
        output = subprocess.check_output(command, cwd=ROOT)
        for raw in output.split(b"\x00"):
            if not raw:
                continue
            files.add(Path(raw.decode("utf-8", errors="ignore")))

    return sorted(files)


def is_binary_content(data: bytes) -> bool:
    if not data:
        return False

    sample = data[:4096]
    if b"\x00" in sample:
        return True

    control_count = sum(1 for b in sample if (b < 9) or (13 < b < 32))
    return (control_count / len(sample)) > 0.30


def should_skip(relpath: Path) -> bool:
    if any(part.lower() in SKIP_DIRS for part in relpath.parts):
        return True
    return relpath.suffix.lower() in BINARY_EXTENSIONS


def main() -> int:
    invalid_encoding: list[str] = []
    invalid_line_endings: list[str] = []

    for relpath in git_files():
        path = ROOT / relpath
        if not path.is_file() or should_skip(relpath):
            continue

        data = path.read_bytes()
        if is_binary_content(data):
            continue

        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            invalid_encoding.append(str(relpath).replace("\\", "/"))
            continue

        if b"\r" in data:
            invalid_line_endings.append(str(relpath).replace("\\", "/"))

    if not invalid_encoding and not invalid_line_endings:
        print("PASS: all checked text files are UTF-8 + LF")
        return 0

    print("FAIL: file format check failed")

    if invalid_encoding:
        print("\nNon-UTF-8 files:")
        for item in invalid_encoding:
            print(f"- {item}")

    if invalid_line_endings:
        print("\nFiles containing CR/CRLF:")
        for item in invalid_line_endings:
            print(f"- {item}")

    return 1


if __name__ == "__main__":
    sys.exit(main())