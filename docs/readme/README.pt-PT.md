# PyGUIbud

[English](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/README.md) ·
[Español](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.es-ES.md) ·
[Português (Portugal)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-PT.md) ·
[Português (Brasil)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-BR.md) ·
[Deutsch](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.de-DE.md) ·
[Italiano](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.it-IT.md) ·
[Nederlands](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.nl-NL.md) ·
[Français](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.fr-FR.md)

Um designer de GUI de arrastar e largar para **ttkbootstrap** (com back-ends de tkinter e PySide6)
que guarda ficheiros `.ui` portáteis. Carregue um ficheiro `.ui` em tempo de execução com
`pyguibud-runtime`, ou converta-o num módulo Python simples com `pyguibud-uic`.

![Demonstração: uma etiqueta e um botão são arrastados da paleta para uma nova janela principal, o botão recebe um texto e o gestor on_hello, o formulário é guardado como hello.ui e executado, e ao clicar no botão a etiqueta muda](https://raw.githubusercontent.com/larrezze-dev/PyGUIbud_CLAUDE/master/docs/images/demo.gif)

## Instalação
Python 3.10–3.13. No Linux, instale primeiro o Tk (`sudo apt install python3-tk`).

```bash
pip install pyguibud          # pip
uv tool install pyguibud      # uv: os comandos pyguibud e pyguibud-uic
uvx pyguibud                  # uv: execute o designer sem o instalar
```

Adicione o extra `[pyside]` (`pip install "pyguibud[pyside]"`) para o back-end PySide6. Consulte o
[guia de instalação completo](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/install.md).

## Início rápido
```bash
pyguibud                                 # abre o designer
pyguibud-uic --check form.ui             # valida um ficheiro .ui
pyguibud-uic form.ui                     # gera o módulo Python form_ui.py
pyguibud-uic form.ui -o my_form.py       # ... ou escolha o nome de saída com -o
pyguibud-uic --extract form.ui -o form.pot   # extrai as cadeias de texto para os tradutores
```

```python
from pyguibud_runtime import load_ui


class Handlers:
    def on_quit(self) -> None:
        ui.destroy()


ui = load_ui("form.ui", Handlers())
ui.run()
```

`load_ui(path, handlers=None, *, strict=True, backend="ttkbootstrap", master=None, lang=None,
localedir=None, translator=None)` aceita `backend="ttkbootstrap"` (a referência),
`"tkinter"` ou `"pyside6"`. O código gerado por `pyguibud-uic` não importa o PyGUIbud.
As aplicações que apenas carregam ficheiros `.ui` precisam somente do
[`pyguibud-runtime`](https://pypi.org/project/pyguibud-runtime/).

## Funcionalidades
- Arraste widgets de uma paleta para uma área de desenho; mova-os, redimensione-os e altere o
  elemento pai aí ou na árvore de objetos. Seleção múltipla, copiar/colar (também entre
  ficheiros) e anular/refazer para cada alteração.
- Inspetor de propriedades com editores tipados, edição de disposições grid e pack, editor de
  menus, gestores de eventos e variáveis associadas a widgets.
- Janelas principais, caixas de diálogo e componentes reutilizáveis (`<include>`), com modelos para
  novos ficheiros.
- Pré-visualização em direto num processo separado, com mudança de tema e de idioma em tempo real,
  e ainda uma pseudo-localização (`en_XA`) para verificar a expansão do texto.
- Utilização apenas com o teclado, gravação automática com recuperação após falhas e proteção
  contra alterações por guardar.
- As ações inválidas são bloqueadas com um motivo traduzido, em vez de serem aplicadas em silêncio.
- A gravação é atómica e mantém uma cópia de segurança. Os ficheiros corrompidos, demasiado grandes
  ou com um esquema mais recente são recusados. Um ficheiro `.ui` não contém código; apenas são
  executados os plugins de widgets que tiver instalado.
- Um formato XML `.ui` com versões e validado.

Fora da v0.1.0: o editor de tipos de letra, adiado para depois da v1.

## Toolkits suportados
| Back-end | Toolkit | Licença |
| --- | --- | --- |
| `ttkbootstrap` (referência) | [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) | MIT |
| `tkinter` | tkinter, da biblioteca padrão do Python | PSF |
| `pyside6` | [PySide6](https://pypi.org/project/PySide6/), extra opcional `[pyside]` | LGPL-3.0 |

O PyGUIbud depende do ttkbootstrap. O PySide6 nunca é incluído: é importado do seu ambiente
apenas se instalar o extra. Obrigado aos autores dos três.

## Idiomas
O designer está disponível em inglês britânico, espanhol (Espanha), português (Portugal e Brasil),
alemão, italiano, neerlandês e francês, com mudança de idioma em tempo real.

## Plugins
É possível adicionar widgets através do ponto de entrada `pyguibud.widgets`, e um plugin que falhe aparece como
marcador de posição em vez de deitar abaixo o designer. Consulte o
[plugin de exemplo](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/tree/master/examples/acme_plugin)
e o
[ADR-004](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/adr/ADR-004-widget-plugins.md).

## Projeto
- Código-fonte e problemas: <https://github.com/larrezze-dev/PyGUIbud_CLAUDE>
- Alterações: [CHANGELOG.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CHANGELOG.md)
- Contribuir: [CONTRIBUTING.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CONTRIBUTING.md)
  e o
  [Código de Conduta](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CODE_OF_CONDUCT.md)
- Licença: MIT, consulte [LICENSE](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/LICENSE).
  O nome, o logótipo e os recursos de marca da SAPÉ não estão abrangidos por ela; consulte
  [NOTICE.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/NOTICE.md).

Criado por Luciano Arrezze e programado com o suporte de Claude Code.
