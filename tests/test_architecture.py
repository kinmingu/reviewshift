import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_does_not_import_backend_or_database_packages() -> None:
    forbidden_prefixes = ("backend", "sqlalchemy", "psycopg", "pgvector")
    for path in (PROJECT_ROOT / "frontend_streamlit").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            assert all(
                not name.startswith(forbidden_prefixes) for name in imported
            ), f"{path.name} imports a forbidden backend dependency: {imported}"

