# acme-pyguibud

A sample PyGUIbud widget plugin. It adds one widget, `acme:ColourSwatch` (a label with a coloured
background; fallback `Label`), to the palette under the category "Acme".

## Install

```
uv pip install -e examples/acme_plugin
```

Use `uv pip`, not `pip`: the project's virtual environment has no `pip.exe`. A later `uv sync`
removes the plugin again, so repeat the command afterwards. Then open
`examples/acme_demo.ui` in the designer (`uv run pyguibud examples/acme_demo.ui`).

## Breaking it on purpose

Set `ACME_PYGUIBUD_BREAK` before starting the designer to see how a broken plugin is isolated
(one entry in Help > Plugins, the fallback widget on the canvas, no crash):

| Value | What fails |
| --- | --- |
| `import` | the module raises while it is imported |
| `spec` | `widgets()` raises |
| `factory` | the widget factory raises when the widget is built |
| `setter` | the widget is built, then setting its text raises (the swatch needs a Text value, as in `acme_demo.ui`) |
| `exit` | the module calls `sys.exit(3)` while it is imported |

## Trust boundary

A plugin is ordinary Python code and it runs when the registry loads: when the designer starts,
when the preview process starts and when `load_ui` runs. Install only plugins you trust. Opening
a `.ui` file never imports anything: a file can only name a plugin (`plugin="acme-pyguibud"`),
and without the plugin installed the widget's fallback is shown instead. Use `pyguibud
--no-plugins` or Help > Plugins to start without third-party plugins.

## Translations

The plugin's strings use its own gettext domain, `acme_pyguibud`. Without a catalogue they stay in
British English.
