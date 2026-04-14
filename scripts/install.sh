#!/bin/bash
# Bonus Bot - Tek Komutla Kurulum Scripti
# Kullanım: bash scripts/install.sh

set -e

echo "=== Bonus Approval Bot Kurulumu ==="
echo ""

# Check Python version
PYTHON_CMD=""
if command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    echo "HATA: Python 3 bulunamadı. Lütfen Python 3.11+ kurun."
    exit 1
fi

echo "Python: $($PYTHON_CMD --version)"

# Create virtual environment
echo ""
echo "1. Virtual environment oluşturuluyor..."
$PYTHON_CMD -m venv .venv
source .venv/bin/activate

# Install dependencies
echo "2. Bağımlılıklar yükleniyor..."
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
echo "3. Playwright tarayıcısı yükleniyor..."
playwright install chromium
playwright install-deps chromium

# Create .env if not exists
if [ ! -f .env ]; then
    echo "4. .env dosyası oluşturuluyor..."
    cp .env.example .env
    echo ""
    echo "UYARI: .env dosyasını düzenlemeyi unutmayın!"
    echo "  nano .env"
else
    echo "4. .env dosyası zaten mevcut, atlanıyor."
fi

# Create logs directory
mkdir -p logs

echo ""
echo "=== Kurulum Tamamlandı ==="
echo ""
echo "Sonraki adımlar:"
echo "  1. .env dosyasını düzenleyin: nano .env"
echo "  2. config/ altındaki YAML dosyalarını düzenleyin"
echo "  3. Botu başlatın: bash scripts/run.sh"
echo "  4. Sistem servisi olarak kurmak için:"
echo "     sudo cp scripts/bonus-bot.service /etc/systemd/system/"
echo "     sudo systemctl enable bonus-bot"
echo "     sudo systemctl start bonus-bot"
