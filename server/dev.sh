#!/usr/bin/env bash
# Development helper script for Remote-Pulse server

set -e

cd "$(dirname "$0")"

case "${1:-help}" in
    install)
        echo "Installing dependencies with uv..."
        uv sync --all-extras
        ;;
    migrate)
        echo "Running database migrations..."
        uv run alembic upgrade head
        ;;
    run)
        echo "Starting server on http://0.0.0.0:8080"
        uv run uvicorn rp_server.main:app --reload --host 0.0.0.0 --port 8080
        ;;
    test)
        echo "Running tests..."
        uv run pytest -v
        ;;
    shell)
        echo "Starting Python shell with imports..."
        uv run python -i -c "from rp_server.models import *; from rp_server.schemas import *; from rp_server.auth import *"
        ;;
    token)
        echo "Generating test enrollment token..."
        uv run python -c "
from rp_server.auth import create_enrollment_token
token, jti = create_enrollment_token('test-group', 'dev-script', ttl_hours=24, max_uses=1)
print(f'Token: {token}')
print(f'JTI: {jti}')
"
        ;;
    help)
        echo "Remote-Pulse Server Dev Helper"
        echo ""
        echo "Usage: ./dev.sh [command]"
        echo ""
        echo "Commands:"
        echo "  install  - Install dependencies with uv"
        echo "  migrate  - Run database migrations"
        echo "  run      - Start development server"
        echo "  test     - Run test suite"
        echo "  shell    - Start Python shell with imports"
        echo "  token    - Generate test enrollment token"
        echo "  help     - Show this message"
        ;;
    *)
        echo "Unknown command: $1"
        echo "Run './dev.sh help' for usage"
        exit 1
        ;;
esac
