#!/bin/sh
# Container start. DEMO_MODE=true seeds sample accounts once (random passwords, printed to the service log).
set -e
python -m app.cli init-db
if [ "$DEMO_MODE" = "true" ] && [ ! -f "$DATA_DIR/.demo_seeded" ]; then
  python -m app.cli demo-data && touch "$DATA_DIR/.demo_seeded"
  echo "=== Demo accounts are listed above (shown once). Also saved in $DATA_DIR/demo-accounts.txt ==="
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
