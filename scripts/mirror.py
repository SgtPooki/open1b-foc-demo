#!/usr/bin/env python3
"""Mirror one Gensyn artifact to Filecoin Onchain Cloud as 1000 MiB pieces.

  mirror.py --kind handoff --step 101 --source gs://... --data-set-id N path/to/file
  mirror.py --kind checkpoint --step 100 --source gs://... --data-set-id N path/to/dir

A directory is streamed through tar before splitting. Each part becomes one
piece (calibnet providers cap pieces at 1 GiB). Results are appended to
data/mirror.json.

ponytail: sequential uploads, one CLI process per part. Parallelize when the
SDK batches addPieces across processes safely.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIRROR = os.path.join(ROOT, "data", "mirror.json")
PIN = os.environ.get("FILECOIN_PIN", "filecoin-pin").split()
CREDS = os.path.expanduser(os.environ.get("FILECOIN_PIN_CREDS", "~/.filecoin-pin.env"))
PART = 1000 * 1024 * 1024


def digests(path):
    """Gensyn commits BLAKE2b-256 of the artifact bytes; SHA-256 is kept for humans."""
    b2, s2 = hashlib.blake2b(digest_size=32), hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 24), b""):
            b2.update(c)
            s2.update(c)
    return {"blake2b256": b2.hexdigest(), "sha256": s2.hexdigest()}


def split(path, parts_dir, prefix):
    os.makedirs(parts_dir, exist_ok=True)
    existing = sorted(p for p in os.listdir(parts_dir) if p.startswith(prefix + "."))
    if existing:
        return existing  # resume: parts already staged from an earlier run
    split_cmd = ["split", "-b", str(PART), "-a", "3", "-d", "-", f"{parts_dir}/{prefix}."]
    if os.path.isdir(path):
        tar = subprocess.Popen(["tar", "-C", os.path.dirname(path), "-cf", "-", os.path.basename(path)], stdout=subprocess.PIPE)
        subprocess.run(split_cmd, stdin=tar.stdout, check=True)
        tar.stdout.close()
        if tar.wait() != 0:
            raise SystemExit("tar failed")
    else:
        with open(path, "rb") as f:
            subprocess.run(split_cmd, stdin=f, check=True)
    return sorted(p for p in os.listdir(parts_dir) if p.startswith(prefix + "."))


def upload(part_path, data_set_id, meta):
    cmd = [*PIN, "--credentials-file", CREDS, "add", "--network", "calibration", "--data-set-id", str(data_set_id)]
    for k, v in meta.items():
        cmd += ["--metadata", f"{k}={v}"]
    cmd.append(part_path)
    for attempt in range(3):
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        m = {k: re.search(rx, out) for k, rx in {
            "rootCid": r"Root CID: (\S+)", "pieceCid": r"Piece CID: (\S+)", "pieceId": r"Piece ID: (\d+)"}.items()}
        if all(m.values()) and "confirmed on-chain" in out:
            return {"rootCid": m["rootCid"].group(1), "pieceCid": m["pieceCid"].group(1), "pieceId": int(m["pieceId"].group(1))}
        sys.stderr.write(f"attempt {attempt + 1} failed for {part_path}\n{out[-800:]}\n")
    raise SystemExit(f"gave up on {part_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", required=True)
    ap.add_argument("--step", type=int, required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--data-set-id", type=int, required=True)
    ap.add_argument("--parts-dir", default=os.path.join(ROOT, "parts"))
    ap.add_argument("path")
    a = ap.parse_args()

    prefix = f"{a.kind}-{a.step}"
    is_dir = os.path.isdir(a.path)
    entry = {
        "kind": a.kind, "step": a.step, "source": a.source, "packaging": "tar" if is_dir else "raw",
        "size": sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(a.path) for f in fs) if is_dir else os.path.getsize(a.path),
        "files": sum(len(fs) for _, _, fs in os.walk(a.path)) if is_dir else None,
        **({} if is_dir else digests(a.path)),
        "parts": [],
        "uploadedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    names = split(a.path, a.parts_dir, prefix)
    print(f"{prefix}: {len(names)} parts", flush=True)
    for i, n in enumerate(names):
        p = os.path.join(a.parts_dir, n)
        # One custom key: the provider caps metadata keys per piece and filecoin-pin uses some itself.
        r = upload(p, a.data_set_id, {"gensyn": f"{a.kind}:{a.step}:{i}/{len(names)}"})
        entry["parts"].append({"index": i, "size": os.path.getsize(p), **digests(p), **r})
        print(f"  part {i}/{len(names) - 1} piece #{r['pieceId']} {r['pieceCid']}", flush=True)
        os.remove(p)

    mirror = json.load(open(MIRROR)) if os.path.exists(MIRROR) else {"pieces": []}
    mirror["pieces"] = [p for p in mirror["pieces"] if p["source"] != a.source] + [entry]
    mirror["generatedAt"] = entry["uploadedAt"]
    json.dump(mirror, open(MIRROR, "w"), indent=1)
    print("recorded", a.source)


if __name__ == "__main__":
    main()
