#!/usr/bin/env bash
# Autogenerate an Alembic migration and fix the JSONB astext_type render quirk.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -f .migtmp.db
YANTRA_DB_URL="sqlite:///.migtmp.db" uv run alembic -c server/alembic.ini upgrade head
YANTRA_DB_URL="sqlite:///.migtmp.db" uv run alembic -c server/alembic.ini revision --autogenerate -m "$1"
rm -f .migtmp.db
sed -i 's/astext_type=Text()/astext_type=sa.Text()/g' server/yantra_server/db/alembic/versions/*.py
