"""Count hand-authored application lines, excluding tests/docs/generated data.

This is a size check, not a quality check: review for duplication and dead code.
"""

from __future__ import annotations

import argparse
import io
import json
import tokenize
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDED = {".py", ".js", ".css", ".html"}
EXCLUDED_NAMES = {"__pycache__", "node_modules", "vendor", "generated"}


def _python_lines(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    comment_lines = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                comment_lines.add(token.start[0])
    except tokenize.TokenError as exc:
        raise ValueError(f"cannot count malformed Python: {path}: {exc}") from exc
    return sum(1 for n, line in enumerate(lines, start=1)
               if line.strip() and n not in comment_lines)


def _text_lines(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    return sum(bool(line.strip()) and not line.lstrip().startswith(("/*", "*", "//", "<!--"))
               for line in lines)


def count_sources(root: Path = ROOT) -> tuple[int, dict[str, int], dict[str, int]]:
    source = root / "src"
    if not source.is_dir():
        return 0, {}, {}
    files: dict[str, int] = {}
    by_suffix: dict[str, int] = defaultdict(int)
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix not in INCLUDED:
            continue
        if any(part in EXCLUDED_NAMES for part in path.relative_to(source).parts):
            continue
        count = _python_lines(path) if path.suffix == ".py" else _text_lines(path)
        files[str(path.relative_to(root))] = count
        by_suffix[path.suffix] += count
    return sum(files.values()), dict(by_suffix), files


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure substantive application source")
    parser.add_argument("--min", type=int, default=1000, dest="minimum")
    args = parser.parse_args()
    total, by_suffix, files = count_sources()
    print(json.dumps({"application_loc": total, "minimum": args.minimum,
                      "by_suffix": by_suffix, "files": files}, indent=2, sort_keys=True))
    return 0 if total >= args.minimum else 1


if __name__ == "__main__":
    raise SystemExit(main())
