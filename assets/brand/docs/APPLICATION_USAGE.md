---
title: SAPE Application Usage
version: 0.1.1
status: DRAFT - READY FOR HUMAN APPROVAL
date: 2026-07-24
---

# Application Usage

Shell estandar: navegacion lateral 240 px, header 56 px, workspace flexible y panel lateral opcional. Formularios con controles de 40 px, labels 14 px medium y foco visible 2 px. Tablas usan 12-14 px, cifras monoespaciadas y estados con icono o texto.

## ERP y controles densos

- Campos de datos, filtros, combos y busquedas usan `color.border.control`.
- `color.border.base` se admite por compatibilidad y resuelve al mismo valor funcional.
- Divisores entre grupos, filas no interactivas y bordes de panel no esenciales usan `color.border.subtle`.
- Error, warning, success y selected usan tokens de estado y no dependen solo del color.
- Disabled combina `color.border.disabled`, opacidad, atributo disabled y texto/estado no interactivo.

Aplicaciones ERP deben favorecer densidad, consistencia y repeticion eficiente por encima de composicion editorial.
