#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

version=$(tr -d '[:space:]' < VERSION)
lib_version=$(node -p "require('./ui/frontend-lib/package.json').version")

if [[ "$version" != "$lib_version" ]]; then
  echo "Version mismatch: VERSION=$version, ui/frontend-lib/package.json=$lib_version"
  echo "Run ./scripts/bump_version.sh $version"
  exit 1
fi
echo "Version $version is in sync"
