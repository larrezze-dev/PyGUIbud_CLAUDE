---
title: SAPÉ Design System
version: 0.1.0
status: COMPLETED WITH OBSERVATIONS
date: 2026-07-24
---
# Typography System

| Rol | Familia | Licencia | Fuente oficial | Uso |
| --- | --- | --- | --- | --- |
| Primaria | IBM Plex Sans | SIL Open Font License 1.1 | https://github.com/IBM/plex | UI, web, documentos e informes |
| Secundaria | Inter | SIL Open Font License 1.1 | https://github.com/rsms/inter | Producto digital cuando se requiera una textura mas neutra |
| Monoespaciada | JetBrains Mono | SIL Open Font License 1.1 | https://github.com/JetBrains/JetBrainsMono | Codigo, datos tecnicos y tablas densas |
| Dependencia de logo | Chakra Petch | Google Fonts / OFL | https://fonts.google.com/specimen/Chakra+Petch | Solo lectura: aparece en SVG horizontales aprobados |

## Reglas de uso

IBM Plex Sans es la familia normativa. Inter puede usarse como alternativa digital si una plataforma ya la incluye o si se busca una textura UI más neutral. JetBrains Mono queda reservado para código, identificadores, logs, tablas con cifras y documentación técnica.

No se incluyen archivos `.ttf`, `.otf`, `.woff` ni `.woff2`. La obtención de fuentes debe realizarse desde las fuentes oficiales documentadas y con revisión de licencia del proyecto consumidor.

## Pesos

- Regular 400: cuerpo, tablas y documentación.
- Medium 500: labels, navegación y controles.
- Semibold 600: títulos, encabezados de tarjetas y énfasis.
- Bold 700: uso excepcional en jerarquía máxima.

## Fallbacks

Windows: `Segoe UI`, `Aptos`, `Arial`. macOS: `SF Pro`, `Helvetica Neue`. Linux: `Noto Sans`, `Liberation Sans`. Monoespaciado: `Consolas`, `SFMono-Regular`, `Menlo`, `monospace`.
