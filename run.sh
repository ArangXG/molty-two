#!/bin/bash
# ╔══════════════════════════════════════════════════════════╗
# ║   MOLTY ROYALE BOT — Ubuntu Cloud Setup & Runner        ║
# ╚══════════════════════════════════════════════════════════╝
set -e

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
RESET="\033[0m"

echo -e "${BOLD}${CYAN}"
echo "╔══════════════════════════════════════════════════╗"
echo "║        MOLTY ROYALE BOT — INSTALLER              ║"
echo "╚══════════════════════════════════════════════════╝"
echo -e "${RESET}"

# ── 1. Check Python ────────────────────────────────────────
echo -e "${BOLD}[1/5] Checking Python...${RESET}"
if ! command -v python3 &>/dev/null; then
    echo "Python3 not found. Installing..."
    sudo apt-get update -qq && sudo apt-get install -y python3 python3-pip python3-venv
fi
PYTHON_VER=$(python3 --version)
echo -e "${GREEN}✓ $PYTHON_VER${RESET}"

# ── 2. Create virtual environment ─────────────────────────
echo -e "${BOLD}[2/5] Setting up virtual environment...${RESET}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${RESET}"
else
    echo -e "${GREEN}✓ Virtual environment already exists${RESET}"
fi

# ── 3. Install dependencies ───────────────────────────────
echo -e "${BOLD}[3/5] Installing dependencies...${RESET}"
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${RESET}"

# ── 4. Environment variables check ────────────────────────
echo -e "${BOLD}[4/5] Environment check...${RESET}"

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠  No .env file found. Creating template...${RESET}"
    cat > .env << 'EOF'
# ── MOLTY ROYALE BOT CONFIG ──────────────────────────────
# Get your API key from: https://www.moltyroyale.com
MOLTY_API_KEY=YOUR_API_KEY_HERE

# Your agent's display name in the game
MOLTY_AGENT_NAME=ShadowStrike_v3

# API endpoint (change if different)
MOLTY_API_BASE=https://www.moltyroyale.com/api

# How fast the bot makes decisions (seconds between ticks)
TICK_INTERVAL=1.0

# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO
EOF
    echo -e "${YELLOW}  → Edit .env with your API key before running!${RESET}"
    echo -e "${YELLOW}  → nano .env${RESET}"
fi

echo -e "${GREEN}✓ Environment ready${RESET}"

# ── 5. Run the bot ────────────────────────────────────────
echo -e "${BOLD}[5/5] Starting bot...${RESET}"
echo ""

if [ -f ".env" ]; then
    # Load .env variables
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

if [ "$MOLTY_API_KEY" = "YOUR_API_KEY_HERE" ] || [ -z "$MOLTY_API_KEY" ]; then
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    echo -e "${YELLOW}  ACTION REQUIRED:${RESET}"
    echo -e "${YELLOW}  1. Open .env file:  nano .env${RESET}"
    echo -e "${YELLOW}  2. Set your API key from moltyroyale.com${RESET}"
    echo -e "${YELLOW}  3. Run again:  bash run.sh${RESET}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
    exit 1
fi

echo -e "${GREEN}🚀 Launching Molty Royale Bot...${RESET}"
echo ""
python3 bot.py
