#!/usr/bin/env bash
# Usage: smoke_image.sh <image>
# Needs PostgreSQL published on the host at POSTGRES_PORT (default 5432) with an empty database.
set -euo pipefail
cd "$(dirname "$0")/.."

image=${1:?usage: $0 <image>}
container=ik-smoke
expected_version=$(tr -d '[:space:]' < VERSION)
encryption_key=$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(base64.urlsafe_b64encode(os.urandom(32))).decode())')

cleanup() {
  local rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "Smoke test failed, container logs:"
    docker logs "$container" 2>&1 | tail -200 || true
  fi
  docker rm -f "$container" >/dev/null 2>&1 || true
  exit $rc
}
trap cleanup EXIT

# Bridge networking: the image's nginx also tries port 80, which only works without host networking.
docker run -d --name "$container" \
  --add-host=host.docker.internal:host-gateway \
  -p 8000:8000 -p 8080:8080 \
  -e POSTGRES_HOST=host.docker.internal \
  -e POSTGRES_PORT="${POSTGRES_PORT:-5432}" \
  -e POSTGRES_USER="${POSTGRES_USER:-postgres}" \
  -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}" \
  -e POSTGRES_DB="${POSTGRES_DB:-infrakitchen}" \
  -e POSTGRES_MIGRATIONS=true \
  -e JWT_KEY="$(openssl rand -hex 32)" \
  -e ENCRYPTION_KEY="$encryption_key" \
  "$image" >/dev/null

echo "Waiting for API health check"
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8000/zstatus >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://localhost:8000/zstatus >/dev/null

echo "Checking UI is served by nginx"
curl -fsS http://localhost:8080/ | grep -qi '<div id="root"'

echo "Checking guest login"
token=$(curl -fsS -o /dev/null -D - http://localhost:8080/api/auth/guest/callback/super |
  tr -d '\r' | grep -i '^set-cookie: guest-token=' | sed 's/^[^=]*=//; s/;.*//')
[[ -n "$token" ]] || { echo "guest-token cookie not set"; exit 1; }

echo "Checking server version"
version=$(curl -fsS http://localhost:8080/api/graphql \
  -H "Authorization: Bearer $token" \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ serverInfo { version } }"}' |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["data"]["serverInfo"]["version"])')
if [[ "${version#v}" != "$expected_version" ]]; then
  echo "Expected version $expected_version, got $version"
  exit 1
fi

echo "Smoke test passed for $image (version $version)"
