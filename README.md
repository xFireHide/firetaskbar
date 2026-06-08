# FireTaskBar

Launcher de aplicativos GTK4 para GNOME. Abre com a tecla **Super** (Windows).

![Preview](https://raw.githubusercontent.com/xFireHide/firetaskbar/main/preview.jpg)

## Instalar

### Uma linha (recomendado — após formatar o Linux)

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/xFireHide/firetaskbar/main/instalar.sh)
```

### Ou clonar e instalar

```bash
git clone https://github.com/xFireHide/firetaskbar.git
bash firetaskbar/instalar.sh
```

O instalador faz tudo automaticamente:
- Instala as dependências (PyGObject, GTK4)
- Copia os arquivos para `~/.local/share/firetaskbar/`
- Configura o autostart (inicia com o sistema)
- Mapeia a tecla **Super** para abrir o menu

## Desinstalar

```bash
bash ~/.local/share/firetaskbar/desinstalar.sh
```

## Dependências

Instaladas automaticamente pelo `instalar.sh`:

| Distro | Pacotes |
|--------|---------|
| Fedora / Nobara | `python3-gobject gtk4` |
| Ubuntu / Debian | `python3-gi gir1.2-gtk-4.0` |
| Arch Linux | `python-gobject gtk4` |

Opcional: `gtk4-layer-shell` (ancora o menu na tela via Wayland — como o ArcMenu)

## Uso

| Ação | Como |
|------|------|
| Abrir / fechar | Tecla **Super** (Windows) |
| Pesquisar | Digite na caixa de busca |
| Filtrar por categoria | Clique na sidebar esquerda |
| Abrir app | Clique no card |
| Fechar | `Esc` ou clique fora |
| Conta de usuário | Clique no **avatar/nome** no rodapé |
| Configurações do Menu | Clique na **engrenagem** do rodapé |
| Bloquear / Sair / Reiniciar / Desligar | Botões no rodapé (à direita) |

### Configurações do Menu

Pela engrenagem no rodapé. O que dá pra ajustar:

| Opção | Valores | Observação |
|-------|---------|------------|
| **Posição** | Esquerda · Centro · Direita | Vale na **próxima abertura** do menu (a extensão reancora ao abrir). |
| **Largura** | Estreito · Médio · Largo | Aplica na hora. |
| **Cor** | Própria ou herdada da barra | Desligada = usa a cor da barra de tarefas. |

## Problemas comuns

**A tecla Super não abre o menu**
→ Configurações → Teclado → Atalhos → Atalhos Personalizados → **FireTaskBar** → pressione a tecla Windows

**Daemon não iniciou**
```bash
cat /tmp/firetaskbar.log
python3 ~/.local/share/firetaskbar/firetaskbar.py
```

**O menu abre longe da barra (flutuando no centro)**
→ Quem ancora o menu na barra é a extensão do GNOME Shell. Depois de alterar a
extensão é preciso **logout/login** no Wayland para o GNOME recarregar o módulo
(`gnome-extensions disable/enable` não basta). Detalhes em [ARQUITETURA.md](ARQUITETURA.md#posicionamento-por-que-o-gnome-não-usa-layer-shell).

## Para quem desenvolve

Arquitetura, ciclo de vida do daemon, posicionamento e como recarregar cada
parte: veja **[ARQUITETURA.md](ARQUITETURA.md)**.
