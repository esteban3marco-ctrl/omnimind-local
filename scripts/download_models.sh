#!/bin/bash
# OMNIMIND LOCAL — Model Downloader
# Downloads all required models from HuggingFace
# Usage: ./scripts/download_models.sh [--minimal|--full]

set -e

MODELS_DIR="./models"
MODE="${1:---full}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[OMNIMIND]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

# Check huggingface-cli
if ! command -v huggingface-cli &> /dev/null; then
    warn "huggingface-cli not found. Installing..."
    pip install huggingface_hub --break-system-packages
fi

mkdir -p "$MODELS_DIR"/{llm,stt,tts,embeddings,reranker,wake}

# ─── LLM Models ───
log "Downloading LLM models..."

if [ "$MODE" = "--minimal" ]; then
    info "Minimal mode: downloading 7B only"
    huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF \
        qwen2.5-7b-instruct-q8_0.gguf \
        --local-dir "$MODELS_DIR/llm/"
else
    info "Full mode: downloading 72B + 7B + 3B"
    
    # 72B Primary (Q4_K_M ~42GB)
    log "Downloading Qwen2.5-72B-Instruct (Q4_K_M) — this will take a while..."
    huggingface-cli download Qwen/Qwen2.5-72B-Instruct-GGUF \
        qwen2.5-72b-instruct-q4_k_m.gguf \
        --local-dir "$MODELS_DIR/llm/"
    
    # 7B Draft (Q8 ~8GB)
    log "Downloading Qwen2.5-7B-Instruct (Q8)..."
    huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF \
        qwen2.5-7b-instruct-q8_0.gguf \
        --local-dir "$MODELS_DIR/llm/"
    
    # 3B Mobile (Q4_K_M ~2GB)
    log "Downloading Qwen2.5-3B-Instruct (Q4_K_M)..."
    huggingface-cli download Qwen/Qwen2.5-3B-Instruct-GGUF \
        qwen2.5-3b-instruct-q4_k_m.gguf \
        --local-dir "$MODELS_DIR/llm/"
fi

# ─── STT (faster-whisper) ───
log "Downloading Whisper Large-v3-turbo (CTranslate2)..."
huggingface-cli download Systran/faster-whisper-large-v3-turbo \
    --local-dir "$MODELS_DIR/stt/whisper-large-v3-turbo-ct2/"

# ─── TTS (Piper) ───
log "Downloading Piper TTS voices..."
mkdir -p "$MODELS_DIR/tts"

# Spanish voice
wget -q -O "$MODELS_DIR/tts/es_ES-davefx-medium.onnx" \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx" || \
    warn "Spanish voice download failed — download manually from https://github.com/rhasspy/piper/blob/master/VOICES.md"

wget -q -O "$MODELS_DIR/tts/es_ES-davefx-medium.onnx.json" \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json" 2>/dev/null || true

# English voice
wget -q -O "$MODELS_DIR/tts/en_US-amy-medium.onnx" \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx" || \
    warn "English voice download failed — download manually"

wget -q -O "$MODELS_DIR/tts/en_US-amy-medium.onnx.json" \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json" 2>/dev/null || true

# ─── Embeddings ───
log "Downloading Nomic-Embed-v1.5..."
huggingface-cli download nomic-ai/nomic-embed-text-v1.5 \
    --local-dir "$MODELS_DIR/embeddings/nomic-embed-v1.5/"

# ─── Reranker ───
log "Downloading BGE-Reranker-v2-m3..."
huggingface-cli download BAAI/bge-reranker-v2-m3 \
    --local-dir "$MODELS_DIR/reranker/bge-reranker-v2-m3/"

# ─── Wake Word ───
log "Installing OpenWakeWord..."
pip install openwakeword --break-system-packages 2>/dev/null || pip install openwakeword
info "OpenWakeWord models download automatically on first use"
info "To train custom 'Hey Leo' wake word, see: https://github.com/dscripka/openWakeWord"

# ─── Summary ───
echo ""
log "✅ All models downloaded!"
echo ""
info "Models directory size:"
du -sh "$MODELS_DIR"/*
echo ""
info "Next: run ./scripts/setup.sh to install dependencies"
info "Then: run ./scripts/start.sh to launch OMNIMIND"
