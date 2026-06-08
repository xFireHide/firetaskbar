#!/usr/bin/env bash
# reiniciar.sh — Reinicia o daemon do FireTaskBar para aplicar mudanças
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$SCRIPT_DIR/firetaskbar.py"

echo "Reiniciando FireTaskBar..."

pkill -f "firetaskbar.py" 2>/dev/null && sleep 0.4 || true

nohup python3 "$APP" --daemon > /tmp/firetaskbar.log 2>&1 &
sleep 1

if pgrep -f "firetaskbar.py" > /dev/null; then
    echo "OK — daemon rodando (PID: $(pgrep -f 'firetaskbar.py' | head -1))"
else
    echo "ERRO — veja o log:"
    cat /tmp/firetaskbar.log
    exit 1
fi
