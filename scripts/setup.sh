#!/bin/bash
# OMNIMIND LOCAL — System Setup
# Run this ONCE on a fresh Ubuntu 24.04 installation
# Usage: sudo ./scripts/setup.sh

set -e

GREEN='\033[0;32m'
NC='\033[0m'
log() { echo -e "${GREEN}[OMNIMIND SETUP]${NC} $1"; }

# ─── System packages ───
log "Updating system packages..."
apt update && apt upgrade -y

log "Installing system dependencies..."
apt install -y \
    build-essential cmake git curl wget \
    python3 python3-pip python3-venv \
    redis-server \
    portaudio19-dev libsndfile1 ffmpeg \
    firejail \
    iptables \
    jq htop tmux

# ─── NVIDIA drivers + CUDA (if not already installed) ───
if ! command -v nvidia-smi &> /dev/null; then
    log "Installing NVIDIA drivers..."
    apt install -y nvidia-driver-550
    log "⚠️  Reboot required after driver installation!"
    log "After reboot, run this script again to continue setup."
fi

# ─── Docker (optional, for containerized deployment) ───
if ! command -v docker &> /dev/null; then
    log "Installing Docker..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    usermod -aG docker $SUDO_USER
    
    # NVIDIA Container Toolkit
    log "Installing NVIDIA Container Toolkit..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
        gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt update && apt install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
fi

# ─── Python environment ───
log "Creating Python virtual environment..."
OMNIMIND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$OMNIMIND_DIR"

python3 -m venv .venv
source .venv/bin/activate

log "Installing Python dependencies..."
pip install --upgrade pip wheel setuptools

# Core
pip install \
    fastapi uvicorn[standard] websockets \
    redis \
    pyyaml python-dotenv \
    httpx aiohttp aiofiles

# LLM
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124

# STT
pip install faster-whisper

# TTS
pip install piper-tts

# Wake word + VAD
pip install openwakeword
pip install silero-vad

# Memory / RAG
pip install chromadb
pip install sentence-transformers
pip install rank-bm25 whoosh

# Embeddings
pip install nomic

# ML / Training
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install transformers datasets accelerate
pip install unsloth
pip install trl  # For DPO

# Audio
pip install pyaudio sounddevice numpy scipy

# Agents
pip install python-obd  # Car OBD-II
pip install caldav      # Calendar

# Security
pip install presidio-analyzer presidio-anonymizer
pip install cryptography

# Monitoring
pip install psutil prometheus-client

# Dev / Testing
pip install pytest pytest-asyncio pytest-cov
pip install ruff mypy  # Linting

log "Setting up Redis..."
systemctl enable redis-server
systemctl start redis-server

# ─── Firewall (privacy) ───
log "Configuring firewall (block all outbound except LAN)..."
# Save current rules first
iptables-save > /etc/iptables.rules.backup

# Allow loopback
iptables -A OUTPUT -o lo -j ACCEPT
# Allow established connections
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
# Allow LAN
iptables -A OUTPUT -d 192.168.0.0/16 -j ACCEPT
iptables -A OUTPUT -d 10.0.0.0/8 -j ACCEPT
iptables -A OUTPUT -d 172.16.0.0/12 -j ACCEPT
# Block everything else (uncomment when ready — blocks internet!)
# iptables -A OUTPUT -j DROP

log "⚠️  Firewall outbound DROP is commented out for now."
log "Uncomment the last iptables rule in this script when ready to go fully offline."

# ─── Systemd service ───
log "Creating systemd service..."
cat > /etc/systemd/system/omnimind.service << EOF
[Unit]
Description=OMNIMIND LOCAL - Leo AI Assistant
After=network.target redis-server.service

[Service]
Type=simple
User=$SUDO_USER
WorkingDirectory=$OMNIMIND_DIR
ExecStart=$OMNIMIND_DIR/.venv/bin/python -m src.core.omnimind
Restart=on-failure
RestartSec=5
Environment=PYTHONPATH=$OMNIMIND_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# ─── Done ───
echo ""
log "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Run: ./scripts/download_models.sh --minimal  (start with 7B)"
echo "  2. Run: ./scripts/start.sh"
echo "  3. Talk to Leo!"
echo ""
echo "To enable as system service: sudo systemctl enable omnimind"
