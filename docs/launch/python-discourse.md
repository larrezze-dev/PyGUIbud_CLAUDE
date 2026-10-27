# Python Discourse (discuss.python.org)

**DRAFT — not posted.**

## Finding: there is no suitable category, and the recommendation is not to post

- Category: **none**. The category list has no "Show and tell" or general project-announcement
  category. Source: <https://discuss.python.org/categories> (checked 2026-10-27).
- The existing **Announcements** category is for "releases for major projects (mainly pip releases
  and PyPI feature deployments)" and "one-off announcements for new projects/tools directly
  related to packaging". PyGUIbud is a GUI designer, not a packaging tool, so it does not fit.
  Source: <https://discuss.python.org/t/about-the-announcements-category/42395>.
- A request for a general project-announcement channel was **declined** by the moderators in May
  2025: "the forum is not supposed to serve as an advertising channel" and a section for
  announcements "would invite low-quality postings". Source:
  <https://discuss.python.org/t/can-we-have-a-project-announcement-channel/68899>.
- Forum guidelines: obvious self-promotion is removed "with extreme prejudice", and AI-generated
  posts are removed even when disclosed. Source: <https://discuss.python.org/guidelines>.

Conclusion: a "Show and tell" post here would very probably be removed and could count against
your account. Skip this channel. Do not start a topic in Python Help or Ideas just to announce.

## Alternative (rules not fully verified)

The moderated `python-announce-list` mailing list is the python.org venue for announcing new
modules and programs. Its page says submissions follow the comp.lang.python.announce posting
guidelines; I could not read those guidelines, so check them before sending. Source:
<https://www.python.org/community/lists/>. A short plain-text announcement, written by you, would be:

```text
Subject: ANN: PyGUIbud 0.1.0 - drag-and-drop GUI designer for ttkbootstrap

PyGUIbud 0.1.0 is the first public release of a drag-and-drop GUI designer
for ttkbootstrap, with tkinter and PySide6 (optional extra) back-ends.
It saves portable, versioned .ui XML files. Load one at run time with
pyguibud-runtime, or generate a plain Python module with pyguibud-uic.

Install:  pip install pyguibud     (Python 3.10-3.13)
Source:   https://github.com/larrezze-dev/PyGUIbud_CLAUDE
PyPI:     https://pypi.org/project/pyguibud/
Licence:  MIT

Not in 0.1.0: the font editor (deferred until after v1).

I built it with the support of Claude Code. Feedback and issues are welcome.

Luciano Arrezze
```

## Uncertain

- Whether python-announce accepts this kind of announcement from an unknown author, and its AI-use
  stance: not checked.

Created by Luciano Arrezze and programmed with the support of Claude Code.
