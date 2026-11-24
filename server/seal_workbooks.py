"""Encrypt the twelve original XLS files for private access on GitHub Pages."""

import argparse
from io import BytesIO
from pathlib import Path
import secrets
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .data import workbook_paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True, help="Private file containing a 256-bit key in hex")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    key = bytes.fromhex(args.key_file.read_text(encoding="ascii").strip())
    if len(key) != 32:
        parser.error("The workbook key must be 256 bits")

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for _, path in workbook_paths(args.data):
            archive.write(path, path.name)
    # The first 12 bytes carry the GCM nonce. AESGCM appends its authentication tag.
    nonce = secrets.token_bytes(12)
    payload = nonce + AESGCM(key).encrypt(nonce, buffer.getvalue(), None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=args.output.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(payload)
            output.close()
            temporary.replace(args.output)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
