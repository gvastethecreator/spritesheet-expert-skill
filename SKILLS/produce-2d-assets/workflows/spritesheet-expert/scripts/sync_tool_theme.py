#!/usr/bin/env python3
"""Copy the shared tool theme into the static tool pages.

Python emitters inline ``spritecore.tool_theme`` at build time. The curator,
the motion reference review and Studio are static files, so this script writes
the same CSS and theme script between ``tool-theme:start`` and
``tool-theme:end`` markers. Run it after you change ``tool_theme.py``.
``--check`` fails when a page is out of date.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from spritecore.tool_theme import THEME_SCRIPT, TOOL_CSS

SCRIPTS_DIR = Path(__file__).resolve().parent
NOTE = "generated from spritecore/tool_theme.py by sync_tool_theme.py; do not edit"

CSS_BLOCK = (r"/\* tool-theme:start[^*]*\*/", "/* tool-theme:end */", f"/* tool-theme:start ({NOTE}) */", TOOL_CSS)
JS_BLOCK = (r"// tool-theme:start[^\n]*", "// tool-theme:end", f"// tool-theme:start ({NOTE})", THEME_SCRIPT)

TARGETS = {
    SCRIPTS_DIR / "curator" / "curator.css": [CSS_BLOCK],
    SCRIPTS_DIR / "curator" / "curator.js": [JS_BLOCK],
    SCRIPTS_DIR / "motion-reference-review" / "index.html": [CSS_BLOCK, JS_BLOCK],
    SCRIPTS_DIR.parent / "studio" / "tool-theme.css": [CSS_BLOCK],
    SCRIPTS_DIR.parent / "studio" / "tool-theme.js": [JS_BLOCK],
}


def synced(text: str, blocks: list[tuple[str, str, str, str]], path: Path) -> str:
    for start_pattern, end_marker, start_marker, body in blocks:
        pattern = re.compile(start_pattern + r".*?" + re.escape(end_marker), re.DOTALL)
        if not pattern.search(text):
            raise SystemExit(f"{path}: missing tool-theme markers")
        replacement = f"{start_marker}\n{body.strip()}\n{end_marker}"
        text = pattern.sub(lambda _match: replacement, text, count=1)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when a page is out of date; write nothing")
    args = parser.parse_args()
    stale = []
    for path, blocks in TARGETS.items():
        current = path.read_text(encoding="utf-8")
        expected = synced(current, blocks, path)
        if expected == current:
            continue
        stale.append(path)
        if not args.check:
            path.write_text(expected, encoding="utf-8", newline="\n")
    for path in stale:
        print(f"{'stale' if args.check else 'updated'}: {path.relative_to(SCRIPTS_DIR.parents[2])}")
    return 1 if args.check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
