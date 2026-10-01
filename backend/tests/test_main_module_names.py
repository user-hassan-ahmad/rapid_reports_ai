"""A name imported at module level must never be re-imported inside a function in main.py: Python
then treats it as local to the whole function, and any path that skips the local import raises
UnboundLocalError (template generate failed at the response step when structure validation was off)."""
import ast
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "src" / "rapid_reports_ai" / "main.py"


def _module_imports(tree: ast.Module) -> set:
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= {a.asname or a.name for a in node.names}
    return names


def test_no_function_shadows_a_module_level_import():
    tree = ast.parse(MAIN.read_text())
    module_names = _module_imports(tree)
    bad = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                if isinstance(node, ast.ImportFrom):
                    for a in node.names:
                        if (a.asname or a.name) == "MODEL_CONFIG" and "MODEL_CONFIG" in module_names:
                            bad.append(f"{fn.name}:{node.lineno}")
    assert not bad, f"MODEL_CONFIG re-imported inside functions: {bad}"
