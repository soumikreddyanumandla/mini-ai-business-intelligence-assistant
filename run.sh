#!/usr/bin/env bash
# ==============================================================================
# Mini AI Business Intelligence Assistant - Quick Runner Script
# RSG Research Private Limited • GET Selection Challenge
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "Installing dependencies..."
    venv/bin/pip install -r requirements.txt
fi

COMMAND="${1:-all}"

case "$COMMAND" in
    backend)
        echo "Starting FastAPI backend on port 8000..."
        venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
        ;;
    frontend)
        echo "Starting Streamlit frontend on port 8501..."
        venv/bin/streamlit run frontend/app.py --server.port 8501 --server.headless true
        ;;
    test)
        echo "Running automated Pytest suite..."
        venv/bin/pytest -v
        ;;
    all)
        echo "=================================================================="
        echo " Starting Mini AI Business Intelligence Assistant (Backend + Frontend)"
        echo "=================================================================="
        echo "Backend API:  http://127.0.0.1:8000 (Swagger docs: http://127.0.0.1:8000/docs)"
        echo "Frontend App: http://127.0.0.1:8501"
        echo "=================================================================="
        
        # Start backend in background
        venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
        BACKEND_PID=$!
        
        # Trap SIGINT/SIGTERM to cleanly kill both
        trap "kill $BACKEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM EXIT
        
        # Give backend a moment to boot
        sleep 2
        
        # Start frontend in foreground
        venv/bin/streamlit run frontend/app.py --server.port 8501 --server.headless true
        ;;
    *)
        echo "Usage: ./run.sh [backend|frontend|test|all]"
        exit 1
        ;;
esac
