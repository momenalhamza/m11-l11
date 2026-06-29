#!/usr/bin/env bash
# Seed Neo4j with the W9B recipe fixture vendored under api/seed.cypher.
# Idempotent — the cypher file uses MERGE + IF NOT EXISTS, so re-running
# does not duplicate nodes or constraints.
# Run from the repo root: bash seed_neo4j.sh
set -euo pipefail

NEO4J_PASSWORD="${NEO4J_PASSWORD:-devpassword}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_URI="${NEO4J_URI:-bolt://localhost:7687}"
SEED_FILE="api/seed.cypher"

if [ ! -f "$SEED_FILE" ]; then
  echo "ERROR: $SEED_FILE not found. Run from the repo root." >&2
  exit 1
fi

echo "Seeding Neo4j (loading $SEED_FILE via cypher-shell inside the neo4j container) ..."

# In local dev the stack is managed by docker compose; in CI the Neo4j
# service container is exposed on localhost and docker compose is not running.
if docker compose ps neo4j 2>/dev/null | grep -q "running"; then
  docker compose exec -T neo4j cypher-shell \
    -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" < "$SEED_FILE"
else
  # CI fallback: connect directly via the Python neo4j driver
  # (already installed from requirements.txt).
  python3 - <<PYEOF
import os, sys
from neo4j import GraphDatabase

uri      = os.environ.get("NEO4J_URI",      "bolt://localhost:7687")
user     = os.environ.get("NEO4J_USER",     "neo4j")
password = os.environ.get("NEO4J_PASSWORD", "devpassword")

with open("$SEED_FILE") as f:
    raw = f.read()

# Strip line comments and split on ";"
statements = []
for stmt in raw.split(";"):
    lines = [l for l in stmt.splitlines() if not l.strip().startswith("//")]
    cleaned = " ".join(lines).strip()
    if cleaned:
        statements.append(cleaned)

driver = GraphDatabase.driver(uri, auth=(user, password))
with driver.session() as session:
    for stmt in statements:
        session.run(stmt)
driver.close()
print(f"Neo4j seeded via direct connection ({len(statements)} statements).")
PYEOF
fi

echo "Done."
