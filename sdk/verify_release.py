#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify an Ed25519-signed manifest, then every listed payload. Requires OpenSSL 3.

Supply a public key trusted independently of the download. A key bundled beside a
signature does not by itself establish publisher identity. No model files are loaded.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath


def key_fingerprint(public_key):
    der = subprocess.check_output(["openssl", "pkey", "-pubin", "-in", str(public_key), "-outform", "DER"],
                                  stderr=subprocess.PIPE)
    if len(der) != 44 or der[:12] != bytes.fromhex("302a300506032b6570032100"):
        raise ValueError("release verification requires an Ed25519 public key")
    return hashlib.sha256(der).hexdigest()


def verify(manifest, signature, public_key, expected_fingerprint=None):
    manifest = Path(manifest).resolve()
    fingerprint = key_fingerprint(public_key)
    if expected_fingerprint and fingerprint != expected_fingerprint.lower():
        raise ValueError("trusted public-key fingerprint does not match")
    subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(public_key), "-rawin",
                    "-in", str(manifest), "-sigfile", str(signature)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data = json.loads(manifest.read_bytes())
    if data.get("schema") != "sdk-release-manifest-v1" or not data.get("files"):
        raise ValueError("invalid or empty release manifest")
    seen = set()
    for entry in data["files"]:
        name = entry["path"]
        rel = PurePosixPath(name)
        if (not name or "\\" in name or rel.is_absolute() or ".." in rel.parts or
                rel.as_posix() != name or name in seen):
            raise ValueError("unsafe or duplicate manifest path")
        seen.add(name)
        payload = manifest.parent / name
        if any(p.is_symlink() for p in [payload, *payload.parents] if p != manifest.parent.parent):
            raise ValueError("symbolic links are not release payloads")
        if not payload.is_file() or manifest.parent not in payload.resolve().parents:
            raise ValueError("missing or escaped release payload: " + name)
        if type(entry["size"]) is not int or entry["size"] != payload.stat().st_size:
            raise ValueError("payload size differs: " + name)
        if not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]):
            raise ValueError("invalid SHA256 in manifest")
        digest = hashlib.sha256()
        with payload.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            raise ValueError("payload digest differs: " + name)
    controls = {manifest.name}
    signature = Path(signature).resolve()
    if signature.parent == manifest.parent:
        controls.add(signature.name)
    actual = {p.relative_to(manifest.parent).as_posix() for p in manifest.parent.rglob("*") if p.is_file()}
    if any(p.is_symlink() for p in manifest.parent.rglob("*")):
        raise ValueError("release contains a symbolic link")
    if actual != seen | controls:
        raise ValueError("release contains unlisted or missing files")
    return {"verified_files": len(seen), "key_sha256": fingerprint, "version": data.get("sdk_version"),
            "model_revision": data.get("model_revision"), "channel": data.get("channel")}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--signature", required=True)
    ap.add_argument("--public-key", required=True, help="an independently trusted Ed25519 public key")
    ap.add_argument("--key-sha256", help="SHA256 of trusted public key DER")
    a = ap.parse_args()
    try:
        result = verify(a.manifest, a.signature, a.public_key, a.key_sha256)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        ap.exit(1, "verification failed: " + str(exc) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
