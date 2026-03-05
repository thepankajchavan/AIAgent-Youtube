.PHONY: test lint format clean install help

help:
	@echo "YouTube Shorts Automation - Development Commands"
	@echo ""
	@echo "Available commands:"
	@echo "  make install    - Install all dependencies"
	@echo "  make test       - Run all tests with coverage"
	@echo "  make lint       - Run linters (ruff, black check)"
	@echo "  make format     - Format code with black"
	@echo "  make clean      - Remove cache and coverage files"
	@echo "  make pre-commit - Install pre-commit hooks"

install:
	pip install --upgrade pip
	pip install -r requirements.txt
	pip install -r requirements-dev.txt

test:
	pytest -v --cov=app --cov-report=html --cov-report=term-missing

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-e2e:
	pytest tests/e2e/ -v -m e2e

lint:
	ruff check app/
	black --check app/
	mypy app/ --ignore-missing-imports

format:
	black app/
	ruff check --fix app/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf .mypy_cache
	rm -rf .ruff_cache

pre-commit:
	pip install pre-commit
	pre-commit install
	pre-commit run --all-files
