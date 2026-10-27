# PyGUIbud

[English](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/README.md) ·
[Español](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.es-ES.md) ·
[Português (Portugal)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-PT.md) ·
[Português (Brasil)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-BR.md) ·
[Deutsch](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.de-DE.md) ·
[Italiano](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.it-IT.md) ·
[Nederlands](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.nl-NL.md) ·
[Français](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.fr-FR.md)

Un designer di GUI drag-and-drop per **ttkbootstrap** (con back-end tkinter e PySide6) che salva
file `.ui` portabili. Carica un file `.ui` a runtime con `pyguibud-runtime`, oppure trasformalo in
un semplice modulo Python con `pyguibud-uic`.

<!-- demo GIF (Step 21b): drag → save → run -->

## Installazione
Python 3.10–3.13. Su Linux, installa prima Tk (`sudo apt install python3-tk`).

```bash
pip install pyguibud          # pip
uv tool install pyguibud      # uv: i comandi pyguibud e pyguibud-uic
uvx pyguibud                  # uv: esegui il designer senza installarlo
```

Aggiungi l'extra `[pyside]` (`pip install "pyguibud[pyside]"`) per il back-end PySide6. Consulta la
[guida completa all'installazione](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/install.md).

## Per iniziare
```bash
pyguibud                                 # apri il designer
pyguibud-uic --check form.ui             # convalida un file .ui
pyguibud-uic form.ui                     # genera il modulo Python form_ui.py
pyguibud-uic form.ui -o my_form.py       # ... oppure scegli il nome di output con -o
pyguibud-uic --extract form.ui -o form.pot   # estrai le stringhe per i traduttori
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
localedir=None, translator=None)` accetta `backend="ttkbootstrap"` (il riferimento),
`"tkinter"` o `"pyside6"`. Il codice generato da `pyguibud-uic` non importa PyGUIbud.
Le applicazioni che si limitano a caricare file `.ui` hanno bisogno soltanto di
[`pyguibud-runtime`](https://pypi.org/project/pyguibud-runtime/).

## Funzionalità
- Trascina i widget da una tavolozza su un'area di disegno; spostali, ridimensionali e cambia il
  genitore lì o nell'albero degli oggetti. Selezione multipla, copia/incolla (anche tra file),
  annulla/ripeti per ogni modifica.
- Ispettore delle proprietà con editor tipizzati, modifica dei layout grid e pack, editor dei menu,
  gestori di eventi e variabili collegate ai widget.
- Finestre principali, finestre di dialogo e componenti riutilizzabili (`<include>`), con modelli
  per i nuovi file.
- Anteprima dal vivo in un processo separato, con cambio dal vivo di tema e lingua, più una
  pseudo-localizzazione (`en_XA`) per verificare l'espansione del testo.
- Utilizzo esclusivamente da tastiera, salvataggio automatico con ripristino dopo un arresto
  anomalo e una protezione contro le modifiche non salvate.
- Le azioni non valide vengono bloccate con un motivo tradotto, invece di essere applicate in
  silenzio.
- Il salvataggio è atomico e conserva una copia di backup. I file danneggiati, troppo grandi o con
  uno schema più recente vengono rifiutati. Un file `.ui` non contiene codice; vengono eseguiti
  solo i plugin di widget che hai installato.
- Un formato XML `.ui` versionato e convalidato.

Non incluso nella v0.1.0: l'editor dei caratteri, rinviato a dopo la v1.

## Toolkit supportati
| Back-end | Toolkit | Licenza |
| --- | --- | --- |
| `ttkbootstrap` (riferimento) | [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) | MIT |
| `tkinter` | tkinter, dalla libreria standard di Python | PSF |
| `pyside6` | [PySide6](https://pypi.org/project/PySide6/), extra opzionale `[pyside]` | LGPL-3.0 |

PyGUIbud dipende da ttkbootstrap. PySide6 non viene mai incluso: viene importato dal tuo ambiente
solo se installi l'extra. Grazie agli autori di tutti e tre.

## Lingue
Il designer è disponibile in inglese britannico, spagnolo (Spagna), portoghese (Portogallo e Brasile),
tedesco, italiano, olandese e francese, con cambio di lingua dal vivo.

## Plugin
I widget si possono aggiungere tramite l'entry point `pyguibud.widgets`, e un plugin che va in crash appare come
segnaposto invece di far cadere il designer. Consulta il
[plugin di esempio](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/tree/master/examples/acme_plugin)
e l'
[ADR-004](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/adr/ADR-004-widget-plugins.md).

## Progetto
- Sorgenti e segnalazioni: <https://github.com/larrezze-dev/PyGUIbud_CLAUDE>
- Modifiche: [CHANGELOG.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CHANGELOG.md)
- Come contribuire: [CONTRIBUTING.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CONTRIBUTING.md)
  e il
  [Codice di condotta](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CODE_OF_CONDUCT.md)
- Licenza: MIT, vedi [LICENSE](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/LICENSE).
  Il nome, il logo e le risorse del marchio SAPÉ non sono coperti da essa; vedi
  [NOTICE.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/NOTICE.md).

Creato da Luciano Arrezze e programmato con il supporto di Claude Code.
