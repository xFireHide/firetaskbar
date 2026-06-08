import Adw from 'gi://Adw';
import Gdk from 'gi://Gdk';
import GLib from 'gi://GLib';
import Gtk from 'gi://Gtk';

import { ExtensionPreferences } from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const CONFIG_PATH = GLib.get_home_dir() + '/.config/firetaskbar.json';

const MODES = {
    icons:       'Somente ícones',
    icons_names: 'Ícone + nome',
};

const LAYOUTS = {
    full: 'Largura total',
    dock: 'Dock  (estilo macOS)',
};

function loadConfig() {
    try {
        const [ok, bytes] = GLib.file_get_contents(CONFIG_PATH);
        if (ok) return JSON.parse(new TextDecoder().decode(bytes));
    } catch (_) {}
    return { size: 'normal', mode: 'icons', layout: 'full' };
}

function saveConfig(cfg) {
    try {
        GLib.file_set_contents(CONFIG_PATH, JSON.stringify(cfg));
    } catch (_) {}
}

export default class FireTaskBarPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const cfg = loadConfig();

        window.set_title('Configurações — FireTaskBar');
        window.set_default_size(520, 480);
        window.set_search_enabled(false);

        const page = new Adw.PreferencesPage({
            title: 'Barra de tarefas',
            icon_name: 'preferences-desktop-symbolic',
        });
        window.add(page);

        // ── Aparência ─────────────────────────────────────────────────────────
        const groupAparencia = new Adw.PreferencesGroup({ title: 'Aparência' });
        page.add(groupAparencia);

        const curHeight = (typeof cfg.heightPx === 'number' && cfg.heightPx > 0)
            ? cfg.heightPx : 48;
        const heightRow = new Adw.SpinRow({
            title:      'Altura da barra',
            subtitle:   'Altura em pixels (24–120)',
            adjustment: new Gtk.Adjustment({
                lower: 24, upper: 120, step_increment: 1, page_increment: 4,
                value: curHeight,
            }),
        });
        heightRow.connect('notify::value', () => {
            cfg.heightPx = Math.round(heightRow.get_value());
            saveConfig(cfg);
        });
        groupAparencia.add(heightRow);

        // ── Cor da barra ────────────────────────────────────────────────────────
        const rgba = new Gdk.RGBA();
        if (!rgba.parse(cfg.barColor || 'rgba(18,18,22,0.96)'))
            rgba.parse('rgba(18,18,22,0.96)');

        const colorBtn = new Gtk.ColorDialogButton({
            dialog:  new Gtk.ColorDialog({ with_alpha: true }),
            rgba,
            valign:  Gtk.Align.CENTER,
        });
        colorBtn.connect('notify::rgba', () => {
            cfg.barColor = colorBtn.get_rgba().to_string();  // ex.: rgba(0,0,0,1)
            saveConfig(cfg);
        });

        const colorRow = new Adw.ActionRow({
            title:    'Cor da barra',
            subtitle: 'Mesma cor é usada no menu Iniciar (suporta transparência)',
        });
        colorRow.add_suffix(colorBtn);
        colorRow.set_activatable_widget(colorBtn);
        groupAparencia.add(colorRow);

        // ── Layout ────────────────────────────────────────────────────────────
        const groupLayout = new Adw.PreferencesGroup({ title: 'Layout' });
        page.add(groupLayout);

        const layoutKeys = Object.keys(LAYOUTS);
        const layoutRow  = new Adw.ComboRow({
            title:    'Modo',
            subtitle: 'Largura total ou dock flutuante estilo macOS',
            model:    new Gtk.StringList({ strings: Object.values(LAYOUTS) }),
        });
        layoutRow.set_selected(Math.max(0, layoutKeys.indexOf(cfg.layout ?? 'full')));
        layoutRow.connect('notify::selected', () => {
            cfg.layout = layoutKeys[layoutRow.selected] ?? 'full';
            saveConfig(cfg);
        });
        groupLayout.add(layoutRow);

        // ── Janelas ───────────────────────────────────────────────────────────
        const groupJanelas = new Adw.PreferencesGroup({ title: 'Janelas' });
        page.add(groupJanelas);

        const modeKeys = Object.keys(MODES);
        const modeRow  = new Adw.ComboRow({
            title:    'Modo de exibição',
            subtitle: 'Como os botões de janela aparecem na barra',
            model:    new Gtk.StringList({ strings: Object.values(MODES) }),
        });
        modeRow.set_selected(Math.max(0, modeKeys.indexOf(cfg.mode ?? 'icons')));
        modeRow.connect('notify::selected', () => {
            cfg.mode = modeKeys[modeRow.selected] ?? 'icons';
            saveConfig(cfg);
        });
        groupJanelas.add(modeRow);
    }
}
