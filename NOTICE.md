# Notice

PyGUIbud source code is released under the [MIT Licence](./LICENSE). The following are **not** covered by the MIT Licence.

## 1. Name and logo
"PyGUIbud" and its logo identify the official project. The MIT Licence grants rights to the code, not to the name.
- Forks are welcome. You may say your fork is "based on PyGUIbud".
- You may **not** distribute a fork, package or service *as* "PyGUIbud" (or a confusingly similar name) without written consent from the project creator. Rename your fork, its PyPI distribution and its entry-point namespaces.

## 2. SAPÉ brand assets (`assets/brand/`)
The logos, design tokens and brand guidelines in `assets/brand/` belong to the SAPÉ corporate identity and are included only to theme the official designer.
- They are **all rights reserved** and are not licensed under MIT.
- Forks must replace them with their own assets.
- This includes `src/pyguibud/designer/themes/sape.json`, which is generated from these tokens by `tools/gen_themes.py` and ships in the `pyguibud` wheel and sdist. Forks delete it; the designer then falls back to its built-in MIT neutral themes.
- It also includes the application icon `src/pyguibud/designer/themes/pyguibud.png`, a copy of `assets/brand/logo/pyguibud.png` made by the same tool, shipped in the wheel and sdist. Forks delete it; the designer windows then show ttkbootstrap's default icon. Applications you build with PyGUIbud never receive this icon.
- Fonts referenced by the brand (IBM Plex Sans, Inter, JetBrains Mono, Chakra Petch) are under the SIL Open Font Licence 1.1. Font files are not bundled.

## 3. Your files
`.ui` files you create, and `.py` files generated from them by `pyguibud-uic`, belong to you. You may license them however you like.

## 4. Third-party toolkits
PySide6 (LGPL-3.0) is an optional extra. It is imported dynamically from the user's environment and is not bundled. ttkbootstrap is MIT; tkinter is part of the Python standard library (PSF licence).
