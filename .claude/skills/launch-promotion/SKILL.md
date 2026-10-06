---
name: launch-promotion
description: How PyGUIbud's promoter (LAME-CULOS) prepares the README, release notes, docs site and announcements for the public launch, with mandatory user approval. Use when preparing public-facing texts or launch material.
---

# Launch and promotion

## Deliverables (drafts in `docs/launch/`)
- `README.md`: one-line pitch, a GIF of drag → save → run, install (`pip install pyguibud`, `uv tool install pyguibud`, `uvx pyguibud`), 30-second quick start (`load_ui` and `pyguibud-uic`), features, supported toolkits, languages, plugin pointer, licence/NOTICE, links to CONTRIBUTING/CoC. Language links to translated READMEs (es-ES, pt-PT, pt-BR, de-DE, it-IT, nl-NL, fr-FR).
- Release notes (Keep a Changelog style) → `CHANGELOG.md`.
- Announcement drafts per channel: GitHub Release, Python Discourse "Show & tell", Reddit r/Python, Mastodon/Bluesky/X, LinkedIn, Hacker News "Show HN". Respect each channel's self-promotion rules and length limits.
- Short demo script for GIFs/video; alt text for every image.

## Tone
Honest, concrete and humble. Show, don't hype. No unverifiable claims ("fastest", "best"), no fake metrics or testimonials. Credit ttkbootstrap, tkinter and PySide6 and their licences. Use en-GB for the source text.

## Hard limits
- **Nothing is published, posted, emailed or submitted by an agent.** Drafts only. The user approves every text, then publishes it personally.
- Don't impersonate anyone or post as the user. Don't use the SAPÉ brand beyond what NOTICE.md allows.
- Check that every link and install command works before handing over.
