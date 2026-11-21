#!/usr/bin/env python3
"""Check the prebuilt library against both delivery identity declarations."""
import argparse
import hashlib
import json
from pathlib import Path
import re

LIBRARY = "libqwen3_tts.so"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_lines(sdk):
    lines = (sdk / "lib/SHA256SUMS").read_text().splitlines()
    entries = []
    for index, line in enumerate(lines):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError("invalid SDK SHA256SUMS entry")
        if match[2] == LIBRARY:
            entries.append((index, match[1]))
    if len(entries) != 1:
        raise ValueError("SDK SHA256SUMS must contain exactly one native library entry")
    return lines, entries[0]


def verify(sdk):
    sdk = Path(sdk)
    actual = sha256(sdk / "lib" / LIBRARY)
    declared = json.loads((sdk / "compatibility.json").read_text())["native_library_sha256"]
    lines, (_, checksum) = checksum_lines(sdk)
    runtime=sdk/"lib/qnn248"
    expected=set()
    for line in lines:
        digest, relative=line.split("  ",1)
        if relative.startswith("qnn248/"):
            path=sdk/"lib"/relative
            if ".." in Path(relative).parts or path.is_symlink() or not path.is_file():
                raise ValueError("Invalid bundled runtime checksum path")
            expected.add(relative[len("qnn248/"):])
            if sha256(path)!=digest: raise ValueError("Bundled runtime checksum mismatch: "+relative)
    actual_files={str(p.relative_to(runtime)) for p in runtime.rglob("*") if p.is_file() or p.is_symlink()}
    if not expected or expected!=actual_files:
        raise ValueError("Bundled runtime closure differs from installation checksum list")
    if declared != actual:
        raise ValueError("compatibility.json native_library_sha256 differs from the native library")
    if checksum != actual:
        raise ValueError("SDK SHA256SUMS differs from the native library")
    return actual


def refresh(sdk):
    """Used only by the source-build staging step, never by verification/export."""
    sdk = Path(sdk)
    actual = sha256(sdk / "lib" / LIBRARY)
    metadata = sdk / "compatibility.json"
    data = json.loads(metadata.read_text())
    sums = sdk / "lib/SHA256SUMS"
    if sums.exists():
        lines, (index, _) = checksum_lines(sdk)
        lines[index] = actual + "  " + LIBRARY
    else:
        lines = [actual + "  " + LIBRARY]
    data["native_library_sha256"] = actual
    metadata.write_text(json.dumps(data, indent=2) + "\n")
    sums.write_text("\n".join(lines) + "\n")
    return verify(sdk)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdk", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    try:
        print(verify(args.sdk))
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc) + "\n")
