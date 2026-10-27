# PyGUIbud

[English](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/README.md) ·
[Español](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.es-ES.md) ·
[Português (Portugal)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-PT.md) ·
[Português (Brasil)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-BR.md) ·
[Deutsch](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.de-DE.md) ·
[Italiano](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.it-IT.md) ·
[Nederlands](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.nl-NL.md) ·
[Français](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.fr-FR.md)

Ein Drag-and-drop-GUI-Designer für **ttkbootstrap** (mit tkinter- und PySide6-Back-ends), der
portable `.ui`-Dateien speichert. Laden Sie eine `.ui`-Datei zur Laufzeit mit `pyguibud-runtime`
oder wandeln Sie sie mit `pyguibud-uic` in ein einfaches Python-Modul um.

![Demo: Ein Label und eine Schaltfläche werden aus der Palette in ein neues Hauptfenster gezogen, die Schaltfläche erhält einen Text und den Handler on_hello, das Formular wird als hello.ui gespeichert und ausgeführt, und ein Klick auf die Schaltfläche ändert das Label](https://raw.githubusercontent.com/larrezze-dev/PyGUIbud_CLAUDE/master/docs/images/demo.gif)

## Installation
Python 3.10–3.13. Installieren Sie unter Linux zuerst Tk (`sudo apt install python3-tk`).

```bash
pip install pyguibud          # pip
uv tool install pyguibud      # uv: die Befehle pyguibud und pyguibud-uic
uvx pyguibud                  # uv: den Designer ohne Installation ausführen
```

Fügen Sie für das PySide6-Back-end das Extra `[pyside]` hinzu (`pip install "pyguibud[pyside]"`). Siehe die
[vollständige Installationsanleitung](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/install.md).

## Schnellstart
```bash
pyguibud                                 # den Designer öffnen
pyguibud-uic --check form.ui             # eine .ui-Datei validieren
pyguibud-uic form.ui                     # das Python-Modul form_ui.py erzeugen
pyguibud-uic form.ui -o my_form.py       # ... oder den Ausgabenamen mit -o wählen
pyguibud-uic --extract form.ui -o form.pot   # die Texte für die Übersetzer extrahieren
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
localedir=None, translator=None)` akzeptiert `backend="ttkbootstrap"` (die Referenz),
`"tkinter"` oder `"pyside6"`. Von `pyguibud-uic` erzeugter Code importiert PyGUIbud nicht.
Anwendungen, die nur `.ui`-Dateien laden, benötigen lediglich
[`pyguibud-runtime`](https://pypi.org/project/pyguibud-runtime/).

## Funktionen
- Ziehen Sie Widgets aus einer Palette auf eine Zeichenfläche; dort oder im Objektbaum lassen sie
  sich verschieben, in der Größe ändern und umhängen. Mehrfachauswahl, Kopieren/Einfügen (auch
  zwischen Dateien), Rückgängig/Wiederholen für jede Änderung.
- Eigenschaftsinspektor mit typisierten Editoren, Bearbeitung von grid- und pack-Layouts,
  Menüeditor, Ereignisbehandlung und an Widgets gebundene Variablen.
- Hauptfenster, Dialoge und wiederverwendbare Komponenten (`<include>`), mit Vorlagen für neue
  Dateien.
- Live-Vorschau in einem separaten Prozess mit Live-Umschaltung von Design und Sprache sowie einer
  Pseudo-Locale (`en_XA`), um die Textausdehnung zu prüfen.
- Reine Tastaturbedienung, automatisches Speichern mit Absturzwiederherstellung und ein Schutz vor
  ungespeicherten Änderungen.
- Ungültige Aktionen werden mit einer übersetzten Begründung blockiert, statt stillschweigend
  ausgeführt zu werden.
- Das Speichern ist atomar und behält eine Sicherungskopie. Beschädigte, zu große oder mit einem
  neueren Schema erstellte Dateien werden abgelehnt. Eine `.ui`-Datei enthält keinen Code; nur die
  von Ihnen installierten Widget-Plugins werden ausgeführt.
- Ein versioniertes, validiertes XML-Format für `.ui`-Dateien.

Nicht in v0.1.0 enthalten: der Schrifteditor, der auf die Zeit nach v1 verschoben ist.

## Unterstützte Toolkits
| Back-end | Toolkit | Lizenz |
| --- | --- | --- |
| `ttkbootstrap` (Referenz) | [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) | MIT |
| `tkinter` | tkinter, aus der Python-Standardbibliothek | PSF |
| `pyside6` | [PySide6](https://pypi.org/project/PySide6/), optionales Extra `[pyside]` | LGPL-3.0 |

PyGUIbud hängt von ttkbootstrap ab. PySide6 wird nie mitgeliefert: Es wird nur dann aus Ihrer
Umgebung importiert, wenn Sie das Extra installieren. Dank an die Autoren aller drei.

## Sprachen
Der Designer ist auf Britisch-Englisch, Spanisch (Spanien), Portugiesisch (Portugal und Brasilien),
Deutsch, Italienisch, Niederländisch und Französisch verfügbar, mit Live-Sprachumschaltung.

## Plugins
Widgets lassen sich über den Entry-Point `pyguibud.widgets` hinzufügen, und ein abstürzendes Plugin erscheint als
Platzhalter, statt den Designer mitzureißen. Siehe das
[Beispiel-Plugin](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/tree/master/examples/acme_plugin)
und
[ADR-004](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/adr/ADR-004-widget-plugins.md).

## Projekt
- Quellcode und Issues: <https://github.com/larrezze-dev/PyGUIbud_CLAUDE>
- Änderungen: [CHANGELOG.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CHANGELOG.md)
- Mitwirken: [CONTRIBUTING.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CONTRIBUTING.md)
  und den
  [Verhaltenskodex](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CODE_OF_CONDUCT.md)
- Lizenz: MIT, siehe [LICENSE](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/LICENSE).
  Der Name, das Logo und die SAPÉ-Markenressourcen fallen nicht darunter; siehe
  [NOTICE.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/NOTICE.md).

Erstellt von Luciano Arrezze und programmiert mit Unterstützung von Claude Code.
