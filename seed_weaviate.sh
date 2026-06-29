#!/usr/bin/env bash
# Seed Weaviate with the M11 Lab RAG chunk corpus (Boston restaurants).
# Idempotent — re-running skips chunk_ids already present.
# Run from the repo root: bash seed_weaviate.sh
set -euo pipefail

echo "Seeding Weaviate ..."

# In local dev the stack is managed by docker compose and the seeder runs
# inside the api container (no host-side ML deps required). In CI the
# Weaviate service container is exposed on localhost and docker compose is
# not running, so we run the script directly on the host.
if docker compose ps api 2>/dev/null | grep -q "running"; then
  docker compose exec -T \
    -e WEAVIATE_URL="${WEAVIATE_URL:-http://weaviate:8080}" \
    api python /app/api/seed_weaviate.py
else
  # CI fallback: run the seed script directly on the host.
  # WEAVIATE_URL must point to the service container's localhost mapping.
  WEAVIATE_URL="${WEAVIATE_URL:-http://localhost:8080}" \
    python3 api/seed_weaviate.py
fi

echo "Done."
