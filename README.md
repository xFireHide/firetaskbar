# FireTaskBar

GTK4 application launcher for GNOME. Opens with the **Super** (Windows) key.

![Preview](https://raw.githubusercontent.com/xFireHide/firetaskbar/main/preview.jpg)

## Install

One-liner (recommended):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xFireHide/firetaskbar/main/instalar.sh)
```

Or clone and run `bash firetaskbar/instalar.sh`. The installer handles everything:
deps (PyGObject, GTK4), copies files to `~/.local/share/firetaskbar/`, sets up
autostart, and binds the **Super** key.

Uninstall: `bash ~/.local/share/firetaskbar/desinstalar.sh`

Dependencies (installed automatically): `python3-gobject gtk4` (Fedora/Nobara),
`python3-gi gir1.2-gtk-4.0` (Ubuntu/Debian), `python-gobject gtk4` (Arch).
Optional `gtk4-layer-shell` anchors the menu to the screen on Wayland.

## Usage

| Action | How |
|---|---|
| Open / close | **Super** key |
| Search | type in the search box |
| Filter by category | click the left sidebar |
| Open app | click a card |
| Close | `Esc` or click outside |
| Account / Menu settings | avatar/name and gear icon in the footer |
| Lock / Log out / Restart / Shut down | footer buttons (right) |

**Menu settings** (footer gear): Position (Left/Center/Right, applies on next open),
Width (Narrow/Medium/Wide, live), and Color (own or inherited from the bar).

## Troubleshooting

- **Super doesn't open the menu** → Settings → Keyboard → Shortcuts → Custom →
  **FireTaskBar** → press the Windows key.
- **Daemon didn't start** → `cat /tmp/firetaskbar.log`, then run
  `python3 ~/.local/share/firetaskbar/firetaskbar.py`.
- **Menu floats in the center** → the GNOME Shell extension anchors it; after
  editing the extension you must log out/in on Wayland to reload it.

Architecture, daemon lifecycle, and positioning: see **[ARQUITETURA.md](ARQUITETURA.md)**.
