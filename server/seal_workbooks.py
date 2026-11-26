"""Encrypt the original XLS files or workbook-derived scenarios for GitHub Pages."""

import argparse
from io import BytesIO
from pathlib import Path
import secrets
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .data import workbook_paths
from .planning_api import WORKBOOK_EXAMPLES


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--data", type=Path, help="Directory containing the 12 original XLS files")
    source.add_argument("--planning-examples", type=Path, help="Directory containing the workbook-derived scenarios")
    parser.add_argument("--key-file", type=Path, required=True, help="Private file containing a 256-bit key in hex")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    key = bytes.fromhex(args.key_file.read_text(encoding="ascii").strip())
    if len(key) != 32:
        parser.error("The workbook key must be 256 bits")

    if args.data is not None:
        paths = [path for _, path in workbook_paths(args.data)]
    else:
        paths = [args.planning_examples / f"{name}.json" for name in WORKBOOK_EXAMPLES]
    seal_files(paths, key, args.output)


def seal_files(paths: list[Path], key: bytes, destination: Path) -> None:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.name)
    # The first 12 bytes carry the GCM nonce. AESGCM appends its authentication tag.
    nonce = secrets.token_bytes(12)
    payload = nonce + AESGCM(key).encrypt(nonce, buffer.getvalue(), None)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(payload)
            output.close()
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
