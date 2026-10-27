# PyGUIbud

[English](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/README.md) ·
[Español](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.es-ES.md) ·
[Português (Portugal)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-PT.md) ·
[Português (Brasil)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-BR.md) ·
[Deutsch](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.de-DE.md) ·
[Italiano](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.it-IT.md) ·
[Nederlands](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.nl-NL.md) ·
[Français](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.fr-FR.md)

Um designer de GUI de arrastar e soltar para **ttkbootstrap** (com back-ends de tkinter e PySide6)
que salva arquivos `.ui` portáteis. Carregue um arquivo `.ui` em tempo de execução com
`pyguibud-runtime`, ou converta-o em um módulo Python simples com `pyguibud-uic`.

<!-- demo GIF (Step 21b): drag → save → run -->

## Instalação
Python 3.10–3.13. No Linux, instale primeiro o Tk (`sudo apt install python3-tk`).

```bash
pip install pyguibud          # pip
uv tool install pyguibud      # uv: os comandos pyguibud e pyguibud-uic
uvx pyguibud                  # uv: execute o designer sem instalar
```

Adicione o extra `[pyside]` (`pip install "pyguibud[pyside]"`) para o back-end PySide6. Veja o
[guia de instalação completo](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/install.md).

## Início rápido
```bash
pyguibud                                 # abre o designer
pyguibud-uic --check form.ui             # valida um arquivo .ui
pyguibud-uic form.ui                     # gera o módulo Python form_ui.py
pyguibud-uic form.ui -o my_form.py       # ... ou escolha o nome de saída com -o
pyguibud-uic --extract form.ui -o form.pot   # extrai as strings para os tradutores
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
`"tkinter"` ou `"pyside6"`. O código gerado pelo `pyguibud-uic` não importa o PyGUIbud.
Os aplicativos que apenas carregam arquivos `.ui` precisam somente do
[`pyguibud-runtime`](https://pypi.org/project/pyguibud-runtime/).

## Recursos
- Arraste widgets de uma paleta para uma tela de desenho; mova, redimensione e mude o elemento pai
  deles ali ou na árvore de objetos. Seleção múltipla, copiar/colar (também entre arquivos) e
  desfazer/refazer para cada alteração.
- Inspetor de propriedades com editores tipados, edição de layouts grid e pack, editor de menus,
  manipuladores de eventos e variáveis vinculadas a widgets.
- Janelas principais, caixas de diálogo e componentes reutilizáveis (`<include>`), com modelos para
  novos arquivos.
- Pré-visualização ao vivo em um processo separado, com troca de tema e de idioma em tempo real,
  além de uma pseudo-localidade (`en_XA`) para verificar a expansão do texto.
- Operação somente pelo teclado, salvamento automático com recuperação após falhas e proteção
  contra alterações não salvas.
- Ações inválidas são bloqueadas com um motivo traduzido, em vez de serem aplicadas silenciosamente.
- O salvamento é atômico e mantém um backup. Arquivos corrompidos, grandes demais ou com um esquema
  mais novo são recusados. Um arquivo `.ui` não contém código; apenas os plugins de widgets que
  você instalou são executados.
- Um formato XML `.ui` versionado e validado.

Fora da v0.1.0: o editor de fontes, adiado para depois da v1.

## Toolkits compatíveis
| Back-end | Toolkit | Licença |
| --- | --- | --- |
| `ttkbootstrap` (referência) | [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) | MIT |
| `tkinter` | tkinter, da biblioteca padrão do Python | PSF |
| `pyside6` | [PySide6](https://pypi.org/project/PySide6/), extra opcional `[pyside]` | LGPL-3.0 |

O PyGUIbud depende do ttkbootstrap. O PySide6 nunca é incluído: ele é importado do seu ambiente
somente se você instalar o extra. Obrigado aos autores dos três.

## Idiomas
O designer está disponível em inglês britânico, espanhol (Espanha), português (Portugal e Brasil),
alemão, italiano, holandês e francês, com troca de idioma em tempo real.

## Plugins
É possível adicionar widgets pelo ponto de entrada `pyguibud.widgets`, e um plugin que falhar aparece como
um espaço reservado em vez de derrubar o designer. Veja o
[plugin de exemplo](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/tree/master/examples/acme_plugin)
e o
[ADR-004](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/adr/ADR-004-widget-plugins.md).

## Projeto
- Código-fonte e issues: <https://github.com/larrezze-dev/PyGUIbud_CLAUDE>
- Alterações: [CHANGELOG.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CHANGELOG.md)
- Como contribuir: [CONTRIBUTING.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CONTRIBUTING.md)
  e o
  [Código de Conduta](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CODE_OF_CONDUCT.md)
- Licença: MIT, veja [LICENSE](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/LICENSE).
  O nome, o logotipo e os recursos de marca da SAPÉ não são cobertos por ela; veja
  [NOTICE.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/NOTICE.md).

Criado por Luciano Arrezze e programado com o suporte de Claude Code.
