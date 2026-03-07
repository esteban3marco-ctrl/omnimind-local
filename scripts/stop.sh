#!/bin/bash
# OMNIMIND LOCAL — Stop all services gracefully
GREEN='\033[0;32m'
NC='\033[0m'
log() { echo -e "${GREEN}[OMNIMIND]${NC} $1"; }

log "Stopping OMNIMIND services..."

# Stop core
if [ -f /tmp/omnimind_core.pid ]; then
    kill $(cat /tmp/omnimind_core.pid) 2>/dev/null && log "Core stopped"
    rm /tmp/omnimind_core.pid
fi

# Stop LLM server
if [ -f /tmp/omnimind_llm.pid ]; then
    kill $(cat /tmp/omnimind_llm.pid) 2>/dev/null && log "LLM server stopped"
    rm /tmp/omnimind_llm.pid
fi

# Kill any remaining llama-server processes
pkill -f "llama-server" 2>/dev/null || true

log "✅ All services stopped."
