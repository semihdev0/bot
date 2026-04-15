#!/bin/bash
# Betronix Bonus Bot - Manuel Çalıştırma
# Kullanım: bash scripts/run.sh
#
# systemd servisi yerine manuel çalıştırmak için kullanın.
# Otomatik çalıştırma için: sudo systemctl start bonus-bot

set -euo pipefail

# Navigate to project root
cd "$(dirname "$0")/.."

# Activate virtual environment
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
else
    echo "HATA: Virtual environment bulunamadı."
    echo "  Kurulum yapın: sudo bash scripts/install.sh"
    exit 1
fi

# Check .env
if [ ! -f .env ]; then
    echo "HATA: .env dosyası bulunamadı."
    echo "  cp .env.example .env && nano .env"
    exit 1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Betronix Bonus Bot"
echo "  Durdurmak için: Ctrl+C"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

exec python -m src.main
