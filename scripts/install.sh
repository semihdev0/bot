#!/bin/bash
# Betronix Bonus Bot - Kurulum Scripti
# =====================================
# Kullanım: sudo bash scripts/install.sh
#
# Bu script:
#   1. Sistem bağımlılıklarını kurar
#   2. Python virtual environment oluşturur
#   3. Playwright Chromium tarayıcısını yükler
#   4. .env dosyasını hazırlar
#   5. systemd servisini kurar

set -euo pipefail

BOT_DIR="/home/user/bot"
SERVICE_FILE="bonus-bot.service"
BOT_USER="user"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ─── 1. Sistem Bağımlılıkları ───────────────────────────────────────────
info "Sistem bağımlılıkları kontrol ediliyor..."

if ! command -v apt-get &>/dev/null; then
    error "Bu script sadece Debian/Ubuntu tabanlı sistemlerde çalışır."
fi

apt-get update -qq
apt-get install -y -qq \
    python3 python3-venv python3-pip \
    libnss3 libatk-bridge2.0-0 libdrm2 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libxshmfence1 libgtk-3-0 \
    libx11-xcb1 fonts-liberation xdg-utils \
    > /dev/null 2>&1

info "Sistem bağımlılıkları kuruldu."

# ─── 2. Python Virtual Environment ──────────────────────────────────────
info "Virtual environment oluşturuluyor..."

PYTHON_CMD="python3"
PYTHON_VER=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VER" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VER" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]; }; then
    warn "Python $PYTHON_VER bulundu. Python 3.11+ önerilir."
fi

cd "$BOT_DIR"

if [ ! -d .venv ]; then
    $PYTHON_CMD -m venv .venv
    info "Virtual environment oluşturuldu: .venv/"
else
    info "Virtual environment zaten mevcut, atlanıyor."
fi

# Activate and install
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
info "Python bağımlılıkları yüklendi."

# ─── 3. Playwright Chromium ─────────────────────────────────────────────
info "Playwright Chromium yükleniyor..."
playwright install chromium
playwright install-deps chromium > /dev/null 2>&1
info "Chromium tarayıcısı yüklendi."

# ─── 4. .env Dosyası ────────────────────────────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    warn ".env dosyası oluşturuldu. Lütfen düzenleyin:"
    warn "  nano $BOT_DIR/.env"
else
    info ".env dosyası zaten mevcut."
fi

# Create logs directory
mkdir -p logs
chown -R "$BOT_USER":"$BOT_USER" "$BOT_DIR"

# ─── 5. systemd Servisi ─────────────────────────────────────────────────
info "systemd servisi kuruluyor..."

cp "$BOT_DIR/scripts/$SERVICE_FILE" /etc/systemd/system/
systemctl daemon-reload
systemctl enable bonus-bot
info "Servis kuruldu ve otomatik başlatma etkinleştirildi."

# ─── 6. Log Rotation ────────────────────────────────────────────────────
if [ -d /etc/logrotate.d ]; then
    cat > /etc/logrotate.d/bonus-bot << 'LOGROTATE'
/home/user/bot/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
LOGROTATE
    info "Log rotation yapılandırıldı (14 gün)."
fi

# ─── Özet ────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  Kurulum Tamamlandı!"
echo "============================================"
echo ""
echo "  Sonraki adımlar:"
echo ""
echo "  1. .env dosyasını düzenleyin:"
echo "     nano $BOT_DIR/.env"
echo ""
echo "  2. Botu başlatın:"
echo "     sudo systemctl start bonus-bot"
echo ""
echo "  3. Durumu kontrol edin:"
echo "     sudo systemctl status bonus-bot"
echo ""
echo "  4. Logları izleyin:"
echo "     sudo journalctl -u bonus-bot -f"
echo ""
echo "  5. Durdurmak için:"
echo "     sudo systemctl stop bonus-bot"
echo ""
