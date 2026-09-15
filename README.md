# open-1b audit record, mirrored to Filecoin Onchain Cloud

A working copy of Gensyn's [OPEN-1B training audit site](https://open1b.gensyn.ai/) where the
artifacts behind every audit live on Filecoin Onchain Cloud (calibration) instead of a
mutable Google Cloud Storage path.

Gensyn's record commits a hash per training step and anchors segment roots to its own
testnet. The bytes those hashes describe are served from `gs://gensyn-open-1b`, which is
public but not content-addressed and not proven. This demo keeps Gensyn's ledger, receipts,
anchors and contributors exactly as their API returns them, and adds for each artifact:

- an IPFS root CID and Filecoin piece CIDs (content addressing, so the CID is the commitment)
- a data set on Filecoin calibration whose provider answers PDP challenges on-chain
- a BLAKE2b-256 check that the bytes on Filecoin equal the digest Gensyn committed

## Layout

```
data/gensyn-api/   snapshot of open1b.gensyn.ai/v1 for every audited step (2026-09-15)
data/mirror.json   what was uploaded: data set, pieces, digests
scripts/mirror.py  split an artifact into 1000 MiB pieces and upload with filecoin-pin
scripts/verify.sh  rebuild an artifact from its pieces and compare BLAKE2b-256
scripts/build-data.py  merge the two into site/data.json
site/              static site, no build step
```

## Run

```
python3 scripts/build-data.py
python3 -m http.server -d site 8080
```

## Mirror an artifact

Every artifact in the run is a public object in `gs://gensyn-open-1b`.

```
curl -L -o handoff.safetensors https://storage.googleapis.com/gensyn-open-1b/open-1b/handoffs/step_000000101/handoff.safetensors
FILECOIN_PIN="node /path/to/filecoin-pin/dist/cli.js" \
scripts/mirror.py --kind handoff --step 101 \
  --source gs://gensyn-open-1b/open-1b/handoffs/step_000000101/handoff.safetensors \
  --data-set-id 36417 handoff.safetensors
```

Calibration providers cap a piece at 1 GiB, so each artifact is split into 1000 MiB parts and
every part is one on-chain piece. Directories are streamed through tar first.

## Verify

```
scripts/verify.sh gs://gensyn-open-1b/open-1b/handoffs/step_000000101/handoff.safetensors
```

Fetches each piece's CAR from the storage provider, unpacks, concatenates, and compares
BLAKE2b-256 against the digest in Gensyn's ledger.

## What was learned about Gensyn's record

- `artifact_digest` is BLAKE2b-256 of the handoff file bytes. Gensyn does not name the
  algorithm; it was found by trying candidates against a byte-identical download (MD5
  matches GCS).
- The Merkle proof in each receipt uses RFC 6962 style tagging, found in the
  `gensyn-audit` wheel (`commitments.verify_inclusion`): `sha256(0x00 || leaf)` and
  `sha256(0x01 || left || right)`, odd nodes promoted unchanged. The site recomputes
  the root in the browser. All 11 receipts verify.
- The same client says its anchors are "still placeholders": the audit tool never
  checks a root against the on-chain transaction. The record only agrees with itself.
- The authoritative commitments are a file, `logs/state_hashes.jsonl` in the bucket,
  about 12 MB for the run. The API is a read-through.
- Anchors go to "Gensyn Testnet" (chain 685685) as calldata to the dead address. They
  commit a 32-byte value; they say nothing about whether the bucket still holds the bytes.
- Published checkpoints are ~19 GB each (150 files, some over 2 GB); handoffs are ~26 GB
  each. 810 checkpoints plus one handoff per audited step.

## Known limits

- One artifact becomes N pieces with N root CIDs. The `filecoin-pin migrate` packer
  (draft PRs #652 to #657) produces one root CID across pieces and should replace
  `scripts/mirror.py` once it accepts local input.
- PDP proving status is linked to the PDP explorer, not read live from chain.
- filecoin-pin 2.0.1 needs two fixes to run on calibration today: a zero-size preflight
  that synapse-core rejects (patched locally in `calculatePieceUploadRequirements`), and
  a data-set enumeration that throws when any of the wallet's providers has no PDP product
  (worked around with `--provider-id 4`).
