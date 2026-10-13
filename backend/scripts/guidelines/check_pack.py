"""Gates 1–4 for one pack folder alone (library spec §8). Pack tasks run in parallel and never touch the shared
bundle; the integration task rebuilds it once. The folder is compiled from a temporary copy without its sources/.
Usage: cd backend && PYTHONPATH=src .venv/bin/python scripts/guidelines/check_pack.py <entry-id>"""
import shutil
import sys
import tempfile
from pathlib import Path

from rapid_reports_ai.hybrid_stack.copilot.library.bundle import BundleError, compile_bundle, guidelines_root


def check(pack_dir: Path) -> int:
    if not (pack_dir / "entry.json").exists():
        print(f"{pack_dir}: no entry.json")
        return 1
    with tempfile.TemporaryDirectory() as d:
        shutil.copytree(pack_dir, Path(d) / pack_dir.name, ignore=shutil.ignore_patterns("sources"))
        try:
            b = compile_bundle(Path(d))
        except BundleError as ex:
            print(ex)
            return 1
    print(f"{pack_dir.name}: gates 1-4 pass ({', '.join(sorted(b['entries']))})")
    return 0


if __name__ == "__main__":
    sys.exit(check(guidelines_root() / sys.argv[1]))
