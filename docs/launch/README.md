# Launch drafts for PyGUIbud v0.1.0

**DRAFT — not posted.** Nothing in this folder has been published, posted or submitted. The
author reviews every text and posts it personally.

Source of truth: `README.md` and `CHANGELOG.md` (section 0.1.0). No draft claims anything beyond
them. Rules below were checked on 2026-10-27; re-read each channel's rules on the day of posting.

## Index

| Channel | File | Limits and rules (source) | When to post | Status |
| --- | --- | --- | --- | --- |
| GitHub Release `v0.1.0` | [github-release.md](github-release.md) | Markdown body; the GIF needs the `?raw=true` URL form to render | Right after the tag publishes to PyPI | draft |
| Python Discourse | [python-discourse.md](python-discourse.md) | No project-announcement category exists; moderators declined one; self-promotion removed; AI-generated posts banned. **Recommendation: do not post.** | Not applicable | draft (recommend skipping) |
| Reddit r/Python | [reddit-python.md](reddit-python.md) | "Showcase" flair and the three template sections; live rules could not be fetched, so check the sidebar | Day 1 or 2, weekday, once the GIF renders | draft |
| Hacker News | [show-hn.md](show-hn.md) | Title starts "Show HN: "; must be tryable; no upvote requests; **no AI-generated or AI-edited comments** | After the release is stable; weekday | draft |
| LinkedIn, Mastodon, Bluesky, X | [social.md](social.md) | 1300 / 500 / 300 / 280 characters | Day 1, after the GitHub Release | draft |
| Demo video and GIF alt text | [demo-script.md](demo-script.md) | 60-90 s; alt text in en-GB | Before any post that embeds the GIF | draft |

Suggested order: GitHub Release first (the other posts link to it), then social, then r/Python,
then Show HN on a different day so you can answer comments promptly. Be present for the first
hours after each post.

## Pre-post checklist

Tick every box before posting anything.

- [ ] The Step 21a PR is merged into `master`: the README, `CHANGELOG.md`, `docs/readme/` and
  `docs/install.md` links used in the drafts only exist on `master` after that merge. (The public
  page was still showing the 0.1.0rc1 README when these drafts were written.)
- [ ] `CHANGELOG.md`: `## [0.1.0] - Unreleased` is changed to the real release date.
- [ ] `pyguibud` 0.1.0 and `pyguibud-runtime` 0.1.0 are live on PyPI (not only TestPyPI).
- [ ] In a clean virtual environment, `pip install pyguibud` installs 0.1.0 and `pyguibud` starts.
- [ ] Also checked: `uv tool install pyguibud` and `uvx pyguibud`.
- [ ] Every link in the drafts returns HTTP 200 (open each in a private window):
  - https://github.com/larrezze-dev/PyGUIbud_CLAUDE
  - https://pypi.org/project/pyguibud/
  - https://pypi.org/project/pyguibud-runtime/
  - https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CHANGELOG.md
  - https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/install.md
  - the seven translated READMEs under `docs/readme/`
  - https://github.com/larrezze-dev/PyGUIbud_CLAUDE/releases/tag/v0.1.0
- [ ] The GIF renders: `docs/images/demo.gif` is on `master`, and the `?raw=true` URL shows the
  animation in a private window and inside the GitHub Release preview.
- [ ] The README placeholder comment `<!-- demo GIF (Step 21b) -->` has been replaced by the image
  (the drafts assume it is).
- [ ] Every claim in the post you are about to send matches the README and CHANGELOG.
- [ ] Each text is read and, where the channel requires it, rewritten in your own words (see the
  AI-use rules in the table above and in each file).
- [ ] You can answer comments and issues for the next few hours.

## AI-use disclosure, per channel

| Channel | Rule found | What the draft does |
| --- | --- | --- |
| GitHub | None | Credit line in the body |
| Python Discourse | Forum guidelines: AI-generated posts are removed; disclosing does not exempt them | Do not post, or write your own text |
| r/Python | Not verifiable (page not fetchable) | Discloses in the post; check the sidebar |
| Hacker News | Guidelines: do not post generated or AI-edited text, submissions or comments | The comment is an outline of facts only. Write it yourself |
| LinkedIn, Mastodon, Bluesky, X | No specific rule checked | Disclosure included, or in a reply where space is short |

Created by Luciano Arrezze and programmed with the support of Claude Code.
