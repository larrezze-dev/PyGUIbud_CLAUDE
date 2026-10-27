# PyGUIbud

[English](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/README.md) ·
[Español](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.es-ES.md) ·
[Português (Portugal)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-PT.md) ·
[Português (Brasil)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-BR.md) ·
[Deutsch](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.de-DE.md) ·
[Italiano](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.it-IT.md) ·
[Nederlands](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.nl-NL.md) ·
[Français](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.fr-FR.md)

Un diseñador de GUI de arrastrar y soltar para **ttkbootstrap** (con back-ends de tkinter y PySide6)
que guarda archivos `.ui` portables. Carga un archivo `.ui` en tiempo de ejecución con
`pyguibud-runtime`, o conviértelo en un módulo de Python normal con `pyguibud-uic`.

![Demostración: se arrastran una etiqueta y un botón desde la paleta a una nueva ventana principal, el botón recibe un texto y el manejador on_hello, el formulario se guarda como hello.ui y se ejecuta, y al pulsar el botón cambia la etiqueta](https://raw.githubusercontent.com/larrezze-dev/PyGUIbud_CLAUDE/master/docs/images/demo.gif)

## Instalación
Python 3.10–3.13. En Linux, instala antes Tk (`sudo apt install python3-tk`).

```bash
pip install pyguibud          # pip
uv tool install pyguibud      # uv: los comandos pyguibud y pyguibud-uic
uvx pyguibud                  # uv: ejecuta el diseñador sin instalarlo
```

Añade el extra `[pyside]` (`pip install "pyguibud[pyside]"`) para el back-end de PySide6. Consulta la
[guía de instalación completa](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/install.md).

## Inicio rápido
```bash
pyguibud                                 # abre el diseñador
pyguibud-uic --check form.ui             # valida un archivo .ui
pyguibud-uic form.ui                     # genera el módulo de Python form_ui.py
pyguibud-uic form.ui -o my_form.py       # ... o elige el nombre de salida con -o
pyguibud-uic --extract form.ui -o form.pot   # extrae las cadenas para los traductores
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
localedir=None, translator=None)` acepta `backend="ttkbootstrap"` (la referencia),
`"tkinter"` o `"pyside6"`. El código generado por `pyguibud-uic` no importa PyGUIbud.
Las aplicaciones que solo cargan archivos `.ui` necesitan únicamente
[`pyguibud-runtime`](https://pypi.org/project/pyguibud-runtime/).

## Características
- Arrastra widgets desde una paleta hasta un lienzo; muévelos, redimensiónalos y cámbialos de padre
  allí o en el árbol de objetos. Selección múltiple, copiar/pegar (también entre archivos) y
  deshacer/rehacer para cada cambio.
- Inspector de propiedades con editores tipados, edición de disposiciones grid y pack, editor de
  menús, manejadores de eventos y variables enlazadas a widgets.
- Ventanas principales, cuadros de diálogo y componentes reutilizables (`<include>`), con plantillas
  para los archivos nuevos.
- Vista previa en directo en un proceso aparte, con cambio de tema e idioma al vuelo, además de una
  pseudo-configuración regional (`en_XA`) para comprobar la expansión del texto.
- Uso exclusivo con teclado, guardado automático con recuperación tras fallos y protección frente a
  cambios sin guardar.
- Las acciones no válidas se bloquean con un motivo traducido en lugar de aplicarse sin avisar.
- El guardado es atómico y conserva una copia de seguridad. Se rechazan los archivos corruptos, de
  tamaño excesivo o con un esquema más reciente. Un archivo `.ui` no contiene código; solo se
  ejecutan los plugins de widgets que hayas instalado.
- Un formato XML `.ui` versionado y validado.

No incluido en la v0.1.0: el editor de fuentes, que se aplaza hasta después de la v1.

## Toolkits compatibles
| Back-end | Toolkit | Licencia |
| --- | --- | --- |
| `ttkbootstrap` (referencia) | [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) | MIT |
| `tkinter` | tkinter, de la biblioteca estándar de Python | PSF |
| `pyside6` | [PySide6](https://pypi.org/project/PySide6/), extra opcional `[pyside]` | LGPL-3.0 |

PyGUIbud depende de ttkbootstrap. PySide6 nunca se incluye: se importa desde tu entorno
solo si instalas el extra. Gracias a los autores de los tres.

## Idiomas
El diseñador está disponible en inglés británico, español (España), portugués (Portugal y Brasil),
alemán, italiano, neerlandés y francés, con cambio de idioma al vuelo.

## Plugins
Se pueden añadir widgets mediante el punto de entrada `pyguibud.widgets`, y un plugin que falla se muestra como
marcador de posición en lugar de tumbar el diseñador. Consulta el
[plugin de ejemplo](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/tree/master/examples/acme_plugin)
y
[ADR-004](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/adr/ADR-004-widget-plugins.md).

## Proyecto
- Código fuente e incidencias: <https://github.com/larrezze-dev/PyGUIbud_CLAUDE>
- Cambios: [CHANGELOG.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CHANGELOG.md)
- Cómo contribuir: [CONTRIBUTING.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CONTRIBUTING.md)
  y el
  [Código de conducta](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CODE_OF_CONDUCT.md)
- Licencia: MIT, consulta [LICENSE](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/LICENSE).
  El nombre, el logotipo y los recursos de marca de SAPÉ no están cubiertos por ella; consulta
  [NOTICE.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/NOTICE.md).

Creado por Luciano Arrezze y programado con el soporte de Claude Code.
