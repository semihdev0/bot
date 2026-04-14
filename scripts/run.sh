#!/bin/bash
# Bonus Bot - Çalıştırma Scripti
# Kullanım: bash scripts/run.sh

set -e

# Navigate to project root
cd "$(dirname "$0")/.."

# Activate virtual environment
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
else
    echo "HATA: Virtual environment bulunamadı. Önce kurulum yapın:"
    echo "  bash scripts/install.sh"
    exit 1
fi

# Check .env exists
if [ ! -f .env ]; then
    echo "HATA: .env dosyası bulunamadı. .env.example'dan kopyalayın:"
    echo "  cp .env.example .env && nano .env"
    exit 1
fi

echo "Bonus Approval Bot başlatılıyor..."
echo "Durdurmak için: Ctrl+C"
echo ""

# Run the bot
python -m src.main
