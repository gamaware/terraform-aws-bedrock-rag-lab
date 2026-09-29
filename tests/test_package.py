"""The Lambda package imports from a zip laid out like the Terraform archive, with only boto3 beside it."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "harbor_rag"


def test_handlers_import_from_the_zip_layout(tmp_path: Path) -> None:
    archive = tmp_path / "harbor_rag.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in sorted(SRC.glob("*.py")):
            zf.write(path, f"harbor_rag/{path.name}")
    code = (
        "import sys; sys.path[:0] = [sys.argv[1]]; "
        "import harbor_rag.handler, harbor_rag.ingest; "
        "assert not any(m.startswith(('harbor_eval', 'yaml')) for m in sys.modules), 'eval code leaked'; "
        "assert harbor_rag.handler.__file__.startswith(sys.argv[1])"
    )
    result = subprocess.run(  # the interpreter under test, no shell
        [sys.executable, "-I", "-c", code, str(archive)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
