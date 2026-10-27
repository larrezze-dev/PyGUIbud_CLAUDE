# PyGUIbud

[English](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/README.md) ·
[Español](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.es-ES.md) ·
[Português (Portugal)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-PT.md) ·
[Português (Brasil)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-BR.md) ·
[Deutsch](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.de-DE.md) ·
[Italiano](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.it-IT.md) ·
[Nederlands](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.nl-NL.md) ·
[Français](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.fr-FR.md)

Een drag-and-drop-GUI-ontwerper voor **ttkbootstrap** (met tkinter- en PySide6-back-ends) die
draagbare `.ui`-bestanden opslaat. Laad een `.ui`-bestand tijdens de uitvoering met
`pyguibud-runtime`, of zet het met `pyguibud-uic` om in een gewone Python-module.

<!-- demo GIF (Step 21b): drag → save → run -->

## Installatie
Python 3.10–3.13. Installeer onder Linux eerst Tk (`sudo apt install python3-tk`).

```bash
pip install pyguibud          # pip
uv tool install pyguibud      # uv: de opdrachten pyguibud en pyguibud-uic
uvx pyguibud                  # uv: de ontwerper uitvoeren zonder te installeren
```

Voeg de extra `[pyside]` toe (`pip install "pyguibud[pyside]"`) voor de PySide6-back-end. Zie de
[volledige installatiehandleiding](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/install.md).

## Snelstart
```bash
pyguibud                                 # de ontwerper openen
pyguibud-uic --check form.ui             # een .ui-bestand valideren
pyguibud-uic form.ui                     # de Python-module form_ui.py genereren
pyguibud-uic form.ui -o my_form.py       # ... of kies de uitvoernaam met -o
pyguibud-uic --extract form.ui -o form.pot   # de teksten voor vertalers extraheren
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
localedir=None, translator=None)` accepteert `backend="ttkbootstrap"` (de referentie),
`"tkinter"` of `"pyside6"`. Code die door `pyguibud-uic` is gegenereerd, importeert PyGUIbud niet.
Toepassingen die alleen `.ui`-bestanden laden, hebben slechts
[`pyguibud-runtime`](https://pypi.org/project/pyguibud-runtime/).

## Functies
- Sleep widgets vanuit een palet naar een tekenvlak; verplaats ze, wijzig hun grootte en hang ze
  aan een andere ouder, daar of in de objectboom. Meervoudige selectie, kopiëren/plakken (ook
  tussen bestanden), ongedaan maken/opnieuw uitvoeren voor elke wijziging.
- Eigenschappeninspecteur met getypeerde editors, bewerking van grid- en pack-indelingen,
  menu-editor, gebeurtenishandlers en variabelen die aan widgets gebonden zijn.
- Hoofdvensters, dialoogvensters en herbruikbare componenten (`<include>`), met sjablonen voor
  nieuwe bestanden.
- Livevoorbeeld in een apart proces, met live wisselen van thema en taal, plus een pseudo-locale
  (`en_XA`) om de uitzetting van tekst te controleren.
- Bediening met alleen het toetsenbord, automatisch opslaan met herstel na een crash en een
  beveiliging tegen niet-opgeslagen wijzigingen.
- Ongeldige acties worden geblokkeerd met een vertaalde reden in plaats van stilzwijgend
  uitgevoerd.
- Opslaan is atomair en bewaart een back-up. Beschadigde, te grote of met een nieuwer schema
  gemaakte bestanden worden geweigerd. Een `.ui`-bestand bevat geen code; alleen de widget-plug-ins
  die u hebt geïnstalleerd, worden uitgevoerd.
- Een geversioneerd, gevalideerd XML-formaat voor `.ui`-bestanden.

Niet in v0.1.0: de lettertype-editor, die is uitgesteld tot na v1.

## Ondersteunde toolkits
| Back-end | Toolkit | Licentie |
| --- | --- | --- |
| `ttkbootstrap` (referentie) | [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) | MIT |
| `tkinter` | tkinter, uit de standaardbibliotheek van Python | PSF |
| `pyside6` | [PySide6](https://pypi.org/project/PySide6/), optionele extra `[pyside]` | LGPL-3.0 |

PyGUIbud is afhankelijk van ttkbootstrap. PySide6 wordt nooit meegeleverd: het wordt alleen uit uw
omgeving geïmporteerd als u de extra installeert. Dank aan de auteurs van alle drie.

## Talen
De ontwerper is beschikbaar in Brits Engels, Spaans (Spanje), Portugees (Portugal en Brazilië),
Duits, Italiaans, Nederlands en Frans, met live wisselen van taal.

## Plug-ins
Widgets kunnen worden toegevoegd via het entry point `pyguibud.widgets`, en een plug-in die crasht, verschijnt als
plaatsaanduiding in plaats van de ontwerper neer te halen. Zie de
[voorbeeldplug-in](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/tree/master/examples/acme_plugin)
en
[ADR-004](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/adr/ADR-004-widget-plugins.md).

## Project
- Broncode en issues: <https://github.com/larrezze-dev/PyGUIbud_CLAUDE>
- Wijzigingen: [CHANGELOG.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CHANGELOG.md)
- Bijdragen: [CONTRIBUTING.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CONTRIBUTING.md)
  en de
  [Gedragscode](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CODE_OF_CONDUCT.md)
- Licentie: MIT, zie [LICENSE](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/LICENSE).
  De naam, het logo en de SAPÉ-merkmiddelen vallen er niet onder; zie
  [NOTICE.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/NOTICE.md).

Gemaakt door Luciano Arrezze en geprogrammeerd met de ondersteuning van Claude Code.
