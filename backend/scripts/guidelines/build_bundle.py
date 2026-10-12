"""Compile guidelines/ into the committed bundle (library spec §8). Every entry passes gates 1–4 or nothing is
written. --check exits 1 when the committed bundle is stale.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/build_bundle.py [--check]"""
import argparse
import json
import sys

from rapid_reports_ai.hybrid_stack.copilot.library.bundle import BUNDLE, BundleError, compile_bundle, dumps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    try:
        text = dumps(compile_bundle())
    except BundleError as ex:
        print(ex, file=sys.stderr)
        return 1
    if args.check:
        ok = BUNDLE.exists() and BUNDLE.read_text() == text
        print("bundle up to date" if ok else "bundle stale: run scripts/guidelines/build_bundle.py")
        return 0 if ok else 1
    BUNDLE.write_text(text)
    print(f"wrote {BUNDLE} ({len(json.loads(text)['entries'])} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
