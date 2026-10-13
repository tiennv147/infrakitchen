#!/usr/bin/env bash
# Runs against the empty database configured via POSTGRES_* env vars.
set -euo pipefail
cd "$(dirname "$0")/../server"

run_alembic() {
  PYTHONPATH=src uv run alembic -c src/alembic.ini "$@"
}

heads=$(run_alembic heads | grep -c '(head)' || true)
if [[ "$heads" -ne 1 ]]; then
  echo "Expected exactly one migration head, found $heads:"
  run_alembic heads
  exit 1
fi

run_alembic upgrade head
run_alembic downgrade -1
run_alembic upgrade head
# Fails when models changed without a matching migration.
run_alembic check
