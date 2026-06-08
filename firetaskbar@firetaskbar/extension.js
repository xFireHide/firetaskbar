import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Mtk from 'gi://Mtk';
import Shell from 'gi://Shell';
import St from 'gi://St';

import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const MENU_CMD    = 'python3 /home/y/firetaskbar/firetaskbar.py';
const DAEMON_CMD  = 'python3 /home/y/firetaskbar/firetaskbar.py --daemon';
const CONFIG_PATH = GLib.get_home_dir() + '/.config/firetaskbar.json';
// Config do PRÓPRIO menu (GTK): a posição esquerda/centro/direita escolhida no
// diálogo "Configurações do Menu" vive aqui. Lemos a cada posicionamento (só
// ocorre ao abrir o menu), então mudanças valem na próxima abertura.
const MENU_CONFIG_PATH = GLib.get_home_dir() + '/.config/firetaskbar/config.json';
const MENU_EDGE_MARGIN = 8;   // folga lateral quando ancorado à esquerda/direita

function loadMenuPosition() {
    try {
        const [ok, bytes] = GLib.file_get_contents(MENU_CONFIG_PATH);
        if (ok) {
            const cfg = JSON.parse(new TextDecoder().decode(bytes));
            const p = cfg.menu_position;
            if (p === 'left' || p === 'right' || p === 'center') return p;
        }
    } catch (_) {}
    return 'center';
}

const SIZES = { pequena: 40, normal: 48, grande: 56, enorme: 64 };
const SIZE_LABELS = {
    pequena: 'Pequena  (40 px)',
    normal:  'Normal   (48 px)',
    grande:  'Grande   (56 px)',
    enorme:  'Enorme   (64 px)',
};
const DEFAULT_SIZE = 'normal';

const MODES = { icons: 'Somente ícones', icons_names: 'Ícone + nome' };
const DEFAULT_MODE = 'icons';

const LAYOUTS = { full: 'Largura total', dock: 'Dock  (estilo macOS)' };
const DEFAULT_LAYOUT = 'full';

const DOCK_GAP    = 8;
const DOCK_MARGIN = 24;
const MENU_OVERLAP = 4;   // px que o menu Iniciar sobrepõe a barra (cola nela)

function loadConfig() {
    try {
        const [ok, bytes] = GLib.file_get_contents(CONFIG_PATH);
        if (ok) {
            const cfg = JSON.parse(new TextDecoder().decode(bytes));
            if (!Array.isArray(cfg.pinnedApps)) cfg.pinnedApps = [];
            return cfg;
        }
    } catch (_) {}
    return { size: DEFAULT_SIZE, mode: DEFAULT_MODE, layout: DEFAULT_LAYOUT, pinnedApps: [] };
}

function saveConfig(cfg) {
    try {
        GLib.file_set_contents(CONFIG_PATH, JSON.stringify(cfg));
    } catch (_) {}
}

// ── Tooltip flutuante ──────────────────────────────────────────────────────

class Tooltip extends St.BoxLayout {
    static { GObject.registerClass(this); }

    constructor() {
        super({ style_class: 'meu-tooltip', visible: false });
        this._label = new St.Label({ y_align: Clutter.ActorAlign.CENTER });
        this.add_child(this._label);
        Main.uiGroup.add_child(this);
    }

    showFor(text, actor) {
        if (!text) return;
        this._label.text = text;
        this.visible = true;
        this.ensure_style();

        const [ax, ay] = actor.get_transformed_position();
        const tw = this.width  || 80;
        const th = this.height || 24;
        const x  = Math.round(ax + actor.width / 2 - tw / 2);
        const y  = Math.round(ay - th - 8);
        this.set_position(Math.max(4, x), Math.max(4, y));

        this.opacity = 0;
        this.ease({ opacity: 255, duration: 130, mode: Clutter.AnimationMode.EASE_OUT_QUAD });
    }

    hideNow() { this.visible = false; }

    destroy() {
        Main.uiGroup.remove_child(this);
        super.destroy();
    }
}

// ── Prévia de janelas (miniaturas ao passar o mouse, estilo Windows) ────────

const PREVIEW_THUMB_W = 200;
const PREVIEW_THUMB_H = 124;

class WindowPreview extends St.BoxLayout {
    static { GObject.registerClass(this); }

    constructor(monitor) {
        super({
            style_class: 'meu-preview',
            reactive: true,
            track_hover: true,
            visible: false,
            vertical: false,
        });
        this._monitor = monitor;
        this._showId  = 0;
        this._hideId  = 0;
        Main.uiGroup.add_child(this);

        // Manter aberta enquanto o mouse estiver sobre a própria prévia.
        this.connect('notify::hover', () => {
            if (this.hover) this._cancelHide();
            else this.scheduleHide();
        });
    }

    setMonitor(m) { this._monitor = m; }

    _cancelShow() { if (this._showId) { GLib.source_remove(this._showId); this._showId = 0; } }
    _cancelHide() { if (this._hideId) { GLib.source_remove(this._hideId); this._hideId = 0; } }

    // Agenda exibição com pequeno atraso (evita flicker ao passar rápido).
    showFor(button) {
        this._cancelHide();
        this._cancelShow();
        const delay = this.visible ? 0 : 300;
        this._showId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, delay, () => {
            this._showId = 0;
            this._present(button);
            return GLib.SOURCE_REMOVE;
        });
    }

    _present(button) {
        const wins = button.wins;
        if (!wins || wins.length === 0) return;

        this.remove_all_children();
        for (const win of wins) this.add_child(this._makeCard(win, button));

        this.visible = true;
        this.ensure_style();

        // Centralizada acima do botão, logo acima da barra.
        const [bx, by] = button.get_transformed_position();
        const pw = this.width  || (wins.length * (PREVIEW_THUMB_W + 16));
        const ph = this.height || (PREVIEW_THUMB_H + 48);
        const mon = this._monitor || { x: 0, width: global.stage.width };
        let x = Math.round(bx + button.width / 2 - pw / 2);
        x = Math.max(mon.x + 6, Math.min(x, mon.x + mon.width - pw - 6));
        const y = Math.round(by - ph - 10);
        this.set_position(x, Math.max(6, y));

        this.opacity = 0;
        this.translation_y = 8;
        this.ease({
            opacity: 255,
            translation_y: 0,
            duration: 150,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    _makeCard(win, button) {
        const card = new St.Widget({
            style_class: 'meu-preview-card',
            layout_manager: new Clutter.BinLayout(),
            reactive: true,
            track_hover: true,
        });

        const vbox = new St.BoxLayout({ vertical: true });
        card.add_child(vbox);

        const title = new St.Label({
            style_class: 'meu-preview-title',
            text: (win.get_title && win.get_title()) || button._appName(),
        });
        title.clutter_text.ellipsize = 3;
        vbox.add_child(title);

        const thumbBox = new St.Widget({
            style_class: 'meu-preview-thumb',
            layout_manager: new Clutter.BinLayout(),
            width:  PREVIEW_THUMB_W,
            height: PREVIEW_THUMB_H,
        });
        vbox.add_child(thumbBox);

        const actor = win.get_compositor_private && win.get_compositor_private();
        if (actor && !win.minimized) {
            const [aw, ah] = actor.get_size();
            const scale = Math.min(PREVIEW_THUMB_W / aw, PREVIEW_THUMB_H / ah, 1) || 1;
            const clone = new Clutter.Clone({
                source:  actor,
                width:   Math.max(1, Math.round(aw * scale)),
                height:  Math.max(1, Math.round(ah * scale)),
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
            });
            thumbBox.add_child(clone);
        } else {
            // Minimizada / sem ator: cai pro ícone do app.
            thumbBox.add_child(new St.Icon({
                gicon:   button._icon.gicon,
                icon_size: 56,
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
            }));
        }

        // Botão fechar (canto superior direito, estilo Windows).
        const closeBtn = new St.Button({
            style_class: 'meu-preview-close',
            child:   new St.Icon({ icon_name: 'window-close-symbolic', icon_size: 14 }),
            // x_expand/y_expand: true é o que faz o BinLayout dar ao botão a área
            // toda do card; só então x_align/y_align valem e ele encosta no canto
            // superior direito. Sem expand, o BinLayout centraliza o botão (caía
            // por cima do ícone).
            x_expand: true,
            y_expand: true,
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.START,
        });
        closeBtn.connect('clicked', () => {
            win.delete(global.get_current_time());
            card.destroy();
            if (this.visible && this.get_n_children() === 0) this.hideNow();
            return Clutter.EVENT_STOP;
        });
        card.add_child(closeBtn);

        // Clique no card → ativa a janela.
        card.connect('button-press-event', (_a, ev) => {
            if (ev.get_button() === 1) {
                if (win.minimized) win.unminimize();
                Main.activateWindow(win);
                this.hideNow();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        // Se a janela fechar por fora, remove o card (evita clone órfão).
        const unmanagedId = win.connect('unmanaged', () => {
            if (!card.get_parent()) return;
            card.destroy();
            if (this.visible && this.get_n_children() === 0) this.hideNow();
        });
        card.connect('destroy', () => { try { win.disconnect(unmanagedId); } catch (_) {} });

        return card;
    }

    scheduleHide() {
        this._cancelShow();
        this._cancelHide();
        this._hideId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 180, () => {
            this._hideId = 0;
            this.hideNow();
            return GLib.SOURCE_REMOVE;
        });
    }

    hideNow() {
        this._cancelShow();
        this._cancelHide();
        if (!this.visible) return;
        this.remove_all_children();
        this.visible = false;
    }

    destroy() {
        this._cancelShow();
        this._cancelHide();
        Main.uiGroup.remove_child(this);
        super.destroy();
    }
}

// ── Menu de contexto do grupo de app ───────────────────────────────────────
// Para 1 janela: minimizar/maximizar/fixar/fechar (como antes).
// Para N janelas do mesmo app: lista cada janela + fixar + "Fechar tudo".

class GroupMenu extends PopupMenu.PopupMenu {
    constructor(source, btn, isPinned, onTogglePin) {
        super(source, 0.5, St.Side.BOTTOM);
        const wins = btn.wins;

        if (wins.length === 1) {
            const win = wins[0];
            this._minItem = new PopupMenu.PopupMenuItem('');
            this._minItem.connect('activate', () => {
                win.minimized ? win.unminimize() : win.minimize();
            });
            this.addMenuItem(this._minItem);

            this._maxItem = new PopupMenu.PopupMenuItem('');
            this._maxItem.connect('activate', () => {
                win.is_maximized() ? win.unmaximize() : win.maximize();
            });
            this.addMenuItem(this._maxItem);

            this.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

            this.connect('open-state-changed', (_m, open) => {
                if (!open) return;
                this._minItem.label.text = win.minimized ? 'Restaurar' : 'Minimizar';
                this._maxItem.label.text = win.is_maximized() ? 'Restaurar tamanho' : 'Maximizar';
                this._minItem.setSensitive(win.can_minimize());
                this._maxItem.setSensitive(win.can_maximize());
            });
        } else {
            this.addMenuItem(new PopupMenu.PopupSeparatorMenuItem(btn._appName()));
            for (const win of wins) {
                const raw = win.get_title() || btn._appName();
                const title = raw.length > 42 ? raw.slice(0, 41) + '…' : raw;
                const it = new PopupMenu.PopupMenuItem(title);
                it.connect('activate', () => {
                    if (win.minimized) win.unminimize();
                    Main.activateWindow(win);
                });
                this.addMenuItem(it);
            }
            this.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        }

        this._pinItem = new PopupMenu.PopupMenuItem(
            isPinned ? 'Desafixar da barra' : 'Fixar na barra');
        this._pinItem.connect('activate', () => onTogglePin && onTogglePin());
        if (!onTogglePin) this._pinItem.setSensitive(false);
        this.addMenuItem(this._pinItem);

        this.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const closeItem = new PopupMenu.PopupMenuItem(
            wins.length > 1 ? 'Fechar tudo' : 'Fechar');
        closeItem.connect('activate', () => {
            for (const win of wins) win.delete(global.get_current_time());
        });
        this.addMenuItem(closeItem);
    }
}

// ── Botão de grupo de app (agrupa todas as janelas do mesmo programa) ───────

class GroupButton extends St.Button {
    static { GObject.registerClass(this); }

    constructor(app, wins, tracker, tooltip, preview, iconSize, mode, isPinned, onTogglePin) {
        super({
            style_class: 'meu-win-btn',
            reactive: true,
            can_focus: false,   // sem foco de teclado → sem anel azul no clique
            track_hover: true,
            // Nunca expandir horizontalmente: a largura é só o conteúdo (ícone).
            // Sem isso, um app com muitas janelas (ex.: Brave) "puxava" o espaço
            // livre da lista e o botão esticava bem mais que os outros.
            x_expand: false,
        });

        this._app     = app;
        this._wins    = wins.slice();
        this._tracker = tracker;
        this._tooltip = tooltip;
        this._preview = preview;
        this._mode    = mode || DEFAULT_MODE;

        const container = new St.Widget({
            x_expand: false,
            y_expand: true,
            layout_manager: new Clutter.BinLayout(),
        });
        this.set_child(container);

        this._inner = new St.BoxLayout({
            vertical: false,
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'meu-win-inner',
        });
        container.add_child(this._inner);

        this._icon = new St.Icon({
            icon_size: iconSize,
            style_class: 'meu-win-icon',
        });
        this._inner.add_child(this._icon);

        this._label = new St.Label({
            style_class: 'meu-win-label',
            y_align: Clutter.ActorAlign.CENTER,
            visible: false,
        });
        this._label.clutter_text.ellipsize = 3;
        this._inner.add_child(this._label);

        this._indicator = new St.Widget({
            style_class: 'meu-indicator',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.END,
        });
        container.add_child(this._indicator);

        // Badge de contagem — só aparece com 2+ janelas agrupadas.
        // Fica no canto inferior-direito, fora do corpo do ícone.
        this._count = new St.Label({
            style_class: 'meu-count',
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.END,
            visible: false,
        });
        container.add_child(this._count);

        this._menuMgr = new PopupMenu.PopupMenuManager(this);
        this._menu    = new GroupMenu(this, this, !!isPinned, onTogglePin);
        Main.uiGroup.add_child(this._menu.actor);
        this._menu.actor.hide();
        this._menuMgr.addMenu(this._menu);

        this.connect('notify::hover', () => {
            if (this.hover) this._preview.showFor(this);
            else this._preview.scheduleHide();
        });

        this.connect('button-press-event', (_a, ev) => {
            if (ev.get_button() === 3) {
                this._preview.hideNow();
                this._menu.toggle();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
        this.connect('clicked', () => this._activate());

        // Faz a animação de minimizar "voar" até este botão (e não pra cima):
        // o Mutter usa o icon-geometry de cada janela como alvo. Reaplica sempre
        // que o botão é (re)alocado, pois a posição na tela muda com a barra.
        this.connect('notify::allocation', () => this._updateIconGeometry());

        for (const win of this._wins) {
            win.connectObject(
                'notify::title',           () => this._syncLabel(),
                'notify::minimized',       () => this._syncStyle(),
                'notify::appears-focused', () => this._syncStyle(),
                this);
        }

        if (this._wins.length > 1) {
            this.add_style_class_name('grouped');
            this._count.text = String(this._wins.length);
            this._count.visible = true;
        }

        this._syncIcon();
        this._syncLabel();
        this._syncStyle();
        this.setMode(this._mode);
        if (isPinned) this.add_style_class_name('pinned');
    }

    get wins() { return this._wins; }

    _appName() {
        if (this._app) return this._app.get_name();
        const w = this._wins[0];
        return (w && (w.get_wm_class?.() || w.get_title?.())) || '';
    }

    _tooltipText() {
        const name = this._appName();
        if (this._wins.length > 1) return `${name}  (${this._wins.length})`;
        return (this._wins[0] && this._wins[0].get_title()) || name;
    }

    setMode(mode) {
        this._mode = mode;
        const withLabel = mode === 'icons_names';
        this._label.visible = withLabel;
        if (withLabel) {
            this.add_style_class_name('with-label');
            this._tooltip.hideNow();
        } else {
            this.remove_style_class_name('with-label');
        }
        this._syncLabel();
    }

    // Janela usada mais recentemente do grupo (maior user_time).
    _mru() {
        const sorted = this._wins.slice()
            .sort((a, b) => b.get_user_time() - a.get_user_time());
        return sorted[0] || this._wins[0];
    }

    _activate() {
        const wins = this._wins;
        if (wins.length === 1) {
            this._preview.hideNow();
            const w = wins[0];
            if (w.minimized) { w.unminimize(); Main.activateWindow(w); }
            else if (w.appears_focused) { w.minimize(); }
            else Main.activateWindow(w);
            return;
        }
        // Grupo (várias janelas): clicar no ícone não cicla nem ativa nada.
        // O usuário deve clicar na prévia para escolher a janela.
        this._preview.showFor(this);
    }

    _syncIcon() {
        if (this._app) {
            this._icon.gicon = this._app.get_icon();
            return;
        }
        const app = this._tracker.get_window_app(this._wins[0]);
        this._icon.gicon = app ? app.get_icon() : null;
        if (!app) this._icon.icon_name = 'application-x-executable';
    }

    _syncLabel() {
        if (!this._label.visible) return;
        const name = this._appName();
        this._label.text = this._wins.length > 1
            ? `${name} (${this._wins.length})` : name;
    }

    // Aponta o icon-geometry de todas as janelas do grupo para o retângulo
    // deste botão na tela. Assim minimizar/restaurar anima na direção da barra.
    _updateIconGeometry() {
        if (!this.mapped) return;
        const [x, y] = this.get_transformed_position();
        const [w, h] = this.get_transformed_size();
        if (!(w > 0 && h > 0) || Number.isNaN(x) || Number.isNaN(y)) return;
        const rect = new Mtk.Rectangle({
            x: Math.round(x), y: Math.round(y),
            width: Math.round(w), height: Math.round(h),
        });
        for (const win of this._wins) {
            try { win.set_icon_geometry(rect); } catch (_) {}
        }
    }

    _syncStyle() {
        this.remove_style_class_name('focused');
        this.remove_style_class_name('minimized');
        if (this._wins.some(w => w.appears_focused))
            this.add_style_class_name('focused');
        else if (this._wins.every(w => w.minimized))
            this.add_style_class_name('minimized');
    }

    destroy() {
        for (const win of this._wins) {
            try { win.disconnectObject(this); } catch (_) {}
        }
        this._menu.destroy();
        super.destroy();
    }
}

// ── Botão de app fixado (sem janela aberta) ────────────────────────────────

class PinnedButton extends St.Button {
    static { GObject.registerClass(this); }

    constructor(app, tooltip, iconSize, onUnpin) {
        super({
            style_class: 'meu-win-btn meu-pinned-launcher',
            reactive: true,
            can_focus: false,   // sem foco de teclado → sem anel azul no clique
            track_hover: true,
            x_expand: false,
        });

        this._app     = app;
        this._tooltip = tooltip;

        const container = new St.Widget({
            x_expand: false,
            y_expand: true,
            layout_manager: new Clutter.BinLayout(),
        });
        this.set_child(container);

        this._icon = new St.Icon({
            gicon: app.get_icon(),
            icon_size: iconSize,
            style_class: 'meu-win-icon',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        container.add_child(this._icon);

        // Dot indicator — dimmer, shows "pinned but not running"
        this._indicator = new St.Widget({
            style_class: 'meu-indicator meu-indicator-pinned',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.END,
        });
        container.add_child(this._indicator);

        // Context menu
        this._menuMgr = new PopupMenu.PopupMenuManager(this);
        this._menu    = new PopupMenu.PopupMenu(this, 0.5, St.Side.BOTTOM);
        Main.uiGroup.add_child(this._menu.actor);
        this._menu.actor.hide();
        this._menuMgr.addMenu(this._menu);

        const openItem = new PopupMenu.PopupMenuItem('Abrir');
        openItem.connect('activate', () => {
            app.activate();
            this._tooltip.hideNow();
        });
        this._menu.addMenuItem(openItem);

        this._menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const unpinItem = new PopupMenu.PopupMenuItem('Desafixar da barra');
        unpinItem.connect('activate', () => onUnpin(app.get_id()));
        this._menu.addMenuItem(unpinItem);

        this.connect('notify::hover', () => {
            if (this.hover) this._tooltip.showFor(app.get_name(), this);
            else this._tooltip.hideNow();
        });

        this.connect('button-press-event', (_a, ev) => {
            if (ev.get_button() === 3) {
                this._tooltip.hideNow();
                this._menu.toggle();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        this.connect('clicked', () => app.activate());
    }

    setIconSize(sz) { this._icon.icon_size = sz; }

    destroy() {
        this._menu.destroy();
        super.destroy();
    }
}

// ── Barra de tarefas inferior ──────────────────────────────────────────────

class BottomTaskbar extends St.Widget {
    static { GObject.registerClass(this); }

    constructor(monitor, extPath) {
        super({
            name: 'panel',
            style_class: 'meu-panel',
            reactive: true,
            track_hover: true,
            layout_manager: new Clutter.BinLayout(),
        });
        this.connect('destroy', this._onDestroy.bind(this));

        this._extPath   = extPath || '';
        this._monitor   = monitor;
        this._tracker   = Shell.WindowTracker.get_default();
        this._btns      = new Map();  // chave grupo → GroupButton
        this._pBtns     = new Map();  // appId       → PinnedButton
        this._winSigs   = new Map();  // windowId    → { win, sigId }
        this._currentWs = null;
        this._cfg       = loadConfig();
        this._tooltip   = new Tooltip();
        this._preview   = new WindowPreview(monitor);

        this._buildUI();

        const inOverview = Main.overview.visible ||
            (Main.layoutManager._startingUp && Main.sessionMode.hasOverview);
        const overviewOpts = { affectsStruts: true };
        const normalOpts   = { ...overviewOpts, trackFullscreen: true };

        Main.layoutManager.addChrome(this, inOverview ? overviewOpts : normalOpts);
        Main.uiGroup.set_child_above_sibling(this, Main.layoutManager.panelBox);

        this.visible = !inOverview;

        this.connect('notify::height', () => this._updatePosition());
        this._applySize();
        this._applyLayout();
        this._applyColor();

        this.connect('button-press-event', (_a, ev) => {
            if (ev.get_button() === 3) {
                this._cfgMenu.toggle();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });

        this._watchConfig();

        global.display.connectObject(
            'notify::focus-window', () => {
                for (const btn of this._btns.values()) btn._syncStyle();
            },
            'window-created', (_d, win) => {
                if (this._isMenuWindow(win)) this._trackMenu(win);
            },
            this);

        global.window_manager.connectObject(
            'switch-workspace', () => this._rebuild(),
            // O menu é um daemon singleton: fecha escondendo a janela e reabre
            // com present(). Só 'window-created' (1ª vez) não basta — em cada
            // reabertura o Mutter recentraliza. Reancoramos a cada 'map'.
            'map', (_wm, actor) => {
                const win = actor.meta_window;
                if (this._isMenuWindow(win)) this._trackMenu(win);
            },
            this);

        Main.overview.connectObject(
            'showing', () => { this._preview.hideNow(); this._retrackChrome(overviewOpts); this._slideOut(); },
            'hiding',  () => { if (!this._monitor.inFullscreen) this._slideIn(); },
            'hidden',  () => { this._retrackChrome(normalOpts); },
            this);

        this._rebuild();
    }

    // ── UI ──────────────────────────────────────────────────────────────────

    _buildUI() {
        // Grupo centralizado no monitor (estilo Windows 11): Iniciar + janelas.
        // O row preenche a barra inteira; a centralização do cluster é feita por
        // dois espaçadores flexíveis nas pontas (abaixo) — não depende do
        // alinhamento interno do BinLayout, que não centraliza de forma
        // confiável quando há muitas janelas.
        const row = new St.BoxLayout({
            x_expand: true,
            y_expand: true,
            x_align: Clutter.ActorAlign.FILL,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._row = row;
        this.add_child(row);

        // Espaçador esquerdo — absorve a folga à esquerda do cluster.
        this._spacerL = new St.Widget({ x_expand: true, y_expand: true });
        row.add_child(this._spacerL);

        // Botão Iniciar — ícone de fogo (SVG colorido empacotado na extensão)
        let startIcon;
        try {
            const fireFile = Gio.File.new_for_path(this._extPath + '/icons/fire.svg');
            startIcon = new St.Icon({
                gicon: new Gio.FileIcon({ file: fireFile }),
                icon_size: 28,
            });
        } catch (_) {
            startIcon = new St.Icon({ icon_name: 'view-grid-symbolic', icon_size: 26 });
        }
        this._startBtn = new St.Button({
            style_class: 'meu-start-btn',
            reactive: true,
            can_focus: true,
            track_hover: true,
            child: startIcon,
        });
        this._startBtn.connect('clicked', () => {
            try { GLib.spawn_command_line_async(MENU_CMD); } catch (_) {}
        });
        row.add_child(this._startBtn);

        row.add_child(new St.Widget({ style_class: 'meu-vsep' }));

        // Lista de janelas + itens fixados
        this._winList = new St.BoxLayout({
            style_class: 'meu-win-list',
            x_expand: false,
            y_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        row.add_child(this._winList);

        // Espaçador direito — simétrico ao esquerdo: juntos mantêm o cluster
        // centralizado. Sob excesso de janelas ambos colapsam para 0 e o grupo
        // encosta à esquerda (Iniciar sempre visível) em vez de sair de centro.
        this._spacerR = new St.Widget({ x_expand: true, y_expand: true });
        row.add_child(this._spacerR);

        // ── Menu de contexto da barra (botão direito): só Configurações ────
        this._cfgMenuMgr = new PopupMenu.PopupMenuManager(this);
        this._cfgMenu    = new PopupMenu.PopupMenu(this, 0.0, St.Side.BOTTOM);
        Main.uiGroup.add_child(this._cfgMenu.actor);
        this._cfgMenu.actor.hide();
        this._cfgMenuMgr.addMenu(this._cfgMenu);

        const prefsItem = new PopupMenu.PopupMenuItem('Configurações…');
        prefsItem.connect('activate', () => {
            try { GLib.spawn_command_line_async('gnome-extensions prefs firetaskbar@firetaskbar'); } catch (_) {}
        });
        this._cfgMenu.addMenuItem(prefsItem);
    }

    // ── Tamanho ─────────────────────────────────────────────────────────────

    _barHeight() {
        const px = this._cfg.heightPx;
        if (typeof px === 'number' && px > 0) return px;
        return SIZES[this._cfg.size || DEFAULT_SIZE] ?? 48;  // compat versões antigas
    }

    _iconSize() {
        return Math.round(this._barHeight() * 0.46);
    }

    _applySize() {
        this.set_height(this._barHeight());
        const sz = this._iconSize();
        for (const btn of this._btns.values()) btn._icon.icon_size = sz;
        for (const btn of this._pBtns.values()) btn.setIconSize(sz);
        this._normalizeBtnWidths();
        this._updatePosition();
    }

    // Invariante de largura: no modo só-ícone todos os botões da lista têm a
    // MESMA largura (ícone + padding), independente de estarem agrupados,
    // fixados ou de terem badge/indicador. Sem isso, um app agrupado (ex.: Brave
    // com 2 janelas) podia ficar mais largo que os de 1 janela. No modo
    // ícone+nome a largura volta a ser natural (cada nome tem seu tamanho).
    _normalizeBtnWidths() {
        const labelMode = (this._cfg.mode || DEFAULT_MODE) === 'icons_names';
        const all = [...this._btns.values(), ...this._pBtns.values()];
        for (const btn of all) {
            if (labelMode) { btn.set_width(-1); continue; }
            let pad = 18; // fallback = padding 0 9px do .meu-win-btn
            try {
                const node = btn.get_theme_node();
                pad = node.get_padding(St.Side.LEFT) + node.get_padding(St.Side.RIGHT);
            } catch (_) {}
            // Math.max com 44 espelha o min-width do CSS.
            btn.set_width(Math.max(44, Math.round(this._iconSize() + pad)));
        }
    }

    // ── Cor da barra ─────────────────────────────────────────────────────────
    // Sobrepõe o background-color das classes .meu-panel/.meu-panel-dock com a
    // cor escolhida nas preferências. Mantém borda/raio/sombra do stylesheet.
    _applyColor() {
        const c = this._cfg.barColor;
        this.set_style(c ? `background-color: ${c};` : null);
    }

    // ── Layout (full / dock) ────────────────────────────────────────────────

    _applyLayout() {
        const isDock = (this._cfg.layout || DEFAULT_LAYOUT) === 'dock';
        if (isDock) {
            this.add_style_class_name('meu-panel-dock');
            this._startBtn.add_style_class_name('meu-start-btn-dock');
        } else {
            this.remove_style_class_name('meu-panel-dock');
            this._startBtn.remove_style_class_name('meu-start-btn-dock');
        }
        this._updatePosition();
    }

    // ── Monitor de config (aplica mudanças do prefs em tempo real) ───────────

    _watchConfig() {
        this._cfgFile    = Gio.File.new_for_path(CONFIG_PATH);
        this._cfgMonitor = this._cfgFile.monitor_file(Gio.FileMonitorFlags.NONE, null);
        this._cfgMonitor.connect('changed', () => {
            // Salvar um arquivo dispara vários sinais 'changed'; faz debounce.
            if (this._cfgDebounce) GLib.source_remove(this._cfgDebounce);
            this._cfgDebounce = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 120, () => {
                this._cfgDebounce = 0;
                this._onConfigChanged();
                return GLib.SOURCE_REMOVE;
            });
        });
    }

    _onConfigChanged() {
        const old  = this._cfg;
        const next = loadConfig();
        this._cfg  = next;

        // Aplica só o que mudou — evita rebuild duplo nas escritas internas (pin/unpin).
        if (next.heightPx !== old.heightPx || next.size !== old.size)
            this._applySize();
        if (next.barColor !== old.barColor)
            this._applyColor();
        if ((next.layout ?? DEFAULT_LAYOUT) !== (old.layout ?? DEFAULT_LAYOUT))
            this._applyLayout();
        if ((next.mode ?? DEFAULT_MODE) !== (old.mode ?? DEFAULT_MODE)) {
            for (const btn of this._btns.values()) btn.setMode(next.mode || DEFAULT_MODE);
            this._normalizeBtnWidths();
        }
        if (JSON.stringify(next.pinnedApps || []) !== JSON.stringify(old.pinnedApps || []))
            this._rebuild();
    }

    // ── Posicionamento ──────────────────────────────────────────────────────

    _updatePosition() {
        const isDock = (this._cfg.layout || DEFAULT_LAYOUT) === 'dock';
        if (isDock) {
            // Dock: largura adaptativa — acompanha a quantidade de ícones.
            const [, natW] = this.get_preferred_width(-1);
            const maxW = this._monitor.width - DOCK_MARGIN * 2;
            const w    = Math.min(Math.max(natW, 80), maxW);
            this.set_width(w);
            const x = this._monitor.x + Math.round((this._monitor.width - w) / 2);
            const y = this._monitor.y + this._monitor.height - this.height - DOCK_GAP;
            this.set_position(x, y);
            this.remove_style_class_name('meu-panel-narrow');
        } else {
            // Modo cheio (estilo Windows): sempre ocupa a largura total da tela.
            this.set_width(this._monitor.width);
            this.set_position(this._monitor.x, this._monitor.y + this._monitor.height - this.height);
            this.remove_style_class_name('meu-panel-narrow');
        }
    }

    _retrackChrome(opts) {
        Main.layoutManager.untrackChrome(this);
        Main.layoutManager.trackChrome(this, opts);
    }

    _slideIn() {
        this.show();
        this.ease({ translation_y: 0, duration: 200, mode: Clutter.AnimationMode.EASE_OUT_QUAD });
    }

    _slideOut() {
        this.ease({
            translation_y: this.height,
            duration: 200,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => this.hide(),
        });
    }

    // ── Janela do menu Iniciar (posiciona colada acima da barra) ─────────────
    // O Mutter não suporta wlr-layer-shell, então é a extensão que ancora a
    // janela do menu GTK (br.dev.firetaskbar) centralizada logo acima da barra.

    _isMenuWindow(win) {
        if (!win) return false;
        try {
            if (win.get_gtk_application_id &&
                win.get_gtk_application_id() === 'br.dev.firetaskbar') return true;
        } catch (_) {}
        const wc = (win.get_wm_class && win.get_wm_class()) || '';
        const title = (win.get_title && win.get_title()) || '';
        return wc === 'br.dev.firetaskbar' ||
               wc.toLowerCase().includes('firetaskbar') ||
               title.startsWith('FireTaskBar');
    }

    _trackMenu(win) {
        const actor = win.get_compositor_private();
        if (actor && actor.mapped) { this._placeMenu(win, actor); return; }
        if (!actor) {
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, 30, () => {
                const a = win.get_compositor_private();
                if (a) this._placeMenu(win, a);
                return GLib.SOURCE_REMOVE;
            });
            return;
        }
        const id = actor.connect('first-frame', () => {
            actor.disconnect(id);
            this._placeMenu(win, actor);
        });
    }

    // Ancora a janela centralizada COLADA na barra, como se saísse de dentro
    // dela. Usa o topo real da barra (this.y) — assim funciona tanto no modo
    // dock (que flutua DOCK_GAP acima do fundo) quanto no modo painel — e
    // sobrepõe alguns pixels para não deixar fresta. Retorna true se moveu.
    _positionMenu(win) {
        const mon = this._monitor;
        const r   = win.get_frame_rect();
        // Alinhamento horizontal conforme a config do menu (esquerda/centro/
        // direita). Antes era sempre centralizado — por isso a opção "não fazia
        // nada" no GNOME.
        const pos = loadMenuPosition();
        let x;
        if (pos === 'left')
            x = mon.x + MENU_EDGE_MARGIN;
        else if (pos === 'right')
            x = mon.x + mon.width - r.width - MENU_EDGE_MARGIN;
        else
            x = mon.x + Math.round((mon.width - r.width) / 2);
        const barTop = this.get_transformed_position()[1] || this.y;
        const y   = Math.max(mon.y, Math.round(barTop) - r.height + MENU_OVERLAP);
        if (r.x === x && r.y === y) return false;
        this._placingMenu = true;
        win.move_frame(true, x, y);
        this._placingMenu = false;
        return true;
    }

    _placeMenu(win, actor) {
        this._positionMenu(win);
        Main.activateWindow(win);

        // Sem layer-shell no GNOME, é a extensão que ancora a janela. O Mutter
        // pode recentralizá-la a cada reabertura/resize, então reancoramos
        // sempre que ele a mover ou redimensionar (guard evita laço).
        if (this._menuWin !== win) {
            if (this._menuWin) this._menuWin.disconnectObject(this);
            this._menuWin = win;
            win.connectObject(
                'size-changed',     () => this._positionMenu(win),
                'position-changed', () => { if (!this._placingMenu) this._positionMenu(win); },
                'notify::title',    () => this._maybeAnimateMenuClose(win),
                'unmanaged',        () => {
                    win.disconnectObject(this);
                    if (this._menuWin === win) this._menuWin = null;
                },
                this);
        }

        // Sobe deslizando de dentro da barra de tarefas
        if (actor) {
            const r = win.get_frame_rect();
            actor.remove_all_transitions();
            actor.translation_y = r.height;
            actor.opacity       = 255;   // reseta caso o actor seja reaproveitado
            actor.ease({
                translation_y: 0,
                opacity: 255,
                duration: 220,
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
        }
    }

    // Quando o menu pede para fechar (sinaliza pelo título), desliza o actor
    // real de volta para dentro da barra — espelho da animação de abertura.
    // O processo Python esconde a janela logo após a animação terminar.
    _maybeAnimateMenuClose(win) {
        const title = (win.get_title && win.get_title()) || '';
        if (!title.includes('fechando')) return;
        const actor = win.get_compositor_private();
        if (!actor) return;
        const r = win.get_frame_rect();
        actor.remove_all_transitions();
        actor.ease({
            translation_y: r.height,
            opacity: 0,
            duration: 200,
            mode: Clutter.AnimationMode.EASE_IN_QUAD,
        });
    }

    // ── Fixar / Desafixar ───────────────────────────────────────────────────

    _pin(appId) {
        if (!this._cfg.pinnedApps.includes(appId)) {
            this._cfg.pinnedApps.push(appId);
            saveConfig(this._cfg);
            this._rebuild();
        }
    }

    _unpin(appId) {
        const idx = this._cfg.pinnedApps.indexOf(appId);
        if (idx !== -1) {
            this._cfg.pinnedApps.splice(idx, 1);
            saveConfig(this._cfg);
            this._rebuild();
        }
    }

    _togglePin(appId) {
        if (this._cfg.pinnedApps.includes(appId))
            this._unpin(appId);
        else
            this._pin(appId);
    }

    // ── Rebuild completo ─────────────────────────────────────────────────────
    // Reconstrói toda a lista. Chamado na troca de workspace e ao fixar/desafixar.

    _rebuild() {
        this._clearAll();
        this._connectWorkspaceSignals();

        const pinnedApps  = this._cfg.pinnedApps || [];
        const appSystem   = Shell.AppSystem.get_default();
        const openWindows = this._currentWs.list_windows()
            .filter(w => !w.skip_taskbar && !this._isMenuWindow(w))
            .sort((a, b) => a.get_stable_sequence() - b.get_stable_sequence());

        // Agrupa janelas por app. Janelas sem app viram grupo próprio (1 janela).
        // chave → { app, appId, wins }. A ordem de inserção segue stable_sequence.
        const groups = new Map();
        for (const win of openWindows) {
            const app = this._tracker.get_window_app(win);
            const key = app ? app.get_id() : ('__win_' + win.get_id());
            if (!groups.has(key))
                groups.set(key, { app, appId: app ? app.get_id() : null, wins: [] });
            groups.get(key).wins.push(win);
        }

        const handled = new Set();

        // 1. Apps fixados — na ordem salva
        for (const appId of pinnedApps) {
            const grp = groups.get(appId);
            if (grp && grp.wins.length > 0) {
                // Fixado com janelas → um GroupButton (classe 'pinned')
                this._addGroupBtn(appId, grp.app, grp.wins, true);
                handled.add(appId);
            } else {
                // Fixado sem janelas → PinnedButton (launcher)
                const app = appSystem.lookup_app(appId);
                if (app) this._addPinnedBtn(appId, app);
            }
        }

        // 2. Grupos de apps não fixados — na ordem das janelas
        for (const [key, grp] of groups) {
            if (handled.has(key)) continue;
            this._addGroupBtn(key, grp.app, grp.wins, false);
        }

        this._normalizeBtnWidths();

        if ((this._cfg.layout || DEFAULT_LAYOUT) === 'dock')
            this._updatePosition();
    }

    _addGroupBtn(key, app, wins, isPinned) {
        if (this._btns.has(key)) return;

        const appId = app ? app.get_id() : null;

        const btn = new GroupButton(
            app, wins, this._tracker, this._tooltip, this._preview,
            this._iconSize(), this._cfg.mode || DEFAULT_MODE,
            isPinned,
            appId ? () => this._togglePin(appId) : null);

        this._winList.add_child(btn);
        this._btns.set(key, btn);

        // Reconstrói a barra quando qualquer janela do grupo fecha.
        for (const win of wins) {
            const sigId = win.connect('unmanaged', () => this._rebuild());
            this._winSigs.set(win.get_id(), { win, sigId });
        }
    }

    _addPinnedBtn(appId, app) {
        if (this._pBtns.has(appId)) return;
        const btn = new PinnedButton(
            app, this._tooltip, this._iconSize(),
            (id) => this._unpin(id));
        this._winList.add_child(btn);
        this._pBtns.set(appId, btn);
    }

    _clearAll() {
        for (const { win, sigId } of this._winSigs.values()) {
            try { win.disconnect(sigId); } catch (_) {}
        }
        this._winSigs.clear();
        for (const btn of this._btns.values()) btn.destroy();
        this._btns.clear();
        for (const btn of this._pBtns.values()) btn.destroy();
        this._pBtns.clear();
        this._winList.remove_all_children();
    }

    // ── Sinais de workspace ─────────────────────────────────────────────────

    _connectWorkspaceSignals() {
        if (this._currentWs) this._currentWs.disconnectObject(this);
        this._currentWs = global.workspace_manager.get_active_workspace();
        this._currentWs.connectObject(
            'window-added',   (_ws, win) => {
                if (this._isMenuWindow(win)) { this._trackMenu(win); return; }
                if (win.skip_taskbar) return;
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, 150, () => {
                    if (!win.skip_taskbar) this._rebuild();
                    return GLib.SOURCE_REMOVE;
                });
            },
            'window-removed', () => this._rebuild(),
            this);
    }

    // ── Destruição ──────────────────────────────────────────────────────────

    _onDestroy() {
        global.display.disconnectObject(this);
        global.window_manager.disconnectObject(this);
        Main.overview.disconnectObject(this);
        if (this._currentWs) {
            this._currentWs.disconnectObject(this);
            this._currentWs = null;
        }
        if (this._menuWin) {
            this._menuWin.disconnectObject(this);
            this._menuWin = null;
        }
        this._clearAll();
        if (this._cfgDebounce) { GLib.source_remove(this._cfgDebounce); this._cfgDebounce = 0; }
        if (this._cfgMonitor) { this._cfgMonitor.cancel(); this._cfgMonitor = null; }
        this._cfgFile = null;
        if (this._tooltip) { this._tooltip.destroy(); this._tooltip = null; }
        if (this._preview) { this._preview.destroy(); this._preview = null; }
        if (this._cfgMenu) { this._cfgMenu.destroy(); this._cfgMenu = null; }
    }

    destroy() {
        Main.layoutManager.removeChrome(this);
        super.destroy();
    }
}

// ── Extensão ───────────────────────────────────────────────────────────────

export default class FireTaskBarExtension extends Extension {
    enable() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor) return;

        this._taskbar = new BottomTaskbar(monitor, this.path);
        this._setupOverlayKey();

        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 800, () => {
            try { GLib.spawn_command_line_async(DAEMON_CMD); } catch (_) {}
            return GLib.SOURCE_REMOVE;
        });
    }

    disable() {
        this._removeOverlayKey();
        if (this._taskbar) {
            this._taskbar.hide();
            this._taskbar.destroy();
            this._taskbar = null;
        }
    }

    // ── Tecla Super (overlay-key) ────────────────────────────────────────────
    // O gsd NÃO consegue capturar a tecla Super sozinha (modificador puro), por
    // isso o atalho custom falhava ("Failed to grab accelerator"). No GNOME o
    // único caminho confiável é o sinal 'overlay-key' do Mutter: bloqueamos o
    // handler nativo (que abre o Overview) e abrimos o FireTaskBar no lugar.
    // O Mutter só emite esse sinal quando a config overlay-key casa com a tecla,
    // então garantimos que continua 'Super_L'.

    _setupOverlayKey() {
        this._mutterSettings = new Gio.Settings({ schema_id: 'org.gnome.mutter' });
        if (this._mutterSettings.get_string('overlay-key') !== 'Super_L')
            this._mutterSettings.set_string('overlay-key', 'Super_L');

        this._defaultOverlayId =
            GObject.signal_handler_find(global.display, { signalId: 'overlay-key' });
        if (this._defaultOverlayId)
            global.display.block_signal_handler(this._defaultOverlayId);

        this._overlayId = global.display.connect('overlay-key', () => {
            try { GLib.spawn_command_line_async(MENU_CMD); } catch (_) {}
        });
    }

    _removeOverlayKey() {
        if (this._overlayId) {
            global.display.disconnect(this._overlayId);
            this._overlayId = 0;
        }
        if (this._defaultOverlayId) {
            global.display.unblock_signal_handler(this._defaultOverlayId);
            this._defaultOverlayId = 0;
        }
        this._mutterSettings = null;
    }
}
