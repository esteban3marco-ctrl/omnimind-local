#!/bin/bash
# OMNIMIND LOCAL — Start all services
set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'
log() { echo -e "${GREEN}[OMNIMIND]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

source .venv/bin/activate 2>/dev/null || true

# Check Redis
if ! redis-cli ping > /dev/null 2>&1; then
    log "Starting Redis..."
    redis-server --daemonize yes
fi

# Determine which LLM model to use
if [ -f "./models/llm/qwen2.5-72b-instruct-q4_k_m.gguf" ]; then
    LLM_MODEL="./models/llm/qwen2.5-72b-instruct-q4_k_m.gguf"
    GPU_LAYERS=45
    info "Using 72B model (primary)"
elif [ -f "./models/llm/qwen2.5-7b-instruct-q8_0.gguf" ]; then
    LLM_MODEL="./models/llm/qwen2.5-7b-instruct-q8_0.gguf"
    GPU_LAYERS=99
    info "Using 7B model (draft)"
else
    echo "ERROR: No LLM model found. Run ./scripts/download_models.sh first."
    exit 1
fi

# Start LLM server
log "Starting LLM server (llama.cpp)..."
llama-server \
    -m "$LLM_MODEL" \
    -ngl $GPU_LAYERS \
    --host 127.0.0.1 \
    --port 8080 \
    -c 8192 \
    --flash-attn \
    -t 12 \
    > ./data/logs/llm_server.log 2>&1 &
LLM_PID=$!
echo $LLM_PID > /tmp/omnimind_llm.pid
info "LLM server PID: $LLM_PID"

# Wait for LLM server to be ready
log "Waiting for LLM server..."
for i in $(seq 1 60); do
    if curl -s http://127.0.0.1:8080/health > /dev/null 2>&1; then
        info "LLM server ready!"
        break
    fi
    sleep 2
done

# Start main OMNIMIND process
log "Starting OMNIMIND core..."
python -m src.core.omnimind > ./data/logs/omnimind.log 2>&1 &
OMNI_PID=$!
echo $OMNI_PID > /tmp/omnimind_core.pid
info "OMNIMIND core PID: $OMNI_PID"

echo ""
log "🧠 Leo is awake!"
echo ""
info "Services running:"
info "  LLM Server:  http://127.0.0.1:8080"
info "  API Gateway:  http://127.0.0.1:3001"
info "  UI Dashboard: http://127.0.0.1:3000"
echo ""
info "Logs: ./data/logs/"
info "Stop: ./scripts/stop.sh"
echo ""
log "Say 'Hey Leo' to start talking!"
