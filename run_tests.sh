#!/bin/bash
# Test runner script for local development

set -e

echo "========================================="
echo "  YouTube Shorts Automation - Test Suite"
echo "========================================="

# Colors for output
GREEN="[0;32m"
RED="[0;31m"
YELLOW="[1;33m"
NC="[0m"  # No Color

echo -e "${YELLOW}Checking dependencies...${NC}"

# Check if pytest is installed
if ! python -c "import pytest" 2>/dev/null; then
    echo -e "${RED}Error: pytest not installed${NC}"
    echo "Install with: pip install -r requirements-dev.txt"
    exit 1
fi

# Check if database is accessible
if ! python -c "import asyncpg" 2>/dev/null; then
    echo -e "${RED}Error: asyncpg not installed${NC}"
    exit 1
fi

echo -e "${GREEN}Dependencies OK${NC}"
echo ""

# Run tests by category
echo -e "${YELLOW}Running unit tests...${NC}"
pytest tests/unit/ -v --cov=app --cov-report=term-missing

echo ""
echo -e "${YELLOW}Running integration tests...${NC}"
pytest tests/integration/ -v

echo ""
echo -e "${YELLOW}Running task tests...${NC}"
pytest tests/tasks/ -v

echo ""
echo -e "${YELLOW}Running E2E tests...${NC}"
pytest tests/e2e/ -v -m e2e

echo ""
echo -e "${GREEN}All tests passed!${NC}"
echo ""
echo "Coverage report saved to: htmlcov/index.html"
echo "Open with: open htmlcov/index.html (macOS) or start htmlcov/index.html (Windows)"
