#!/usr/bin/env bash
# Validate configuration without starting services

echo "Running configuration validation..."
python -c "import asyncio; from app.core.validation import validate_all; asyncio.run(validate_all())"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Configuration is valid!"
else
    echo ""
    echo "❌ Configuration validation failed!"
    exit 1
fi
