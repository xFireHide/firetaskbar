#!/usr/bin/env python3
"""FireTaskBar Iniciar — daemon singleton, abre com a tecla Super (visual Windows 11)."""

import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GioUnix", "2.0")

# gtk4-layer-shell: posiciona a janela ancorada na tela (como ArcMenu)
# Instale com: sudo dnf install gtk4-layer-shell
_LAYER_SHELL = False
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell  # type: ignore[attr-defined]
    _LAYER_SHELL = True
except Exception:
    pass

from gi.repository import Gdk, Gio, GioUnix, GLib, Graphene, Gsk, Gtk  # noqa: E402


def _usar_layer_shell() -> bool:
    """Só usa gtk4-layer-shell onde o protocolo wlr-layer-shell existe.
    O GNOME/Mutter NÃO o implementa — nele a janela é posicionada pela
    extensão do GNOME Shell, então o layer-shell é ignorado."""
    if not _LAYER_SHELL:
        return False
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").upper()
    return "GNOME" not in desktop


# ── Configuração persistente ──────────────────────────────────────────────────

_CONFIG_PATH = Path.home() / ".config" / "firetaskbar" / "config.json"
# Largura da janela do menu (px) por rótulo. A extensão recentraliza sozinha,
# então mudar a largura "só funciona" no GNOME na hora seguinte que abre.
_LARGURAS = {"estreito": 520, "medio": 640, "largo": 760}
_LARGURA_PADRAO = "medio"
_CONFIG_PADRAO: dict = {
    "bar_height": 52,
    "menu_position": "center",  # estilo Windows 11: centralizado na barra
    "menu_width": _LARGURA_PADRAO,  # estreito | medio | largo
    "menu_color": None,             # None = herda a cor da barra de tarefas
    "pinned": None,   # None = semeia padrões no primeiro uso
    "recent": [],
}


def _carregar_config() -> dict:
    try:
        dados = json.loads(_CONFIG_PATH.read_text())
        return {**_CONFIG_PADRAO, **dados}
    except Exception:
        return dict(_CONFIG_PADRAO)


def _salvar_config(cfg: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def _caminho_avatar() -> str | None:
    """Foto de perfil. O GNOME guarda em /var/lib/AccountsService/icons/<user>
    (definida em Configurações → Usuários), não em ~/.face — então procura nos
    dois lugares, na ordem de preferência."""
    try:
        usuario = pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        usuario = os.environ.get("USER", "")
    candidatos = [
        Path.home() / ".face",
        Path.home() / ".face.icon",
        Path(f"/var/lib/AccountsService/icons/{usuario}") if usuario else None,
    ]
    for c in candidatos:
        if c and c.is_file() and os.access(c, os.R_OK):
            return str(c)
    return None


class AvatarRedondo(Gtk.Widget):
    """Avatar circular de verdade: recorta a textura em círculo (clip no
    snapshot) e preenche o quadrado mantendo a proporção (crop central
    'cover'). O GtkImage com border-radius não recorta o conteúdo no GTK4."""

    def __init__(self, caminho: str, tamanho: int) -> None:
        super().__init__()
        self._tam = tamanho
        try:
            self._tex: Gdk.Texture | None = Gdk.Texture.new_from_filename(caminho)
        except Exception:
            self._tex = None
        self.set_size_request(tamanho, tamanho)
        self.set_overflow(Gtk.Overflow.HIDDEN)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        w, h = self.get_width(), self.get_height()
        if not self._tex or w <= 0 or h <= 0:
            return
        size = min(w, h)
        x0, y0 = (w - size) / 2, (h - size) / 2

        rect = Graphene.Rect().init(x0, y0, size, size)
        circulo = Gsk.RoundedRect()
        circulo.init_from_rect(rect, size / 2)
        snapshot.push_rounded_clip(circulo)

        # Escala "cover": preenche o quadrado mantendo proporção, centralizado.
        tw, th = self._tex.get_width(), self._tex.get_height()
        fator = max(size / tw, size / th)
        dw, dh = tw * fator, th * fator
        dx, dy = x0 + (size - dw) / 2, y0 + (size - dh) / 2
        snapshot.append_texture(self._tex, Graphene.Rect().init(dx, dy, dw, dh))
        snapshot.pop()


# ── Tema (deriva do mesmo arquivo de config da barra de tarefas) ────────────────
# A barra (extensão) grava a cor escolhida em ~/.config/firetaskbar.json. O menu
# lê a MESMA cor para combinar o tema — barra preta ⇒ menu preto.

_TASKBAR_CONFIG = Path.home() / ".config" / "firetaskbar.json"
_COR_BARRA_PADRAO = "rgba(18, 18, 22, 0.96)"


def _ler_cor_barra() -> str:
    try:
        dados = json.loads(_TASKBAR_CONFIG.read_text())
        cor = dados.get("barColor")
        if cor:
            return cor
    except Exception:
        pass
    return _COR_BARRA_PADRAO


def _tema_do(cor: str) -> dict:
    """Deriva um conjunto de tokens de cor a partir da cor base da barra.
    Funciona com qualquer cor: escolhe texto claro/escuro pela luminância."""
    rgba = Gdk.RGBA()
    if not rgba.parse(cor):
        rgba.parse("rgb(18,18,22)")
        cor = _COR_BARRA_PADRAO
    r, g, b, a = rgba.red, rgba.green, rgba.blue, rgba.alpha
    ri, gi, bi = round(r * 255), round(g * 255), round(b * 255)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    escuro = lum < 0.5

    def ov(esc: float, claro: float) -> str:
        # Overlay branco (tema escuro) ou preto (tema claro).
        return f"rgba(255,255,255,{esc})" if escuro else f"rgba(0,0,0,{claro})"

    def txt(alpha: float) -> str:
        return f"rgba(255,255,255,{alpha})" if escuro else f"rgba(22,22,26,{alpha})"

    def clar(v: int, d: int) -> int:
        return max(0, min(255, v + (d if escuro else -d)))

    # A janela do menu é flutuante e sem blur — qualquer transparência deixa o
    # que está atrás (ex.: um vídeo) vazar e fica feio. Então o menu usa SEMPRE
    # a cor opaca (ignora o alpha da barra); a barra pode continuar translúcida.
    bg  = f"rgb({ri},{gi},{bi})"
    pop = f"rgb({clar(ri,14)},{clar(gi,14)},{clar(bi,16)})"

    return {
        "escuro":      escuro,
        "bg":          bg,
        "pop_bg":      pop,
        "elevado":     ov(0.05, 0.035),
        "txt":         txt(0.93),
        "txt_sec":     txt(0.60),
        "txt_mut":     txt(0.45),
        "hover":       ov(0.10, 0.06),
        "ativo":       ov(0.16, 0.10),
        "borda":       ov(0.12, 0.10),
        "borda_in":    ov(0.16, 0.14),
        "accent":      "#4fc3f7",
        "accent_h":    "#74d1f9",
        "accent_txt":  "#06151d",
        "anel_foco":   "rgba(79,195,247,0.30)",
        "perigo":      "#e2563f",
        "perigo_txt":  "#ffffff",
        "sombra":      "0 16px 50px rgba(0,0,0,0.55)" if escuro
                       else "0 16px 50px rgba(0,0,0,0.20)",
        "sombra_pop":  "0 10px 32px rgba(0,0,0,0.55)" if escuro
                       else "0 10px 32px rgba(0,0,0,0.22)",
    }


# ── Categorias ────────────────────────────────────────────────────────────────

CATS: list[tuple[str, str, list[str]]] = [
    ("todos",       "Todos",        []),
    ("internet",    "Internet",     ["Network", "WebBrowser", "Email", "Chat", "InstantMessaging"]),
    ("escritorio",  "Escritório",   ["Office", "WordProcessor", "Spreadsheet", "Presentation"]),
    ("midia",       "Mídia",        ["AudioVideo", "Audio", "Video", "Player", "Recorder"]),
    ("graficos",    "Gráficos",     ["Graphics", "2DGraphics", "VectorGraphics", "Photography"]),
    ("jogos",       "Jogos",        ["Game"]),
    ("dev",         "Dev",          ["Development", "Debugger", "IDE", "TextEditor"]),
    ("sistema",     "Sistema",      ["System", "Monitor", "TerminalEmulator", "FileManager", "Settings", "PackageManager"]),
    ("utilitarios", "Utilitários",  ["Utility", "Archiving", "Calculator", "Viewer", "Security", "Filesystem"]),
    ("educacao",    "Educação",     ["Education", "Science"]),
]
CAT_LABELS  = {k: label for k, label, _ in CATS}
CAT_ICONES  = {
    "todos":       "view-grid-symbolic",
    "internet":    "network-wireless-symbolic",
    "escritorio":  "x-office-document-symbolic",
    "midia":       "multimedia-player-symbolic",
    "graficos":    "applications-graphics-symbolic",
    "jogos":       "applications-games-symbolic",
    "dev":         "applications-engineering-symbolic",
    "sistema":     "preferences-system-symbolic",
    "utilitarios": "applications-utilities-symbolic",
    "educacao":    "applications-science-symbolic",
}


def _cat_de_app(cats_str: str) -> str:
    cats = set(cats_str.split(";")) if cats_str else set()
    for key, _, keywords in CATS[1:]:
        if cats & set(keywords):
            return key
    return "utilitarios"


# ── Lê todos os apps instalados ───────────────────────────────────────────────

def _ler_apps() -> list[dict]:
    # get_all() respeita XDG_DATA_DIRS — cobre /usr/share, ~/.local/share,
    # /var/lib/flatpak/exports/share, ~/.local/share/flatpak/exports/share etc.
    apps: list[dict] = []
    visto: set[str] = set()

    for info in GioUnix.DesktopAppInfo.get_all():
        if not info.should_show():
            continue

        nome = info.get_display_name() or ""
        if not nome or nome in visto:
            continue
        visto.add(nome)

        # Coleta keywords para melhorar a busca
        kws_raw = info.get_keywords()  # retorna lista de strings ou None
        keywords = " ".join(kws_raw).lower() if kws_raw else ""

        apps.append({
            "id":        info.get_id() or nome,
            "nome":      nome,
            "desc":      info.get_description() or "",
            "keywords":  keywords,
            "icone":     info.get_icon(),
            "info":      info,
            "categoria": _cat_de_app(info.get_categories() or ""),
        })

    return sorted(apps, key=lambda a: a["nome"].lower())


def _pontuar_busca(app: dict, q: str) -> int | None:
    """Relevância de um app para a busca `q` (menor = melhor). None = não casa.
    Prioriza nome exato > começa com > palavra começa com > contém > keywords."""
    nome = app["nome"].lower()
    if not q:
        return None
    if nome == q:
        return 0
    if nome.startswith(q):
        return 1
    if any(p.startswith(q) for p in nome.split()):
        return 2
    if q in nome:
        return 3
    if q in app["keywords"]:
        return 4
    if q in app["desc"].lower():
        return 5
    return None


# ── Card de aplicativo (grade Fixados / Todos) ─────────────────────────────────

class CardApp(Gtk.Button):
    def __init__(self, app: dict, janela: "FireTaskBar") -> None:
        super().__init__()
        self._app    = app
        self._info   = app["info"]
        self._id     = app["id"]
        self._janela = janela
        self.add_css_class("card-app")
        self.set_tooltip_text(app["desc"] or app["nome"])

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_halign(Gtk.Align.CENTER)

        img = Gtk.Image()
        img.set_pixel_size(36)
        img.set_from_gicon(app["icone"]) if app["icone"] else img.set_from_icon_name("application-x-executable")
        box.append(img)

        lbl = Gtk.Label(label=app["nome"])
        lbl.set_max_width_chars(11)
        lbl.set_wrap(True)
        lbl.set_justify(Gtk.Justification.CENTER)
        lbl.set_lines(2)
        lbl.set_ellipsize(3)
        lbl.add_css_class("app-label")
        box.append(lbl)

        self.set_child(box)
        self.connect("clicked", self._abrir)

        # Botão direito → fixar / desafixar
        gesto = Gtk.GestureClick()
        gesto.set_button(3)
        gesto.connect("pressed", self._contexto)
        self.add_controller(gesto)

    def set_selecionado(self, on: bool) -> None:
        if on:
            self.add_css_class("card-app-sel")
        else:
            self.remove_css_class("card-app-sel")

    def _abrir(self, _btn) -> None:
        try:
            self._info.launch([], None)
            self._janela.registrar_recente(self._id)
            self._janela.esconder()
        except GLib.Error as e:
            print(f"Erro ao abrir: {e}", file=sys.stderr)

    def _contexto(self, _g, _n, x, y) -> None:
        fixado = self._janela.esta_fixado(self._id)
        pop = Gtk.Popover()
        pop.set_parent(self)
        pop.set_has_arrow(True)
        pop.add_css_class("menu-contexto")

        cx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        item = Gtk.Button(label="Desafixar de Fixados" if fixado else "Fixar em Fixados")
        item.add_css_class("ctx-item")
        item.connect("clicked", lambda _b: (self._janela.alternar_fixado(self._id), pop.popdown()))
        cx.append(item)
        pop.set_child(cx)

        ret = Gdk.Rectangle()
        ret.x, ret.y, ret.width, ret.height = int(x), int(y), 1, 1
        pop.set_pointing_to(ret)
        pop.popup()


# ── Card de categoria (visão "Todos", estilo Windows 11) ───────────────────────

class CardCategoria(Gtk.Button):
    def __init__(self, chave: str, label: str, apps: list[dict], janela: "FireTaskBar") -> None:
        super().__init__()
        self._chave  = chave
        self._janela = janela
        self.add_css_class("card-cat")
        n = len(apps)
        self.set_tooltip_text(f"{label} — {n} {'app' if n == 1 else 'apps'}")

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        col.set_halign(Gtk.Align.CENTER)

        # Mini-grade 2×2 com os primeiros ícones da categoria.
        tile = Gtk.Grid()
        tile.add_css_class("card-cat-tile")
        tile.set_row_spacing(8)
        tile.set_column_spacing(8)
        tile.set_halign(Gtk.Align.CENTER)
        for i, app in enumerate(apps[:4]):
            img = Gtk.Image()
            img.set_pixel_size(34)
            img.set_from_gicon(app["icone"]) if app["icone"] else img.set_from_icon_name("application-x-executable")
            tile.attach(img, i % 2, i // 2, 1, 1)
        col.append(tile)

        nome = Gtk.Label(label=label)
        nome.set_halign(Gtk.Align.CENTER)
        nome.add_css_class("card-cat-label")
        col.append(nome)

        self.set_child(col)
        self.connect("clicked", lambda _b: janela._abrir_categoria(chave))


# ── Botão de ação (popover de energia) ──────────────────────────────────────────

# ── Diálogo de preferências ───────────────────────────────────────────────────

class DialogPreferencias(Gtk.Window):
    def __init__(self, menu: "FireTaskBar") -> None:
        # NÃO usar transient_for=menu: o menu é uma superfície layer-shell
        # (overlay) que se auto-esconde ao perder foco — um diálogo transiente
        # dela fica sem pai válido no Wayland e nunca mapeia. Em vez disso,
        # ancoramos o diálogo na própria aplicação, como toplevel normal.
        super().__init__(title="Configurações — FireTaskBar")
        app = menu.get_application()
        if app is not None:
            self.set_application(app)
        self._menu = menu
        self.set_default_size(420, -1)
        self.set_resizable(False)
        self.add_css_class("pref-janela")

        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(raiz)

        # ── Cabeçalho ─────────────────────────────────────────────────────────
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header.add_css_class("pref-header")
        ic = Gtk.Image.new_from_icon_name("preferences-other-symbolic")
        ic.set_pixel_size(20)
        ic.add_css_class("pref-header-ic")
        header.append(ic)
        titulo = Gtk.Label(label="Configurações do Menu")
        titulo.add_css_class("pref-titulo")
        titulo.set_halign(Gtk.Align.START)
        titulo.set_hexpand(True)
        header.append(titulo)
        raiz.append(header)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        raiz.append(sep)

        # ── Corpo ─────────────────────────────────────────────────────────────
        corpo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        corpo.set_margin_top(24)
        corpo.set_margin_bottom(24)
        corpo.set_margin_start(24)
        corpo.set_margin_end(24)
        raiz.append(corpo)

        # ── Seção: Aparência (largura + cor) ──────────────────────────────────
        # A altura saiu daqui de propósito: no GNOME ela é automática (o menu
        # cola na barra real), então um campo manual só confundiria.
        secao = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        secao.add_css_class("pref-secao")
        corpo.append(secao)

        sec_titulo = Gtk.Label(label="APARÊNCIA")
        sec_titulo.add_css_class("pref-sec-titulo")
        sec_titulo.set_halign(Gtk.Align.START)
        secao.append(sec_titulo)

        # Largura do menu (segmented)
        row_w = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row_w.set_valign(Gtk.Align.CENTER)
        secao.append(row_w)

        info_w = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_w.set_hexpand(True)
        lbl_w = Gtk.Label(label="Largura do menu")
        lbl_w.add_css_class("pref-lbl")
        lbl_w.set_halign(Gtk.Align.START)
        info_w.append(lbl_w)
        sub_w = Gtk.Label(label="Tamanho da janela do menu")
        sub_w.add_css_class("pref-sub")
        sub_w.set_halign(Gtk.Align.START)
        info_w.append(sub_w)
        row_w.append(info_w)

        larg_atual = menu._config.get("menu_width", _LARGURA_PADRAO)
        self._btns_larg: dict[str, Gtk.ToggleButton] = {}
        seg_w = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        seg_w.add_css_class("pref-segmented")
        primeiro_w: Gtk.ToggleButton | None = None
        for val, rotulo, css_extra in [
            ("estreito", "Estreito", "pref-seg-left"),
            ("medio",    "Médio",    "pref-seg-mid"),
            ("largo",    "Largo",    "pref-seg-right"),
        ]:
            b = Gtk.ToggleButton()
            b.add_css_class("pref-seg-btn")
            b.add_css_class(css_extra)
            b.set_child(Gtk.Label(label=rotulo))
            if primeiro_w is None:
                primeiro_w = b
            else:
                b.set_group(primeiro_w)
            b.set_active(val == larg_atual)
            self._btns_larg[val] = b
            seg_w.append(b)
        row_w.append(seg_w)

        # Cor do menu (switch + seletor)
        row_c = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row_c.set_valign(Gtk.Align.CENTER)
        secao.append(row_c)

        info_c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_c.set_hexpand(True)
        lbl_c = Gtk.Label(label="Cor do menu")
        lbl_c.add_css_class("pref-lbl")
        lbl_c.set_halign(Gtk.Align.START)
        info_c.append(lbl_c)
        sub_c = Gtk.Label(label="Desligado = herda a cor da barra de tarefas")
        sub_c.add_css_class("pref-sub")
        sub_c.set_halign(Gtk.Align.START)
        sub_c.set_wrap(True)
        info_c.append(sub_c)
        row_c.append(info_c)

        controles_c = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controles_c.set_valign(Gtk.Align.CENTER)
        row_c.append(controles_c)

        cor_cfg = menu._config.get("menu_color")
        self._switch_cor = Gtk.Switch()
        self._switch_cor.set_valign(Gtk.Align.CENTER)
        self._switch_cor.set_active(bool(cor_cfg))
        controles_c.append(self._switch_cor)

        rgba0 = Gdk.RGBA()
        rgba0.parse(cor_cfg or _ler_cor_barra())
        self._btn_cor = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
        self._btn_cor.set_rgba(rgba0)
        self._btn_cor.set_sensitive(bool(cor_cfg))
        controles_c.append(self._btn_cor)
        self._switch_cor.connect(
            "notify::active",
            lambda s, _p: self._btn_cor.set_sensitive(s.get_active()),
        )

        # ── Seção: Posição do menu ─────────────────────────────────────────────
        sep_sec = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep_sec.set_margin_top(4)
        sep_sec.set_margin_bottom(4)
        corpo.append(sep_sec)

        secao_pos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        corpo.append(secao_pos)

        sec_pos_titulo = Gtk.Label(label="POSIÇÃO DO MENU NA BARRA")
        sec_pos_titulo.add_css_class("pref-sec-titulo")
        sec_pos_titulo.set_halign(Gtk.Align.START)
        secao_pos.append(sec_pos_titulo)

        row_pos = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row_pos.set_valign(Gtk.Align.CENTER)
        secao_pos.append(row_pos)

        info_pos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_pos.set_hexpand(True)
        lbl_pos = Gtk.Label(label="Alinhamento do menu")
        lbl_pos.add_css_class("pref-lbl")
        lbl_pos.set_halign(Gtk.Align.START)
        info_pos.append(lbl_pos)
        sub_pos = Gtk.Label(label="Esquerda = estilo Windows 10  ·  Centro = estilo Windows 11")
        sub_pos.add_css_class("pref-sub")
        sub_pos.set_halign(Gtk.Align.START)
        sub_pos.set_wrap(True)
        info_pos.append(sub_pos)
        row_pos.append(info_pos)

        # Segmented toggle: Esquerda / Centro / Direita
        pos_atual = menu._config.get("menu_position", "left")
        self._btns_pos: dict[str, Gtk.ToggleButton] = {}
        seg = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        seg.add_css_class("pref-segmented")
        primeiro: Gtk.ToggleButton | None = None

        for val, icone, rotulo, css_extra in [
            ("left",   "go-first-symbolic",            "Esquerda", "pref-seg-left"),
            ("center", "format-justify-center-symbolic","Centro",   "pref-seg-mid"),
            ("right",  "go-last-symbolic",              "Direita",  "pref-seg-right"),
        ]:
            btn = Gtk.ToggleButton()
            btn.add_css_class("pref-seg-btn")
            btn.add_css_class(css_extra)
            conteudo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            conteudo.set_halign(Gtk.Align.CENTER)
            ic2 = Gtk.Image.new_from_icon_name(icone)
            ic2.set_pixel_size(14)
            conteudo.append(ic2)
            conteudo.append(Gtk.Label(label=rotulo))
            btn.set_child(conteudo)
            if primeiro is None:
                primeiro = btn
            else:
                btn.set_group(primeiro)
            btn.set_active(val == pos_atual)
            self._btns_pos[val] = btn
            seg.append(btn)

        row_pos.append(seg)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        raiz.append(sep2)

        # ── Botões ────────────────────────────────────────────────────────────
        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btns.set_margin_top(14)
        btns.set_margin_bottom(14)
        btns.set_margin_start(16)
        btns.set_margin_end(16)
        btns.set_halign(Gtk.Align.END)
        raiz.append(btns)

        btn_cancelar = Gtk.Button(label="Cancelar")
        btn_cancelar.add_css_class("pref-btn")
        btn_cancelar.connect("clicked", lambda _: self.close())
        btns.append(btn_cancelar)

        btn_aplicar = Gtk.Button(label="Aplicar")
        btn_aplicar.add_css_class("pref-btn")
        btn_aplicar.add_css_class("pref-btn-aplicar")
        btn_aplicar.connect("clicked", self._aplicar)
        btns.append(btn_aplicar)

        ctrl = Gtk.EventControllerKey()
        ctrl.connect("key-pressed", lambda _c, kv, _kc, _s: self.close() or True if kv == Gdk.KEY_Escape else False)
        self.add_controller(ctrl)

    def _aplicar(self, _btn) -> None:
        cfg = self._menu._config
        cfg["menu_position"] = next(
            (v for v, b in self._btns_pos.items() if b.get_active()), "center")
        cfg["menu_width"] = next(
            (v for v, b in self._btns_larg.items() if b.get_active()), _LARGURA_PADRAO)
        cfg["menu_color"] = (
            self._btn_cor.get_rgba().to_string() if self._switch_cor.get_active() else None)
        _salvar_config(cfg)
        # Aplica ao vivo: layout (layer-shell), largura e tema.
        self._menu._aplicar_config()
        self._menu._aplicar_largura()
        self._menu._aplicar_tema()
        self.close()


# ── Janela principal ──────────────────────────────────────────────────────────

class FireTaskBar(Gtk.ApplicationWindow):
    PREVIEW_FIX = 12   # quantos fixados antes de "Mostrar tudo"
    ANIM_FECHAR_MS = 200   # duração da animação de "voltar para a barra"
    TITULO_BASE    = "FireTaskBar"
    TITULO_FECHAR  = "FireTaskBar ·fechando"  # sinal p/ a extensão animar o fechamento

    def __init__(self, app_gtk: Gtk.Application) -> None:
        super().__init__(application=app_gtk, title="FireTaskBar")
        self.set_default_size(640, 730)
        self.set_resizable(False)
        self.add_css_class("menu-raiz")

        self._config = _carregar_config()

        # Em compositores wlroots: ancora via layer-shell. No GNOME/Mutter a
        # extensão posiciona a janela (Mutter não suporta wlr-layer-shell).
        self._usar_layer = _usar_layer_shell()
        if self._usar_layer:
            Gtk4LayerShell.init_for_window(self)
            Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.OVERLAY)
            Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.BOTTOM, True)
            Gtk4LayerShell.set_keyboard_mode(self, Gtk4LayerShell.KeyboardMode.ON_DEMAND)
            self._aplicar_config()
        else:
            self.set_decorated(False)  # janela limpa; posição vem da extensão

        self._todos    = _ler_apps()
        self._por_id   = {a["id"]: a for a in self._todos}

        # Semeia fixados padrão no primeiro uso
        if self._config.get("pinned") is None:
            self._config["pinned"] = self._semear_fixados()
            _salvar_config(self._config)

        self._cat_filtro   = "todos"
        self._fix_expandido = False
        self._busca_ativa   = False
        self._fechando      = False
        self._resultados: list[CardApp] = []   # cards na ordem do ranking (modo busca)
        self._sel_idx       = -1               # índice do resultado destacado

        self._construir_ui()
        self._aplicar_largura()
        self._repovoar_tudo()

        # Tema dinâmico: combina com a cor da barra de tarefas (lido do config
        # da extensão). Provider próprio, reaplicado a cada abertura para pegar
        # mudanças de cor sem reiniciar o daemon.
        self._prov_tema = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self._prov_tema,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self._aplicar_tema()

        # Esconde ao perder foco
        self.connect("notify::is-active", self._foco_mudou)

        ctrl = Gtk.EventControllerKey()
        ctrl.connect("key-pressed", self._tecla)
        self.add_controller(ctrl)

    # ── Posicionamento ──────────────────────────────────────────────────────────

    def _aplicar_config(self) -> None:
        if not getattr(self, "_usar_layer", False):
            return
        pos = self._config.get("menu_position", "left")
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.LEFT,  pos == "left")
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, pos == "right")
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.LEFT,   8 if pos == "left"  else 0)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.RIGHT,  8 if pos == "right" else 0)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.BOTTOM, self._config["bar_height"])

    def do_close_request(self) -> bool:
        self.set_visible(False)
        return True  # bloqueia destruição — só esconde

    def esconder(self) -> None:
        self._fechar_animado()

    def _fechar_animado(self) -> None:
        # Em wlroots a janela é ancorada por layer-shell; não há extensão para
        # animar o actor, então esconde direto.
        if getattr(self, "_usar_layer", False):
            self.set_visible(False)
            return
        if self._fechando or not self.is_visible():
            return
        self._fechando = True
        # Sinaliza à extensão (via título, canal que ela já observa) para
        # deslizar a janela de volta para dentro da barra. Só então escondemos.
        self.set_title(self.TITULO_FECHAR)
        GLib.timeout_add(self.ANIM_FECHAR_MS + 20, self._concluir_fechar)

    def _concluir_fechar(self) -> bool:
        self.set_visible(False)
        self.set_title(self.TITULO_BASE)
        self._fechando = False
        return GLib.SOURCE_REMOVE

    def _aplicar_tema(self) -> None:
        # menu_color (se definido) sobrepõe a cor herdada da barra de tarefas.
        cor = self._config.get("menu_color") or _ler_cor_barra()
        tema = _tema_do(cor)
        self._prov_tema.load_from_data(_construir_css(tema).encode())

    def _aplicar_largura(self) -> None:
        largura = _LARGURAS.get(self._config.get("menu_width", _LARGURA_PADRAO),
                                _LARGURAS[_LARGURA_PADRAO])
        # set_size_request no conteúdo redimensiona a janela viva (o
        # set_default_size só vale na 1ª realização). A extensão recentraliza
        # no próximo 'map'.
        if getattr(self, "_raiz", None) is not None:
            self._raiz.set_size_request(largura, -1)
        self.set_default_size(largura, 730)

    def mostrar(self) -> None:
        self._fechando = False
        self.set_title(self.TITULO_BASE)
        self._aplicar_tema()      # pega mudança de cor sem reiniciar o daemon
        self._aplicar_largura()   # idem para a largura
        self._busca.set_text("")
        self._repovoar_tudo()
        self.present()
        self._busca.grab_focus()

    def _foco_mudou(self, win, _param) -> None:
        # Pequeno delay para não fechar antes de registrar clique em app
        if not win.props.is_active:
            GLib.timeout_add(120, lambda: self._fechar_animado() if not win.props.is_active else None)

    # ── Fixados / Recentes (estado) ─────────────────────────────────────────────

    def _semear_fixados(self) -> list[str]:
        preferidos = [
            "firefox.desktop", "org.mozilla.firefox.desktop", "firefox-esr.desktop",
            "google-chrome.desktop", "chromium.desktop", "org.chromium.Chromium.desktop",
            "org.gnome.Nautilus.desktop", "nautilus.desktop",
            "org.gnome.Console.desktop", "org.gnome.Terminal.desktop",
            "org.gnome.TextEditor.desktop", "org.gnome.gedit.desktop", "gedit.desktop",
            "org.gnome.Calculator.desktop",
            "org.gnome.Settings.desktop", "gnome-control-center.desktop",
            "org.gnome.Software.desktop",
            "code.desktop", "code-oss.desktop", "com.visualstudio.code.desktop",
            "org.gnome.Calendar.desktop", "org.gnome.Loupe.desktop",
        ]
        pins = [p for p in preferidos if p in self._por_id]
        if not pins:
            pins = [a["id"] for a in self._todos[:8]]
        return pins[:self.PREVIEW_FIX]

    def esta_fixado(self, app_id: str) -> bool:
        return app_id in (self._config.get("pinned") or [])

    def alternar_fixado(self, app_id: str) -> None:
        pins = list(self._config.get("pinned") or [])
        if app_id in pins:
            pins.remove(app_id)
        else:
            pins.append(app_id)
        self._config["pinned"] = pins
        _salvar_config(self._config)
        self._popular_fixados()

    def registrar_recente(self, app_id: str) -> None:
        if not app_id:
            return
        rec = [r for r in self._config.get("recent", []) if r != app_id]
        rec.insert(0, app_id)
        self._config["recent"] = rec[:12]
        _salvar_config(self._config)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _construir_ui(self) -> None:
        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._raiz = raiz
        self.set_child(raiz)

        # ── Barra de busca (topo, estilo Windows 11) ────────────────────────────
        topo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        topo.set_margin_top(22)
        topo.set_margin_bottom(8)
        topo.set_margin_start(28)
        topo.set_margin_end(28)
        raiz.append(topo)

        self._busca = Gtk.SearchEntry()
        self._busca.set_hexpand(True)
        self._busca.set_placeholder_text("Pesquisar aplicativos, configurações e documentos")
        self._busca.add_css_class("campo-busca")
        self._busca.connect("search-changed", self._filtrar)
        self._busca.connect("activate", self._abrir_selecionado)
        topo.append(self._busca)

        # ── Conteúdo rolável ─────────────────────────────────────────────────────
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        # Altura mínima reservada — sem isto o Revealer mede natural ≈ 0 e a
        # grade de apps colapsa (some). Mantém o conteúdo sempre visível.
        scroll.set_min_content_height(500)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        raiz.append(scroll)
        self._scroll = scroll

        conteudo = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        conteudo.set_margin_top(12)
        conteudo.set_margin_bottom(18)
        conteudo.set_margin_start(28)
        conteudo.set_margin_end(28)
        scroll.set_child(conteudo)
        self._conteudo = conteudo

        # — Seção Fixados —
        self._box_fix = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        conteudo.append(self._box_fix)

        cab_fix, self._btn_fix_tudo = self._cabecalho_secao("Fixados")
        self._btn_fix_tudo.connect("clicked", self._alternar_fix_tudo)
        self._box_fix.append(cab_fix)

        self._grade_fix = self._nova_grade()
        self._box_fix.append(self._grade_fix)

        # — Seção Todos os aplicativos (visão por categorias, estilo Windows 11) —
        self._box_todos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        conteudo.append(self._box_todos)

        cab_todos = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._titulo_todos = Gtk.Label(label="Todos os aplicativos")
        self._titulo_todos.set_halign(Gtk.Align.START)
        self._titulo_todos.set_hexpand(True)
        self._titulo_todos.add_css_class("sec-titulo")
        cab_todos.append(self._titulo_todos)

        self._btn_voltar_cat = Gtk.Button(label="‹ Categorias")
        self._btn_voltar_cat.add_css_class("mostrar-tudo")
        self._btn_voltar_cat.set_visible(False)
        self._btn_voltar_cat.connect("clicked", self._voltar_categorias)
        cab_todos.append(self._btn_voltar_cat)
        self._box_todos.append(cab_todos)

        self._grade_todos = self._nova_grade()
        self._box_todos.append(self._grade_todos)

        # ── Barra inferior (perfil + energia) ────────────────────────────────────
        rodape = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        rodape.add_css_class("rodape")
        rodape.set_margin_start(20)
        rodape.set_margin_end(16)
        rodape.set_margin_top(8)
        rodape.set_margin_bottom(8)
        raiz.append(self._linha_topo_rodape())
        raiz.append(rodape)

        rodape.append(self._construir_perfil())

        espaco = Gtk.Box()
        espaco.set_hexpand(True)
        rodape.append(espaco)

        btn_pref = Gtk.Button()
        btn_pref.set_tooltip_text("Configurações do Menu")
        btn_pref.add_css_class("btn-rodape")
        ic_pref = Gtk.Image.new_from_icon_name("preferences-other-symbolic")
        ic_pref.set_pixel_size(18)
        btn_pref.set_child(ic_pref)
        btn_pref.connect("clicked", lambda _: self._abrir_preferencias())
        rodape.append(btn_pref)

        # Ações de sistema direto no rodapé (antes ficavam escondidas num
        # popover atrás do botão de energia). Cluster próprio à direita; só
        # "Desligar" recebe o realce vermelho (.btn-energia).
        acoes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        for icone, tip, cmd, perigo in [
            ("preferences-system-symbolic", "Configurações", ["gnome-control-center"], False),
            ("system-lock-screen-symbolic", "Bloquear", ["loginctl", "lock-session"], False),
            ("system-log-out-symbolic", "Sair",
             ["gnome-session-quit", "--logout", "--no-prompt"], False),
            ("system-reboot-symbolic", "Reiniciar", ["systemctl", "reboot"], False),
            ("system-shutdown-symbolic", "Desligar", ["systemctl", "poweroff"], True),
        ]:
            acoes.append(self._botao_energia(icone, tip, cmd, perigo))
        rodape.append(acoes)

    def _linha_topo_rodape(self) -> Gtk.Widget:
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.add_css_class("sep-rodape")
        return sep

    def _nova_grade(self) -> Gtk.FlowBox:
        grade = Gtk.FlowBox()
        grade.set_valign(Gtk.Align.START)
        # Centraliza o bloco de cards: sem isto, uma linha incompleta — como a
        # prévia (PREVIEW_FIX) costuma gerar — fica colada à esquerda e parece
        # "descentralizada" ao abrir o menu.
        grade.set_halign(Gtk.Align.CENTER)
        grade.set_max_children_per_line(6)
        grade.set_min_children_per_line(4)
        grade.set_selection_mode(Gtk.SelectionMode.NONE)
        grade.set_homogeneous(True)
        grade.set_row_spacing(4)
        grade.set_column_spacing(4)
        return grade

    def _cabecalho_secao(self, titulo: str) -> tuple[Gtk.Widget, Gtk.Button]:
        cab = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        lbl = Gtk.Label(label=titulo)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_hexpand(True)
        lbl.add_css_class("sec-titulo")
        cab.append(lbl)

        btn = Gtk.Button(label="Mostrar tudo  ›")
        btn.add_css_class("mostrar-tudo")
        cab.append(btn)
        return cab, btn

    def _botao_energia(self, icone: str, tooltip: str, cmd: list[str],
                       perigo: bool = False) -> Gtk.Button:
        btn = Gtk.Button()
        btn.set_tooltip_text(tooltip)
        btn.add_css_class("btn-rodape")
        if perigo:
            btn.add_css_class("btn-energia")
        ic = Gtk.Image.new_from_icon_name(icone)
        ic.set_pixel_size(18)
        btn.set_child(ic)
        btn.connect("clicked", lambda _b: self._acao_sistema(cmd))
        return btn

    def _acao_sistema(self, cmd: list[str]) -> None:
        # Esconde o menu antes: é superfície overlay (layer-shell) e janelas
        # como gnome-control-center abririam atrás dela.
        self.set_visible(False)
        try:
            subprocess.Popen(cmd)
        except Exception as e:
            print(f"Erro: {e}", file=sys.stderr)

    def _construir_perfil(self) -> Gtk.Widget:
        # Botão (não Box): clicar no avatar/nome abre a Conta de Usuário do
        # GNOME. Aparência de "linha" plana — sem moldura de botão (.perfil no
        # CSS já remove o realce padrão), mas com hover/foco reativos.
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_valign(Gtk.Align.CENTER)

        avatar_wrap = Gtk.Box()
        avatar_wrap.set_valign(Gtk.Align.CENTER)
        avatar_wrap.add_css_class("avatar-anel")

        foto = _caminho_avatar()
        if foto:
            avatar: Gtk.Widget = AvatarRedondo(foto, 32)
        else:
            avatar = Gtk.Image()
            avatar.set_pixel_size(30)
            avatar.set_from_icon_name("avatar-default-symbolic")
        avatar.add_css_class("avatar")
        avatar_wrap.append(avatar)
        box.append(avatar_wrap)

        try:
            info_u = pwd.getpwuid(os.getuid())
            nome   = info_u.pw_gecos.split(",")[0].strip() or info_u.pw_name
        except Exception:
            nome = os.environ.get("USER", "Usuário")

        nome_lbl = Gtk.Label(label=nome)
        nome_lbl.add_css_class("nome-usuario")
        nome_lbl.set_halign(Gtk.Align.START)
        box.append(nome_lbl)

        btn = Gtk.Button()
        btn.add_css_class("perfil")
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_tooltip_text("Conta de usuário")
        btn.set_child(box)
        btn.connect("clicked", lambda _: self._abrir_conta_usuario())
        return btn

    def _abrir_preferencias(self) -> None:
        """Abre o diálogo de Configurações do Menu.

        Esconde o menu primeiro (superfície layer-shell overlay que se
        auto-fecha ao perder foco — manter ambos visíveis causaria conflito de
        z-order e uma corrida com o handler de foco). Guarda referência ao
        diálogo: sem isso o PyGObject poderia coletá-lo assim que o lambda
        retornasse.
        """
        self.set_visible(False)
        self._dlg_pref = DialogPreferencias(self)
        self._dlg_pref.connect("close-request", self._ao_fechar_preferencias)
        self._dlg_pref.present()

    def _ao_fechar_preferencias(self, _win) -> bool:
        self._dlg_pref = None
        return False  # deixa a janela fechar normalmente

    def _abrir_conta_usuario(self) -> None:
        """Abre o painel de Conta de Usuário das Configurações do GNOME.

        Fecha o menu primeiro (singleton em layer-shell sobre tudo), senão a
        janela das Configurações abriria atrás da barra/menu.
        """
        self.set_visible(False)
        # GNOME 46+ fundiu "Usuários" no painel System → subpágina "users".
        try:
            GLib.spawn_async(
                argv=["gnome-control-center", "system", "users"],
                flags=GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.STDOUT_TO_DEV_NULL
                | GLib.SpawnFlags.STDERR_TO_DEV_NULL,
            )
        except GLib.Error:
            # Fallback: abre as Configurações na tela inicial.
            try:
                GLib.spawn_async(
                    argv=["gnome-control-center"],
                    flags=GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.STDOUT_TO_DEV_NULL
                    | GLib.SpawnFlags.STDERR_TO_DEV_NULL,
                )
            except GLib.Error:
                pass

    # ── Filtrar / popular ───────────────────────────────────────────────────────

    def _apps_de_ids(self, ids: list[str]) -> list[dict]:
        return [self._por_id[i] for i in ids if i in self._por_id]

    @staticmethod
    def _limpar(grade: Gtk.FlowBox) -> None:
        while (c := grade.get_first_child()) is not None:
            grade.remove(c)

    def _popular_fixados(self) -> None:
        self._limpar(self._grade_fix)
        apps = self._apps_de_ids(self._config.get("pinned") or [])
        mostrar = apps if self._fix_expandido else apps[:self.PREVIEW_FIX]
        for app in mostrar:
            self._grade_fix.append(CardApp(app, self))
        # botão "Mostrar tudo" só faz sentido se há excedente
        tem_mais = len(apps) > self.PREVIEW_FIX
        self._btn_fix_tudo.set_visible(tem_mais)
        self._btn_fix_tudo.set_label("Mostrar menos  ‹" if self._fix_expandido else "Mostrar tudo  ›")
        self._box_fix.set_visible(bool(apps))

    def _popular_todos(self) -> None:
        self._limpar(self._grade_todos)
        self._resultados = []
        self._sel_idx = -1

        # Modo busca: resultados achatados (um card por app), ordenados por
        # relevância — o melhor palpite vem primeiro e já fica destacado, então
        # Enter abre direto (efeito de "autocomplete").
        if self._busca_ativa:
            texto = self._busca.get_text().lower().strip()
            ranqueados = sorted(
                ((p, a) for a in self._todos
                 if (p := _pontuar_busca(a, texto)) is not None),
                key=lambda pa: (pa[0], pa[1]["nome"].lower()),
            )
            self._resultados = []
            for _p, app in ranqueados:
                card = CardApp(app, self)
                self._grade_todos.append(card)
                self._resultados.append(card)
            self._sel_idx = 0 if self._resultados else -1
            self._destacar(self._sel_idx)
            return

        # Visão por categorias (overview): um card por categoria com apps.
        if self._cat_filtro == "todos":
            for chave, label, _ in CATS[1:]:
                apps_cat = [a for a in self._todos if a["categoria"] == chave]
                if apps_cat:
                    self._grade_todos.append(CardCategoria(chave, label, apps_cat, self))
            return

        # Dentro de uma categoria: os apps dela como cards.
        for app in (a for a in self._todos if a["categoria"] == self._cat_filtro):
            self._grade_todos.append(CardApp(app, self))

    def _repovoar_tudo(self) -> None:
        self._popular_fixados()
        self._popular_todos()

    def _alternar_fix_tudo(self, _b) -> None:
        self._fix_expandido = not self._fix_expandido
        self._popular_fixados()

    def _abrir_categoria(self, chave: str) -> None:
        self._cat_filtro = chave
        self._titulo_todos.set_text(CAT_LABELS.get(chave, "Todos os aplicativos"))
        self._btn_voltar_cat.set_visible(True)
        self._popular_todos()

    def _voltar_categorias(self, _b=None) -> None:
        self._cat_filtro = "todos"
        self._titulo_todos.set_text("Todos os aplicativos")
        self._btn_voltar_cat.set_visible(False)
        self._popular_todos()

    def _filtrar(self, _entry: Gtk.SearchEntry) -> None:
        texto = self._busca.get_text().strip()
        ativa = bool(texto)
        self._busca_ativa = ativa

        # No modo busca, só a grade "Todos" aparece e vira "Melhor correspondência".
        self._box_fix.set_visible(not ativa and bool(self._config.get("pinned")))
        self._btn_voltar_cat.set_visible(not ativa and self._cat_filtro != "todos")

        if ativa:
            self._titulo_todos.set_text("Melhor correspondência")
            self._popular_todos()
        else:
            self._titulo_todos.set_text(
                "Todos os aplicativos" if self._cat_filtro == "todos"
                else CAT_LABELS.get(self._cat_filtro, "Todos os aplicativos"))
            self._repovoar_tudo()

    def _tecla(self, _ctrl, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.esconder()
            return True
        # Setas ↓/↑ percorrem os resultados da busca sem tirar o foco do campo
        # (o campo de texto não usa ↓/↑, então o evento chega até aqui).
        if self._resultados:
            if keyval in (Gdk.KEY_Down, Gdk.KEY_Right):
                self._mover_selecao(+1)
                return True
            if keyval in (Gdk.KEY_Up, Gdk.KEY_Left):
                self._mover_selecao(-1)
                return True
        return False

    # ── Seleção / "autocomplete" na busca ────────────────────────────────────────

    def _destacar(self, idx: int) -> None:
        for i, card in enumerate(self._resultados):
            card.set_selecionado(i == idx)
        if 0 <= idx < len(self._resultados):
            self._scroll_para(self._resultados[idx])

    def _mover_selecao(self, passo: int) -> None:
        if not self._resultados:
            return
        self._sel_idx = (self._sel_idx + passo) % len(self._resultados)
        self._destacar(self._sel_idx)

    def _scroll_para(self, widget: Gtk.Widget) -> None:
        ok, rect = widget.compute_bounds(self._conteudo)
        if not ok:
            return
        adj = self._scroll.get_vadjustment()
        topo, base = rect.get_y(), rect.get_y() + rect.get_height()
        if topo < adj.get_value():
            adj.set_value(topo)
        elif base > adj.get_value() + adj.get_page_size():
            adj.set_value(base - adj.get_page_size())

    def _abrir_selecionado(self, _entry=None) -> None:
        if 0 <= self._sel_idx < len(self._resultados):
            self._resultados[self._sel_idx]._abrir(None)


# ── CSS (tema dinâmico — combina com a cor da barra de tarefas) ─────────────────

def _construir_css(t: dict) -> str:
    return f"""
.menu-raiz {{
    background-color: {t['bg']};
    border-radius: 12px;
    border: 1px solid {t['borda']};
    box-shadow: {t['sombra']};
    color: {t['txt']};
}}

/* ── Busca ── */
.campo-busca {{
    font-size: 14px;
    border-radius: 20px;
    padding: 9px 14px;
    min-height: 22px;
    background-color: {t['elevado']};
    color: {t['txt']};
    border: 1px solid {t['borda_in']};
    caret-color: {t['accent']};
    box-shadow: none;
}}
.campo-busca:focus {{
    border-color: {t['accent']};
    box-shadow: 0 0 0 3px {t['anel_foco']};
}}
.campo-busca image {{ color: {t['txt_sec']}; }}
.campo-busca text {{ color: {t['txt']}; }}

/* ── Títulos de seção + "Mostrar tudo" ── */
.sec-titulo {{
    font-size: 13px;
    font-weight: 600;
    color: {t['txt']};
}}
.mostrar-tudo {{
    background: none;
    border: none;
    box-shadow: none;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 12px;
    font-weight: 500;
    color: {t['txt_sec']};
    transition: background 90ms ease-out, color 90ms ease-out;
}}
.mostrar-tudo:hover {{
    background-color: {t['hover']};
    color: {t['txt']};
}}
/* ── Cards de app (Fixados / Todos) ── */
.card-app {{
    background: none;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 10px 4px;
    min-width: 88px;
    min-height: 88px;
    box-shadow: none;
    transition: background 90ms ease-out, border-color 90ms ease-out;
}}
.card-app:hover {{
    background-color: {t['hover']};
    border-color: {t['borda']};
    box-shadow: 0 4px 14px rgba(0,0,0,0.22);
}}
.card-app:active {{
    background-color: {t['ativo']};
    box-shadow: 0 1px 4px rgba(0,0,0,0.18);
}}
/* Resultado destacado na busca (melhor correspondência / navegação por setas) */
.card-app-sel {{
    background-color: {t['ativo']};
    border-color: {t['accent']};
    box-shadow: 0 0 0 2px {t['anel_foco']};
}}
.app-label {{
    font-size: 12px;
    color: {t['txt']};
}}

/* ── Cards de categoria (visão "Todos", estilo Windows 11) ── */
.card-cat {{
    background: none;
    border: 1px solid transparent;
    border-radius: 12px;
    padding: 12px 10px 10px 10px;
    min-width: 124px;
    box-shadow: none;
    transition: background 90ms ease-out, border-color 90ms ease-out;
}}
.card-cat:hover {{
    background-color: {t['hover']};
    border-color: {t['borda']};
    box-shadow: 0 4px 14px rgba(0,0,0,0.22);
}}
.card-cat:active {{ background-color: {t['ativo']}; }}
.card-cat-tile {{
    background-color: {t['elevado']};
    border: 1px solid {t['borda_in']};
    border-radius: 10px;
    padding: 12px;
}}
.card-cat-label {{
    font-size: 12px;
    font-weight: 500;
    color: {t['txt']};
}}

/* ── Rodapé ── */
.sep-rodape {{ background-color: {t['borda']}; }}
.rodape {{
    background-color: transparent;
    border-radius: 0 0 12px 12px;
    min-height: 48px;
}}
.avatar-anel {{
    border-radius: 50%;
    padding: 2px;
    background-color: {t['hover']};
}}
.avatar {{ border-radius: 50%; }}
.perfil {{
    background: none;
    border: none;
    box-shadow: none;
    border-radius: 10px;
    padding: 4px 8px 4px 4px;
    min-height: 0;
    transition: background 90ms ease-out;
}}
.perfil:hover {{
    background-color: {t['hover']};
}}
.nome-usuario {{
    font-size: 13px;
    font-weight: 600;
    color: {t['txt']};
}}
.btn-rodape {{
    background: none;
    border: none;
    border-radius: 8px;
    padding: 7px;
    min-height: 0;
    box-shadow: none;
    color: {t['txt_sec']};
    transition: background 90ms ease-out, color 90ms ease-out;
}}
.btn-rodape:hover {{
    background-color: {t['hover']};
    color: {t['txt']};
}}
.btn-energia:hover {{
    background-color: {t['perigo']};
    color: {t['perigo_txt']};
}}

/* ── Popovers (categoria, energia, contexto) ── */
.pop-cat contents, .pop-energia contents, .menu-contexto contents {{
    background-color: {t['pop_bg']};
    border: 1px solid {t['borda_in']};
    border-radius: 10px;
    padding: 4px;
    box-shadow: {t['sombra_pop']};
    color: {t['txt']};
}}
.ctx-item, .linha-energia {{
    background: none;
    border: none;
    box-shadow: none;
    border-radius: 7px;
    padding: 8px 12px;
    font-size: 13px;
    color: {t['txt']};
    transition: background 80ms ease-out;
}}
.ctx-item:hover, .linha-energia:hover {{
    background-color: {t['hover']};
}}

/* ── Diálogo de preferências ── */
.pref-janela {{
    background-color: {t['bg']};
    border-radius: 14px;
    border: 1px solid {t['borda']};
    box-shadow: {t['sombra']};
    color: {t['txt']};
}}
.pref-header {{
    padding: 18px 20px 14px 20px;
    background-color: {t['elevado']};
    border-radius: 14px 14px 0 0;
}}
.pref-header-ic {{ color: {t['accent']}; }}
.pref-titulo {{
    font-size: 15px;
    font-weight: 600;
    color: {t['txt']};
}}
.pref-sec-titulo {{
    font-size: 10px;
    font-weight: 700;
    color: {t['txt_mut']};
    letter-spacing: 0.08em;
}}
.pref-lbl {{
    font-size: 13px;
    font-weight: 500;
    color: {t['txt']};
}}
.pref-sub {{
    font-size: 11px;
    color: {t['txt_sec']};
}}
.pref-spin {{
    font-size: 15px;
    font-weight: 600;
    color: {t['txt']};
    background-color: {t['elevado']};
    border: 1px solid {t['borda_in']};
    border-radius: 8px;
    padding: 4px 6px;
    caret-color: {t['accent']};
}}
.pref-spin:focus {{ border-color: {t['accent']}; }}
.pref-unidade {{
    font-size: 12px;
    color: {t['txt_sec']};
}}
.pref-scale trough {{
    background-color: {t['borda_in']};
    border-radius: 4px;
    min-height: 4px;
    min-width: 0;
}}
.pref-scale highlight {{
    background-color: {t['accent']};
    border-radius: 4px;
    min-width: 0;
    min-height: 0;
}}
.pref-scale slider {{
    background-color: {t['accent']};
    border-radius: 50%;
    min-width: 16px;
    min-height: 16px;
    margin: -6px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.35);
}}
.pref-btn {{
    background-color: {t['elevado']};
    border: 1px solid {t['borda_in']};
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: 500;
    color: {t['txt']};
    box-shadow: none;
    transition: background 100ms ease-out;
}}
.pref-btn:hover {{ background-color: {t['hover']}; }}
.pref-btn-aplicar {{
    background-color: {t['accent']};
    border-color: {t['accent']};
    color: {t['accent_txt']};
    font-weight: 600;
}}
.pref-btn-aplicar:hover {{ background-color: {t['accent_h']}; }}

/* Segmented control de posição */
.pref-segmented {{
    background-color: {t['elevado']};
    border: 1px solid {t['borda']};
    border-radius: 8px;
    padding: 2px;
}}
.pref-seg-btn {{
    background: none;
    border: none;
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
    color: {t['txt_sec']};
    box-shadow: none;
    transition: background 80ms ease-out, color 80ms ease-out;
    min-width: 88px;
}}
.pref-seg-btn:hover {{ background-color: {t['hover']}; color: {t['txt']}; }}
.pref-seg-btn:checked {{
    background-color: {t['accent']};
    color: {t['accent_txt']};
    font-weight: 600;
    box-shadow: 0 1px 4px rgba(0,0,0,0.3);
}}
"""


# ── Aplicação singleton (daemon) ──────────────────────────────────────────────

class Aplicacao(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id="br.dev.firetaskbar",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._janela:  FireTaskBar | None = None
        self._daemon:  bool           = False

        self.add_main_option(
            "daemon", ord("d"),
            GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Iniciar em segundo plano (sem mostrar janela)", None,
        )

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        self.hold()  # mantém vivo sem janelas abertas

    def do_command_line(self, cmd_line: Gio.ApplicationCommandLine) -> int:
        opts = cmd_line.get_options_dict()
        self._daemon = opts.contains("daemon")
        self.activate()
        return 0

    def do_activate(self) -> None:
        if self._janela is None:
            self._janela = FireTaskBar(self)

        if self._daemon:
            # Primeira vez em modo daemon: só cria a janela, não mostra
            self._daemon = False
            return

        # Chamadas seguintes: alterna visibilidade
        if self._janela.is_visible():
            self._janela.esconder()
        else:
            self._janela.mostrar()


if __name__ == "__main__":
    app = Aplicacao()
    sys.exit(app.run(sys.argv))
