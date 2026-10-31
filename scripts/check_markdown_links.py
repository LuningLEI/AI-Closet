"""Fail when repository Markdown contains a broken or machine-local link."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_DIRECTORIES = {".git", "closet_picture", "artifacts", "build"}


def markdown_files(root: Path):
    for path in root.rglob("*.md"):
        relative = path.relative_to(root)
        if any(part in SKIP_DIRECTORIES for part in relative.parts):
            continue
        if relative.parts and relative.parts[0] == "evaluation" and relative != Path("evaluation/README.md"):
            continue
        yield path


def broken_links(root: Path) -> list[str]:
    broken = []
    for path in markdown_files(root):
        for raw_target in LINK.findall(path.read_text(errors="ignore")):
            target = unquote(raw_target.strip("<>").split("#", 1)[0])
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if Path(target).is_absolute():
                broken.append(f"{path.relative_to(root)}: machine-local path {target}")
                continue
            if not (path.parent / target).resolve().exists():
                broken.append(f"{path.relative_to(root)}: missing {target}")
    return broken


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    failures = broken_links(root)
    if failures:
        print("\n".join(failures))
        return 1
    print("Local Markdown links resolve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
