"""Build report/REPORT.pdf from report/REPORT.md with pandoc and xelatex.

REPORT.md is the canonical deliverable; the PDF is generated from it and never
edited by hand. The build runs in the same pinned pandoc/latex image, with the
same arguments, as the shared gamaware/.github report workflow that CI calls.
Relative links become links to the repository on GitHub, so they still work
when the PDF travels on its own.

    make report          # rebuild the PDF and report/REPORT.sha256 (needs Docker)
    make report-check    # offline: the committed PDF was built from the current REPORT.md

report/REPORT.sha256 records the hashes of REPORT.md and REPORT.pdf at build
time, so `make verify` can check the pair without Docker or a LaTeX install.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

# Keep in step with PANDOC_IMAGE in gamaware/.github/.github/workflows/report.yml.
PANDOC_IMAGE = "pandoc/latex:3.11@sha256:cdbf139f607237498b412b3aa051008311d69b88006ab47550efba357af3b277"
# Also passed as `pandoc-args` to the report job in .github/workflows/ci.yml.
PANDOC_ARGS = [
    "--pdf-engine=xelatex",
    "-V",
    "geometry:margin=2.2cm",
    "-V",
    "papersize=a4",
    "--toc",
    "--shift-heading-level-by=-1",
    # Smaller code font so the 110-column tool output fits the page. No spaces:
    # the shared workflow splits pandoc-args on whitespace.
    "-V",
    r"header-includes=\RecustomVerbatimEnvironment{Highlighting}{Verbatim}"
    r"{commandchars=\\\{\},fontsize=\scriptsize}",
]
REPO_URL = "https://github.com/gamaware/terraform-aws-bedrock-rag-lab/blob/main"
ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "report" / "REPORT.md"
OUTPUT = ROOT / "report" / "REPORT.pdf"
HASHES = ROOT / "report" / "REPORT.sha256"

# Markdown link targets that are relative paths, e.g. ](../after/) or ](../docs/adr/0001-x.md#a)
RELATIVE_LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)")


def absolutize(markdown: str) -> str:
    def repl(match: re.Match[str]) -> str:
        target = (SOURCE.parent / match.group(1)).resolve()
        path, _, anchor = str(target.relative_to(ROOT)).partition("#")
        return f"]({REPO_URL}/{path}{'#' + anchor if anchor else ''})"

    return RELATIVE_LINK.sub(repl, markdown)


def main() -> int:
    if shutil.which("docker") is None:
        print("error: make report needs Docker to run the pinned pandoc/latex image", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        pathlib.Path(tmp, "REPORT.md").write_text(absolutize(SOURCE.read_text(encoding="utf-8")), encoding="utf-8")
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "-e",
                "HOME=/tmp",
                "-e",
                "SOURCE_DATE_EPOCH=0",
                "-v",
                f"{tmp}:/data",
                "-w",
                "/data",
                PANDOC_IMAGE,
                "REPORT.md",
                *PANDOC_ARGS,
                "-o",
                "REPORT.pdf",
            ],
            check=True,
        )
        shutil.copyfile(pathlib.Path(tmp, "REPORT.pdf"), OUTPUT)
    subprocess.run(
        ["shasum", "-a", "256", "report/REPORT.md", "report/REPORT.pdf"],
        cwd=ROOT,
        check=True,
        stdout=HASHES.open("w", encoding="utf-8"),
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)} and {HASHES.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
