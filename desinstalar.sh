#!/usr/bin/env bash
# desinstalar.sh — Remove o FireTaskBar completamente
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/firetaskbar"
EXT_UUID="firetaskbar@firetaskbar"
EXT_DEST="$HOME/.local/share/gnome-shell/extensions/$EXT_UUID"
KB_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/firetaskbar/"

echo "=== Desinstalando FireTaskBar ==="
echo ""

# ── Para o daemon ──────────────────────────────────────────────────────────────
pkill -f "firetaskbar.py" 2>/dev/null \
    && echo "✅ Daemon encerrado" \
    || echo "ℹ️  Daemon não estava rodando"

# ── Remove arquivos ────────────────────────────────────────────────────────────
rm -rf "$INSTALL_DIR" \
    && echo "✅ Diretório removido: $INSTALL_DIR" \
    || echo "ℹ️  Diretório não encontrado"

# ── Remove a extensão do GNOME Shell ────────────────────────────────────────────
if command -v gnome-extensions &>/dev/null; then
    gnome-extensions disable "$EXT_UUID" 2>/dev/null || true
fi
rm -rf "$EXT_DEST" \
    && echo "✅ Extensão removida: $EXT_DEST" \
    || echo "ℹ️  Extensão não encontrada"

rm -f "$HOME/.local/share/applications/firetaskbar.desktop" \
    && echo "✅ .desktop removido" || true

rm -f "$HOME/.config/autostart/firetaskbar.desktop" \
    && echo "✅ Autostart removido" || true

rm -f /tmp/firetaskbar.log 2>/dev/null || true

# ── Remove atalho de teclado ───────────────────────────────────────────────────
CURRENT=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null || echo "[]")
if echo "$CURRENT" | grep -q "firetaskbar"; then
    NEW=$(echo "$CURRENT" \
        | sed "s|, '$KB_PATH'||g" \
        | sed "s|'$KB_PATH', ||g" \
        | sed "s|'$KB_PATH'||g")
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$NEW" 2>/dev/null || true
    echo "✅ Atalho de teclado removido"
fi

# ── Restaura tecla Super (opcional) ───────────────────────────────────────────
echo ""
read -rp "Restaurar a tecla Super para o GNOME Activities? [s/N] " resp
if [[ "${resp,,}" == "s" ]]; then
    gsettings set org.gnome.mutter overlay-key 'Super_L' 2>/dev/null \
        && echo "✅ Tecla Super restaurada" \
        || echo "⚠️  Não foi possível restaurar"
fi

echo ""
echo "FireTaskBar desinstalado com sucesso."
