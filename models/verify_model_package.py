#!/usr/bin/env python3
"""Verify common resources and one configured target, without loading the NPU."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

MODEL = 'Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice'
COMMON = {'config', 'code_predictor_tables', 'codec_embedding', 'talker_prefix_kv', 'codec_rope_cos', 'codec_rvq_tables', 'text_embedding', 'tokenizer', 'codec_rope_sin'}
GRAPHS = {'talker', 'codec_b1', 'code_predictor', 'codec_b2', 'codec_a'}

def verify(root, target=None):
    root = Path(root).resolve(strict=True)
    def safe(name):
        if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
            raise ValueError("Invalid resource path")
        rel = PurePosixPath(name)
        if rel.is_absolute() or any(x in ("", ".", "..") for x in name.split("/")):
            raise ValueError("Invalid relative resource path: " + name)
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or path == root: raise ValueError("Resource escapes package: " + name)
        return path
    checks = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        if len(line) <= 66 or line[64:66] not in ("  ", " *"): raise ValueError("Malformed SHA256SUMS")
        sha, name = line[:64], line[66:]
        safe(name)
        if sha.strip("0123456789abcdef") or name in checks: raise ValueError("Invalid/duplicate checksum entry")
        checks[name] = sha
    def check(name):
        path = safe(name)
        if name not in checks or not path.is_file(): raise ValueError("Missing required resource/checksum: " + name)
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(4194304), b""): h.update(block)
        if h.hexdigest() != checks[name]: raise ValueError("SHA256 mismatch: " + name)
    check("models.json")
    config = json.loads((root / "models.json").read_text())
    if config.get("format_version") != 2 or config.get("model") != MODEL:
        raise ValueError("Unsupported models.json format/model")
    resources = config["resources"]
    if not COMMON <= resources.keys(): raise ValueError("Missing common resource roles")
    candidates, identities = [], set()
    for item in config["targets"]:
        label = item["soc"] + "_qnn" + item["qnn_version"].replace(".", "")
        if label in identities or item["qnn_version"] != "2.48": raise ValueError("Duplicate/unsupported target")
        identities.add(label)
        directory = safe(item["directory"])
        if not GRAPHS <= item["files"].keys(): raise ValueError("Missing target graph roles")
        for name in item["files"].values():
            path = safe(name)
            if path == directory or not path.is_relative_to(directory): raise ValueError("File outside target directory")
        if target == label or target is None and all(safe(x).is_file() for x in item["files"].values()): candidates.append(item)
    if len(candidates) != 1: raise ValueError("Select exactly one complete target with --target")
    selected = candidates[0]
    required = {"models.json", "NOTICE"} | set(selected["files"].values())
    for name in resources.values():
        path = safe(name)
        if path.is_dir():
            members = set()
            for member in path.rglob("*"):
                rel = member.relative_to(root).as_posix();safe(rel)
                if member.is_symlink() and member.is_dir(): raise ValueError("Symlinked resource directory")
                if member.is_file(): members.add(rel)
            if not members: raise ValueError("Empty required resource directory")
            required |= members | {x for x in checks if x.startswith(name + "/")}
        else: required.add(name)
    legal = safe("LICENSES")
    if not legal.is_dir(): raise ValueError("Missing model licenses")
    legal_members = {p.relative_to(root).as_posix() for p in legal.rglob("*") if p.is_file()}
    if not legal_members: raise ValueError("Missing model license files")
    required |= legal_members | {x for x in checks if x.startswith("LICENSES/")}
    for name in sorted(required): check(name)
    return {"target":selected["soc"] + "_qnn" + selected["qnn_version"].replace(".", ""),
            "verified_required_files":len(required), "complete":True}

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__);p.add_argument("root");p.add_argument("--target")
    a = p.parse_args();print(json.dumps(verify(a.root, a.target)))
