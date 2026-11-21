#!/usr/bin/env python3
"""Verify the detached archive signature before safe extraction and payload checks."""
import argparse
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

from verify_release import key_fingerprint, verify


def verify_archive(archive, signature, public_key, fingerprint, output, allow_candidate=False):
    if key_fingerprint(public_key) != fingerprint.lower():
        raise ValueError("trusted public-key fingerprint does not match")
    subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(public_key),
                    "-rawin", "-in", str(archive), "-sigfile", str(signature)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = Path(output)
    if output.exists():
        raise ValueError("use a new extraction directory")
    with tarfile.open(archive, "r:*") as stream:
        members = stream.getmembers()
        names, size = set(), 0
        for member in members:
            name = member.name.rstrip("/")
            path = PurePosixPath(name)
            if (not name or ":" in name or "\\" in name or path.is_absolute() or ".." in path.parts or
                    path.as_posix() != name or name in names or
                    not (member.isfile() or member.isdir())):
                raise ValueError("unsafe or duplicate archive entry")
            names.add(name)
            size += member.size
        if len(members) > 10000 or size > 1024 ** 3:
            raise ValueError("archive exceeds extraction limits")
        output.mkdir(parents=True)
        try:
            for member in members:
                target = output / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with stream.extractfile(member) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    target.chmod(0o644)
            root = output / "sdk"
            result = verify(root / "release-manifest.json", root / "release-manifest.sig",
                            public_key, fingerprint)
            if result["channel"] != "release" and not allow_candidate:
                raise ValueError("candidate is not a formal release; explicit --allow-candidate is required")
            return result
        except BaseException:
            shutil.rmtree(output)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--signature", required=True)
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--key-sha256", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-candidate", action="store_true")
    args = parser.parse_args()
    try:
        result = verify_archive(args.archive, args.signature, args.public_key,
                                args.key_sha256, args.out, args.allow_candidate)
    except (ValueError, OSError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        parser.exit(1, "verification failed: " + str(exc) + "\n")
    print(__import__("json").dumps(result))


if __name__ == "__main__":
    main()
