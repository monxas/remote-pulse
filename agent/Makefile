.PHONY: build clean test build-binary lint format

# Build standalone binary with PyInstaller
build-binary:
	@echo "Building Remote-Pulse binary..."
	uv sync --all-extras --dev
	uv run pyinstaller rp.spec --clean --noconfirm
	@echo ""
	@echo "Binary built successfully:"
	@ls -lh dist/rp* 2>/dev/null || ls -lh dist/*.exe 2>/dev/null
	@echo ""
	@echo "Test with: ./dist/rp version"

# Clean build artifacts
clean:
	rm -rf dist build *.spec.bak __pycache__ .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Run tests
test:
	uv run pytest -v

# Lint code
lint:
	uv run ruff check .

# Format code
format:
	uv run ruff format .

# Lint and format check (CI-style)
check: lint
	uv run ruff format --check .

# Cross-compile Linux arm64 via Docker (experimental)
# Requires: Docker with buildx, QEMU configured
build-linux-arm64-docker:
	@echo "Building Linux arm64 binary via Docker..."
	@echo "Note: This is experimental and may not work on all systems"
	docker run --rm --platform linux/arm64 -v $(shell pwd):/work -w /work \
		python:3.12-slim \
		bash -c "apt-get update && apt-get install -y binutils && \
		         pip install uv && \
		         uv sync --all-extras --dev && \
		         uv run pyinstaller rp.spec --clean --noconfirm"
	@echo "Binary: $(shell pwd)/dist/rp"

# Help
help:
	@echo "Remote-Pulse Agent Build System"
	@echo ""
	@echo "Targets:"
	@echo "  build-binary              Build standalone binary with PyInstaller"
	@echo "  clean                     Remove build artifacts"
	@echo "  test                      Run pytest"
	@echo "  lint                      Run ruff linter"
	@echo "  format                    Format code with ruff"
	@echo "  check                     Lint + format check (CI-style)"
	@echo "  build-linux-arm64-docker  Cross-compile Linux arm64 (Docker required)"
	@echo "  help                      Show this help"
