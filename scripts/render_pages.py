#!/usr/bin/env python3
"""Render the source PDF to one PNG per page for vision-based extraction.

Usage:
    python scripts/render_pages.py [PDF_PATH] [--dpi 200] [--out extraction/pages]

Requires `pdftoppm` (poppler-utils) on PATH.
"""
from __future__ import annotations

import argparse
import glob
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PDF = next(iter(sorted(ROOT.glob("*.pdf"))), None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", nargs="?", default=str(DEFAULT_PDF) if DEFAULT_PDF else None)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--out", default=str(ROOT / "extraction" / "pages"))
    args = ap.parse_args()

    if not args.pdf or not Path(args.pdf).exists():
        print("PDF not found; pass the path explicitly.", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cmd = ["pdftoppm", "-r", str(args.dpi), "-png", args.pdf, str(out / "p")]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    n = len(glob.glob(str(out / "p*.png")))
    print(f"rendered {n} pages into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
