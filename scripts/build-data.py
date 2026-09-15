#!/usr/bin/env python3
"""Merge the Gensyn API snapshot with data/mirror.json into site/data.json."""
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = os.path.join(ROOT, "data", "gensyn-api")


def load(name):
    with open(os.path.join(API, name)) as f:
        return json.load(f)


def step_of(name, prefix):
    return int(re.search(rf"{prefix}-(\d+)\.json$", name).group(1))


mirror = json.load(open(os.path.join(ROOT, "data", "mirror.json")))
by_source = {p["source"]: p for p in mirror["pieces"]}

ledger = [json.loads(l) for l in open(os.path.join(API, "ledger.jsonl")) if l.strip()]
receipts = {step_of(p, "receipt"): load(os.path.basename(p)) for p in glob.glob(f"{API}/receipt-*.json")}
anchors = {step_of(p, "anchor"): load(os.path.basename(p)) for p in glob.glob(f"{API}/anchor-*.json")}
segments = {step_of(p, "segment"): load(os.path.basename(p)) for p in glob.glob(f"{API}/segment-*.json")}
contributors = [load(os.path.basename(p)) for p in glob.glob(f"{API}/contributor-*.json")]
coverage = load("coverage.json")

steps = []
for row in ledger:
    r = receipts[row["step"]]
    steps.append({
        **row,
        "receipt": r,
        "predecessorMirror": by_source.get(r["predecessor"]["uri"]),
        "artifactMirror": by_source.get(row["artifact"]),
    })

out = {
    "generatedAt": mirror.get("generatedAt"),
    "run": coverage["run"],
    "coverage": coverage,
    "steps": steps,
    "anchors": anchors,
    "segments": segments,
    "contributors": contributors,
    "foc": {k: v for k, v in mirror.items() if k != "pieces"},
    "pieces": mirror["pieces"],
}
with open(os.path.join(ROOT, "site", "data.json"), "w") as f:
    json.dump(out, f, indent=1)
print(f"steps={len(steps)} mirrored_steps={sum(1 for s in steps if s['artifactMirror'])} pieces={len(mirror['pieces'])}")
