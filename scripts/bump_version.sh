#!/usr/bin/env bash
# Usage: bump_version.sh <X.Y.Z[-rc.N]>
set -euo pipefail
cd "$(dirname "$0")/.."

new_version=${1:-}
if [[ ! "$new_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]]; then
  echo "Usage: $0 <X.Y.Z or X.Y.Z-rc.N>" >&2
  exit 1
fi

current=$(tr -d '[:space:]' < VERSION)
if ! node -e '
const parse = (v) => {
  const [core, pre] = v.split("-rc.");
  return [...core.split(".").map(Number), pre === undefined ? Infinity : Number(pre)];
};
const [a, b] = [parse(process.argv[1]), parse(process.argv[2])];
const cmp = a.map((x, i) => (x === b[i] ? 0 : x > b[i] ? 1 : -1)).find((d) => d !== 0) ?? 0;
process.exit(cmp > 0 ? 0 : 1);
' "$new_version" "$current"; then
  echo "New version $new_version must be greater than current $current" >&2
  exit 1
fi

echo "$new_version" > VERSION
node -e '
const fs = require("fs");
const path = "ui/frontend-lib/package.json";
const pkg = JSON.parse(fs.readFileSync(path, "utf8"));
pkg.version = process.argv[1];
fs.writeFileSync(path, JSON.stringify(pkg, null, 2) + "\n");
' "$new_version"

echo "Bumped $current -> $new_version"
