#!/bin/bash
# TrendEmpire Bot — one-command Ubuntu 22.04 setup script

set -e  # Exit immediately if any command fails

echo "============================================"
echo "  TrendEmpire Bot — Server Setup"
echo "============================================"

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/6] Updating apt and installing system dependencies..."
sudo apt-get update -y
sudo apt-get install -y python3-pip ffmpeg imagemagick python3-venv

# ImageMagick policy fix — allow PDF/text rendering used by MoviePy
sudo sed -i 's/rights="none" pattern="PDF"/rights="read|write" pattern="PDF"/' \
    /etc/ImageMagick-6/policy.xml 2>/dev/null || true

# ── 2. Python virtual environment ─────────────────────────────────────────────
echo "[2/6] Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# ── 3. Python dependencies ────────────────────────────────────────────────────
echo "[3/6] Installing Python requirements..."
pip install --upgrade pip
pip install -r requirements.txt

# ── 4. Environment file ───────────────────────────────────────────────────────
echo "[4/6] Creating .env from .env.example..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  → .env created. Fill in your API keys before running."
else
    echo "  → .env already exists, skipping."
fi

# ── 5. Output subdirectories ──────────────────────────────────────────────────
echo "[5/6] Creating output subdirectories..."
mkdir -p output/images output/repurposed/tiktok output/repurposed/reels \
         output/repurposed/shorts output/repurposed/spotify logs

# ── 6. Done — print next steps ────────────────────────────────────────────────
echo "[6/6] Setup complete!"
echo ""
echo "============================================"
echo "  NEXT STEPS"
echo "============================================"
echo "1. Edit .env and add your API keys:"
echo "     nano .env"
echo ""
echo "2. Add your YouTube OAuth2 credentials file:"
echo "     Place client_secret.json in this directory"
echo "     (Download from Google Cloud Console → APIs & Services → Credentials)"
echo ""
echo "3. Activate the venv and start the bot:"
echo "     source venv/bin/activate"
echo "     python main.py"
echo ""
echo "4. To run in the background (production):"
echo "     nohup python main.py > logs/server.log 2>&1 &"
echo ""
echo "5. Trigger a manual run via webhook:"
echo '     curl -X POST http://localhost:5000/webhook/run \'
echo '          -H "X-Webhook-Secret: your_secret_here"'
echo "============================================"
