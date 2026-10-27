# PyGUIbud

[English](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/README.md) ·
[Español](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.es-ES.md) ·
[Português (Portugal)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-PT.md) ·
[Português (Brasil)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-BR.md) ·
[Deutsch](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.de-DE.md) ·
[Italiano](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.it-IT.md) ·
[Nederlands](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.nl-NL.md) ·
[Français](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.fr-FR.md)

Un concepteur d'interfaces graphiques par glisser-déposer pour **ttkbootstrap** (avec des back-ends
tkinter et PySide6) qui enregistre des fichiers `.ui` portables. Chargez un fichier `.ui` à
l'exécution avec `pyguibud-runtime`, ou transformez-le en simple module Python avec `pyguibud-uic`.

<!-- demo GIF (Step 21b): drag → save → run -->

## Installation
Python 3.10–3.13. Sous Linux, installez d'abord Tk (`sudo apt install python3-tk`).

```bash
pip install pyguibud          # pip
uv tool install pyguibud      # uv: les commandes pyguibud et pyguibud-uic
uvx pyguibud                  # uv: lancer le concepteur sans l'installer
```

Ajoutez l'extra `[pyside]` (`pip install "pyguibud[pyside]"`) pour le back-end PySide6. Consultez le
[guide d'installation complet](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/install.md).

## Démarrage rapide
```bash
pyguibud                                 # ouvrir le concepteur
pyguibud-uic --check form.ui             # valider un fichier .ui
pyguibud-uic form.ui                     # générer le module Python form_ui.py
pyguibud-uic form.ui -o my_form.py       # ... ou choisir le nom de sortie avec -o
pyguibud-uic --extract form.ui -o form.pot   # extraire les chaînes pour les traducteurs
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
localedir=None, translator=None)` accepte `backend="ttkbootstrap"` (la référence),
`"tkinter"` ou `"pyside6"`. Le code généré par `pyguibud-uic` n'importe pas PyGUIbud.
Les applications qui se contentent de charger des fichiers `.ui` n'ont besoin que de
[`pyguibud-runtime`](https://pypi.org/project/pyguibud-runtime/).

## Fonctionnalités
- Glissez des widgets depuis une palette vers une zone de dessin ; déplacez-les, redimensionnez-les
  et changez leur parent à cet endroit ou dans l'arborescence des objets. Sélection multiple,
  copier/coller (y compris entre fichiers), annuler/rétablir pour chaque modification.
- Inspecteur de propriétés avec éditeurs typés, édition des dispositions grid et pack, éditeur de
  menus, gestionnaires d'événements et variables liées aux widgets.
- Fenêtres principales, boîtes de dialogue et composants réutilisables (`<include>`), avec des
  modèles pour les nouveaux fichiers.
- Aperçu en direct dans un processus séparé, avec changement de thème et de langue à la volée, ainsi
  qu'une pseudo-locale (`en_XA`) pour vérifier l'expansion du texte.
- Utilisation entièrement au clavier, enregistrement automatique avec récupération après un
  plantage et protection contre les modifications non enregistrées.
- Les actions non valides sont bloquées avec un motif traduit au lieu d'être appliquées en silence.
- L'enregistrement est atomique et conserve une sauvegarde. Les fichiers corrompus, trop volumineux
  ou d'un schéma plus récent sont refusés. Un fichier `.ui` ne contient aucun code ; seuls les
  plugins de widgets que vous avez installés sont exécutés.
- Un format XML `.ui` versionné et validé.

Absent de la v0.1.0 : l'éditeur de polices, reporté à après la v1.

## Toolkits pris en charge
| Back-end | Toolkit | Licence |
| --- | --- | --- |
| `ttkbootstrap` (référence) | [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) | MIT |
| `tkinter` | tkinter, de la bibliothèque standard de Python | PSF |
| `pyside6` | [PySide6](https://pypi.org/project/PySide6/), extra optionnel `[pyside]` | LGPL-3.0 |

PyGUIbud dépend de ttkbootstrap. PySide6 n'est jamais inclus : il est importé depuis votre
environnement uniquement si vous installez l'extra. Merci aux auteurs des trois.

## Langues
Le concepteur est disponible en anglais britannique, espagnol (Espagne), portugais (Portugal et Brésil),
allemand, italien, néerlandais et français, avec changement de langue à la volée.

## Plugins
Des widgets peuvent être ajoutés via le point d'entrée `pyguibud.widgets`, et un plugin qui plante s'affiche comme
espace réservé au lieu de faire tomber le concepteur. Consultez le
[plugin d'exemple](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/tree/master/examples/acme_plugin)
et l'
[ADR-004](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/adr/ADR-004-widget-plugins.md).

## Projet
- Code source et tickets : <https://github.com/larrezze-dev/PyGUIbud_CLAUDE>
- Modifications : [CHANGELOG.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CHANGELOG.md)
- Contribuer : [CONTRIBUTING.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CONTRIBUTING.md)
  et le
  [Code de conduite](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CODE_OF_CONDUCT.md)
- Licence : MIT, voir [LICENSE](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/LICENSE).
  Le nom, le logo et les ressources de marque SAPÉ n'en relèvent pas ; voir
  [NOTICE.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/NOTICE.md).

Créé par Luciano Arrezze et programmé avec le soutien de Claude Code.
