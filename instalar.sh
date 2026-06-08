#!/usr/bin/env bash
# instalar.sh — Instala o FireTaskBar a partir do GitHub ou localmente
# Uso local:    bash instalar.sh
# Uso remoto:   bash <(curl -fsSL https://raw.githubusercontent.com/xFireHide/firetaskbar/main/instalar.sh)
set -euo pipefail

GITHUB_USER="xFireHide"
REPO_NAME="firetaskbar"
REPO_URL="https://github.com/$GITHUB_USER/$REPO_NAME.git"
INSTALL_DIR="$HOME/.local/share/firetaskbar"

# ── Detecta modo: local (clone) ou bootstrap (curl) ──────────────────────────
SCRIPT_DIR=""
# BASH_SOURCE[0] pode ser /dev/fd/XX quando executado via curl pipe
if [[ -n "${BASH_SOURCE[0]:-}" ]] && [[ "${BASH_SOURCE[0]}" != /dev/fd/* ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [[ -z "$SCRIPT_DIR" ]] || [[ ! -f "$SCRIPT_DIR/firetaskbar.py" ]]; then
    echo "=== Modo bootstrap: baixando repositório ==="
    if command -v git &>/dev/null; then
        if [[ -d "$INSTALL_DIR/.git" ]]; then
            echo "Repositório já existe, atualizando..."
            git -C "$INSTALL_DIR" pull --ff-only
        else
            git clone "$REPO_URL" "$INSTALL_DIR"
        fi
    else
        echo "git não encontrado — instalando..."
        if command -v dnf &>/dev/null; then
            sudo dnf install -y git
        elif command -v apt-get &>/dev/null; then
            sudo apt-get install -y git
        elif command -v pacman &>/dev/null; then
            sudo pacman -S --noconfirm git
        else
            echo "ERRO: Instale o git manualmente e rode novamente." >&2
            exit 1
        fi
        git clone "$REPO_URL" "$INSTALL_DIR"
    fi
    SCRIPT_DIR="$INSTALL_DIR"
fi

# ── Copia arquivos para o diretório permanente (se necessário) ───────────────
REAL_SCRIPT="$(realpath "$SCRIPT_DIR")"
REAL_INSTALL="$(realpath "$INSTALL_DIR" 2>/dev/null || echo "$INSTALL_DIR")"

EXT_UUID="firetaskbar@firetaskbar"

if [[ "$REAL_SCRIPT" != "$REAL_INSTALL" ]]; then
    mkdir -p "$INSTALL_DIR"
    cp "$SCRIPT_DIR/firetaskbar.py"   "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/instalar.sh"   "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/desinstalar.sh" "$INSTALL_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR/reiniciar.sh"  "$INSTALL_DIR/" 2>/dev/null || true
    # Vendoriza a extensão junto, para o desinstalador/manutenção encontrarem.
    rm -rf "$INSTALL_DIR/$EXT_UUID"
    cp -r "$SCRIPT_DIR/$EXT_UUID" "$INSTALL_DIR/" 2>/dev/null || true
fi

chmod +x "$INSTALL_DIR/firetaskbar.py"

APP="python3 $INSTALL_DIR/firetaskbar.py"
APP_DAEMON="python3 $INSTALL_DIR/firetaskbar.py --daemon"

echo ""
echo "=== Instalando FireTaskBar ==="
echo ""

# ── 1. Dependências ───────────────────────────────────────────────────────────
echo "--- Verificando dependências..."

if command -v dnf &>/dev/null; then
    sudo dnf install -y python3-gobject gtk4 gobject-introspection \
        && echo "✅ Dependências instaladas (dnf)" \
        || echo "⚠️  Falha ao instalar dependências via dnf"
    # gtk4-layer-shell: ancora o menu na tela no Wayland (opcional)
    sudo dnf install -y gtk4-layer-shell 2>/dev/null \
        && echo "✅ gtk4-layer-shell instalado" \
        || echo "ℹ️  gtk4-layer-shell não disponível (opcional)"

elif command -v apt-get &>/dev/null; then
    sudo apt-get update -qq
    sudo apt-get install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 \
        && echo "✅ Dependências instaladas (apt)" \
        || echo "⚠️  Falha ao instalar dependências via apt"
    sudo apt-get install -y libgtk4-layer-shell0 2>/dev/null \
        && echo "✅ gtk4-layer-shell instalado" \
        || echo "ℹ️  gtk4-layer-shell não disponível (opcional)"

elif command -v pacman &>/dev/null; then
    sudo pacman -S --noconfirm python-gobject gtk4 \
        && echo "✅ Dependências instaladas (pacman)" \
        || echo "⚠️  Falha ao instalar dependências via pacman"

else
    echo "⚠️  Gerenciador de pacotes não reconhecido."
    echo "     Instale manualmente: PyGObject + GTK4"
fi

echo ""

# ── 2. Extensão do GNOME Shell (barra de tarefas + ancoragem do menu) ─────────
echo "--- Instalando extensão do GNOME Shell..."
EXT_DEST="$HOME/.local/share/gnome-shell/extensions/$EXT_UUID"
if [[ -d "$SCRIPT_DIR/$EXT_UUID" ]]; then
    mkdir -p "$EXT_DEST"
    cp -r "$SCRIPT_DIR/$EXT_UUID/." "$EXT_DEST/"
    echo "✅ Extensão copiada para $EXT_DEST"
    if command -v gnome-extensions &>/dev/null; then
        gnome-extensions enable "$EXT_UUID" 2>/dev/null \
            && echo "✅ Extensão habilitada" \
            || echo "ℹ️  Habilite após o login: gnome-extensions enable $EXT_UUID"
    fi
    echo "ℹ️  No Wayland, faça logout/login para o GNOME carregar a extensão."
else
    echo "⚠️  Pasta da extensão ($EXT_UUID) não encontrada — pulando."
fi

echo ""

# ── 3. Arquivo .desktop (aparece em buscas) ───────────────────────────────────
DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_DIR/firetaskbar.desktop" << EOF
[Desktop Entry]
Name=FireTaskBar
Comment=Meu launcher de aplicativos
Exec=$APP
Icon=view-grid-symbolic
Terminal=false
Type=Application
Categories=Utility;
Keywords=menu;apps;launcher;
EOF
echo "✅ Entrada .desktop criada"

# ── 4. Autostart: daemon sobe junto com o GNOME ───────────────────────────────
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_DIR/firetaskbar.desktop" << EOF
[Desktop Entry]
Name=FireTaskBar (daemon)
Comment=Mantém o menu em segundo plano para abrir rápido
Exec=$APP_DAEMON
Icon=view-grid-symbolic
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
EOF
echo "✅ Autostart configurado (inicia com o sistema)"

# ── 5. Atalho de teclado: tecla Super ─────────────────────────────────────────
echo ""
echo "--- Configurando tecla Super..."

# A extensão captura o toque do Super pelo sinal 'overlay-key' do Mutter e abre
# o FireTaskBar no lugar do Overview. Para isso o Mutter PRECISA continuar emitindo
# esse sinal, então mantemos overlay-key = 'Super_L' (NÃO esvaziar).
#
# Obs.: NÃO usar atalho custom do gnome-settings-daemon com 'Super_L' — o gsd
# não consegue capturar uma tecla modificadora isolada e falha com
# "Failed to grab accelerator". Removemos qualquer atalho 'firetaskbar' antigo.
gsettings set org.gnome.mutter overlay-key 'Super_L' 2>/dev/null \
    && echo "✅ Super_L mapeada para o FireTaskBar (via extensão)" \
    || echo "⚠️  Não foi possível ajustar overlay-key (verifique manualmente)"

KB_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/firetaskbar/"
CURRENT=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null || echo "@as []")
if echo "$CURRENT" | grep -q "firetaskbar"; then
    NEW_LIST=$(printf '%s' "$CURRENT" | sed "s|, *'$KB_PATH'||; s|'$KB_PATH', *||; s|\['$KB_PATH'\]|@as []|")
    gsettings set org.gnome.settings-daemon.plugins.media-keys \
        custom-keybindings "$NEW_LIST" 2>/dev/null || true
    gsettings reset-recursively \
        "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$KB_PATH" 2>/dev/null || true
    echo "🧹 Atalho gsd antigo (quebrado) removido"
fi

# ── 6. Inicia o daemon agora ──────────────────────────────────────────────────
echo ""
echo "--- Iniciando daemon..."

pkill -f "firetaskbar.py" 2>/dev/null || true
sleep 0.3

nohup $APP_DAEMON > /tmp/firetaskbar.log 2>&1 &
sleep 1

if pgrep -f "firetaskbar.py" > /dev/null; then
    echo "✅ Daemon rodando (PID: $(pgrep -f 'firetaskbar.py'))"
else
    echo "⚠️  Daemon não iniciou — veja o log: cat /tmp/firetaskbar.log"
fi

# ── Resumo ─────────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo "  PRONTO! FireTaskBar instalado."
echo "============================================"
echo ""
echo "  Tecla Super (Windows) → abre/fecha o menu"
echo "  Instalado em: $INSTALL_DIR"
echo ""
echo "  Se a Super não funcionar de imediato:"
echo "  → Configurações > Teclado > Atalhos"
echo "  → Atalhos Personalizados > FireTaskBar"
echo "  → Pressione a tecla Windows para confirmar"
echo ""
echo "  Para desinstalar:"
echo "    bash $INSTALL_DIR/desinstalar.sh"
echo ""
