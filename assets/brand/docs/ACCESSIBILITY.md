---
title: SAPE Accessibility
version: 0.1.1
status: DRAFT - READY FOR HUMAN APPROVAL
date: 2026-07-24
---

# Accessibility

Objetivo minimo: WCAG 2.2 AA.

## Umbrales

| Uso | Umbral |
| --- | ---: |
| Texto normal | 4.5:1 |
| Texto grande | 3.0:1 |
| Componentes e indicadores graficos funcionales | 3.0:1 |
| Bordes decorativos | NOT APPLICABLE con justificacion |

## Bordes

- `color.border.control`, `color.border.base`, `focus`, `selected`, `error`, `warning` y `success` se validan como contraste no textual.
- `color.border.subtle = #CFD3D8` se permite solo para divisores o bordes decorativos que no sean la unica senal de un control.
- El fallo original `#CFD3D8` sobre `#F8FAFC` queda cerrado porque `base` ya no apunta a ese valor; se clasifica como `NOT APPLICABLE` cuando el uso es decorativo.
- Disabled puede tener menor contraste si el estado se comunica tambien por atributo, opacidad, texto y no disponibilidad.

## Reglas adicionales

- Navegacion por teclado completa y foco visible.
- No depender exclusivamente del color; usar texto, icono o patron.
- Respetar `prefers-reduced-motion`.
- Mantener 44 px de area tactil minima.
- En tablas densas, usar pesos, alineacion, separadores y etiquetas, no solo color.

La matriz vigente esta en `../validation/contrast-matrix.md` y sustituye cualquier conteo anterior.
