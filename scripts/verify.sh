#!/usr/bin/env bash
# Rebuild a mirrored Gensyn artifact from its Filecoin pieces and check it
# against the digest Gensyn committed (BLAKE2b-256 of the artifact bytes).
#
#   scripts/verify.sh <source-uri> [out-dir]
#
# Reads data/mirror.json for the piece list, fetches each piece's CAR from the
# storage provider, unpacks it, concatenates the parts, and compares.
#
#   scripts/verify.sh gs://gensyn-open-1b/open-1b/handoffs/step_000000101/handoff.safetensors
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
src=$1; out=${2:-$here/verify-out}
mkdir -p "$out"

entry=$(python3 -c "import json,sys; m=json.load(open('$here/data/mirror.json')); print(json.dumps(next(p for p in m['pieces'] if p['source']==sys.argv[1])))" "$src")
svc=$(python3 -c "import json; print(json.load(open('$here/data/mirror.json'))['dataSet']['serviceUrl'])")
expected=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('blake2b256') or '')" "$entry")
n=$(python3 -c "import json,sys; print(len(json.loads(sys.argv[1])['parts']))" "$entry")

: > "$out/artifact"
for i in $(seq 0 $((n - 1))); do
  read -r piece root < <(python3 -c "import json,sys; p=json.loads(sys.argv[1])['parts'][$i]; print(p['pieceCid'], p['rootCid'])" "$entry")
  echo "part $i/$((n - 1)): $piece"
  curl -fsSL "$svc/piece/$piece" -o "$out/part.car"
  rm -rf "$out/part"; npx --yes ipfs-car unpack "$out/part.car" --root "$root" --output "$out/part" >/dev/null
  cat "$(find "$out/part" -type f | head -1)" >> "$out/artifact"
done

actual=$(python3 -c "import hashlib,sys; h=hashlib.blake2b(digest_size=32)
with open(sys.argv[1],'rb') as f:
    for c in iter(lambda: f.read(1<<24), b''): h.update(c)
print(h.hexdigest())" "$out/artifact")
echo "gensyn committed (blake2b-256): $expected"
echo "rebuilt from Filecoin:          $actual"
[ -n "$expected" ] && [ "$actual" = "$expected" ] && echo MATCH || { echo "MISMATCH or no committed digest (directories are tar-packed; compare per-file)"; exit 1; }
