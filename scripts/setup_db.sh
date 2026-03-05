#!/usr/bin/env bash
# Apply Alembic migrations to create/update database schema

echo "Applying database migrations..."
python -m alembic upgrade head

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Database setup complete!"
else
    echo ""
    echo "❌ Migration failed!"
    exit 1
fi
