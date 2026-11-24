"""Build the GitHub Pages viewer with its browser runtime and encrypted workbooks."""

import argparse
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile


PYODIDE_FILES = (
    "pyodide.mjs", "pyodide.mjs.map", "pyodide-lock.json",
    "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for the static site")
    parser.add_argument("--pyodide", type=Path, required=True, help="Directory containing the Pyodide browser runtime")
    parser.add_argument("--xlrd", type=Path, required=True, help="Path to the xlrd wheel")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "web", args.output)
    index = args.output / "index.html"
    html = index.read_text(encoding="utf-8")
    if 'data-source="api"' not in html:
        raise ValueError("Data source marker missing from index.html")
    index.write_text(html.replace('data-source="api"', 'data-source="workbooks"', 1), encoding="utf-8")

    runtime = args.output / "runtime"
    runtime.mkdir()
    for name in PYODIDE_FILES:
        shutil.copyfile(args.pyodide / name, runtime / name)
    with ZipFile(runtime / "application.zip", "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted((root / "server").rglob("*.py")):
            archive.write(path, path.relative_to(root))
    shutil.copyfile(args.xlrd, runtime / "xlrd.whl")
    shutil.copyfile(root / "pages" / "workbooks.zip.enc", args.output / "workbooks.zip.enc")


if __name__ == "__main__":
    main()
