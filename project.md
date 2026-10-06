# PyGUIbud — Project Concept

> Drag-and-drop GUI designer for Python. Design once, save a `.ui` file, then **load it at runtime** or **export plain `.py`**.
> Backends: **ttkbootstrap** · tkinter · PySide6 · Languages: en-GB (source) + es-ES, pt-PT, pt-BR, de-DE, it-IT, nl-NL, fr-FR · Licence: **MIT** (+ [NOTICE](./NOTICE.md))
> v1 features: **[FEATURES.md](./FEATURES.md)** · ADRs: `docs/adr/`
> Full proposal (stack, licence, agents, steps, UAT): **[DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)**

## Scope

| In scope (v1) | Out of scope (v1) |
| --- | --- |
| Visual editor: palette, canvas, inspector, object tree | Full IDE / code editor |
| `.ui` XML file (versioned schema, translatable strings) | Binary/proprietary formats |
| Runtime loader `load_ui()`; code generator `pyguibud-uic` → standalone `.py` | Round-trip parsing of hand-edited `.py` |
| Backend plugins: ttkbootstrap, tkinter, PySide6 | Kivy, wx, Dear PyGui (welcome as community plugins/forks) |
| Multilingual designer **and** multilingual generated GUIs | Right-to-left scripts (later) |
| Idiot-proof editing: invalid actions are blocked | |

## 1. Architecture
```mermaid
flowchart LR
  subgraph Designer["pyguibud (designer app)"]
    UI[ttkbootstrap shell<br/>palette · canvas · inspector · tree]
    CMD[Command stack<br/>undo/redo + guards]
    I18N[i18n<br/>gettext + Babel<br/>8 locales]
  end
  subgraph Core["pyguibud.core (toolkit-agnostic)"]
    M[Widget model]
    V[Validator]
    IO[.ui XML I/O]
  end
  subgraph Plugins["Backends (entry points)"]
    B1[ttkbootstrap]
    B2[tkinter]
    B3[PySide6]
    BX[community plugin...]
  end
  I18N -.-> UI
  UI --> CMD --> M
  M <--> V
  M <--> IO
  IO --> F[(file.ui)]
  F --> RT[pyguibud-runtime<br/>load_ui]
  F --> CG[pyguibud-uic<br/>codegen + .pot extract]
  CG --> PY[(file.py)]
  RT --> Plugins
  CG --> Plugins
```

## 2. `.ui` lifecycle
```mermaid
sequenceDiagram
  actor Dev
  participant D as Designer
  participant V as Validator
  participant F as file.ui
  participant R as Runtime / UIC
  Dev->>D: drag widget, edit properties
  D->>V: proposed command
  alt invalid (e.g. child into non-container)
    V-->>D: blocked + translated reason
  else valid
    V-->>D: apply + push undo
  end
  Dev->>D: Save
  D->>F: serialise (schema_version, translatable strings)
  Dev->>R: load_ui(F, translator) / pyguibud-uic F -o app.py
  R-->>Dev: live window / standalone .py with _() calls
```

## 3. Agent orchestration and the user gate
```mermaid
flowchart TD
  U((User)) <--> O[ORCHESTRATOR]
  O --> A[SOFTWARE-ARCHITECT]
  A --> BE[BACKEND-DEV]
  A --> FE[FRONTEND-DEV<br/>+ TRANSLATOR]
  BE --> T[TESTING]
  FE --> T
  T -->|failures| DBG[DEBUGGER]
  DBG --> T
  T -->|green| QA[QA]
  QA -->|bugs| DBG
  QA -->|approved| O
  O -->|UAT instructions + commit message| U
  U -->|UAT passed + manual commit| O
  O -->|release steps| DEP[DEPLOYER]
  DEP --> LC[LAME-CULOS]
  S[SCORER] -.observes.-> T
  S -.dashboard.-> U
```

## 4. Roadmap
```mermaid
flowchart LR
  M0[M0 Foundations<br/>S01–S06] --> M1[M1 Core & runtime<br/>S07–S11] --> M2[M2 Designer<br/>S12–S15] --> M3[M3 Backends, plugins & languages<br/>S16–S18] --> M4[M4 QA hardening<br/>S19] --> M5[M5 Release<br/>S20–S21]
```

## Brand
Copied from the SAPÉ corporate identity into `assets/brand/` (tokens, SVG logos, guidelines). Primary `#1C3FF0` (hover `#122AD2`, active `#1026A6`), background `#F8FAFC`, surface `#FFFFFF`, text `#212832`, semantic error/warning/success/info sets. Fonts: IBM Plex Sans (UI) and JetBrains Mono (code), all OFL.
