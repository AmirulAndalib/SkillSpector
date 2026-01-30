.PHONY: help install install-dev test test-cov lint format clean build publish release

# Default target
help:
	@echo "Available targets:"
	@echo "  make install      - Install the package in production mode"
	@echo "  make install-dev  - Install the package with development dependencies"
	@echo "  make test         - Run tests"
	@echo "  make test-cov     - Run tests with coverage report"
	@echo "  make lint         - Run linters (ruff, mypy)"
	@echo "  make format       - Format code with ruff"
	@echo "  make clean        - Remove build artifacts and cache files"
	@echo "  make build        - Build the package"
	@echo "  make publish      - Publish to nv-shared-pypi (requires credentials)"
	@echo "  make release      - Run full release process (interactive)"

# Install package in production mode
install:
	pip install -e .

# Install package with development dependencies
install-dev:
	pip install -e ".[dev]"

# Run tests
test:
	pytest tests/

# Run tests with coverage
test-cov:
	pytest --cov=src/skillspector --cov-report=html --cov-report=term tests/

# Run linters
lint:
	@echo "Running ruff..."
	ruff check src/ tests/
	@echo "Running mypy..."
	mypy src/

# Format code
format:
	@echo "Formatting with ruff..."
	ruff check --fix src/ tests/
	ruff format src/ tests/

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf src/*.egg-info
	rm -rf .pytest_cache/
	rm -rf .ruff_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "Clean complete!"

# Build the package
build: clean
	python -m build

# Publish to nv-shared-pypi
publish: build
	@echo "Publishing to nv-shared-pypi..."
	@echo "Note: Credentials will be read from ~/.config/pypoetry/auth.toml or environment variables"
	python -m twine upload --repository-url https://urm.nvidia.com/artifactory/api/pypi/nv-shared-pypi dist/*

# Run release script (interactive)
release:
	@echo "Running release script..."
	@echo "Usage: make release VERSION=<major|minor|patch|dev> USER=<email>"
	@if [ -z "$(VERSION)" ] || [ -z "$(USER)" ]; then \
		echo "Error: VERSION and USER are required."; \
		echo "Example: make release VERSION=patch USER=nraghavan@nvidia.com"; \
		exit 1; \
	fi
	python release.py --version $(VERSION) --user $(USER)
