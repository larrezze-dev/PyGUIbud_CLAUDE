# Show HN

**DRAFT — not posted.**

## Rules found

Sources: <https://news.ycombinator.com/showhn.html> and
<https://news.ycombinator.com/newsguidelines.html> (checked 2026-10-27).

- Show HN is for something you made that people can try. Software must be runnable, with easy
  access (ideally no signup). Early and unpolished is acceptable. You must be available to discuss
  it. Not eligible: landing pages, sign-up pages, blog posts, and minor releases of existing
  projects. This is a first release, so it qualifies.
- Title starts with "Show HN". Do not ask friends to upvote or comment.
- Titles: no attention-grabbing tactics, no uppercase shouting or exclamation marks, no editorialising.
- Promotion: HN should not be used primarily for promotion. Posting your own work some of the time
  is acceptable.
- **AI text: the guidelines say not to put generated or AI-edited text in submissions or comments
  and to write your own.** Because of this, the first comment below is an outline of facts, not
  finished prose. Write it again in your own words before you post, and say plainly that the
  project was built with the support of Claude Code.

## Title (63 characters, hand-counted; limit 80)

```text
Show HN: PyGUIbud - drag-and-drop GUI designer for ttkbootstrap
```

## URL

```text
https://github.com/larrezze-dev/PyGUIbud_CLAUDE
```

(Alternative: https://pypi.org/project/pyguibud/ . The repository is better: it has the README,
the GIF and the issue tracker.)

## First comment: outline to rewrite in your own words

Points to cover, in this order, in plain sentences:

1. What it is: a drag-and-drop designer for ttkbootstrap that saves versioned `.ui` XML files.
   You load them at run time with `pyguibud-runtime`, or generate a plain Python module with
   `pyguibud-uic` (the generated code does not import PyGUIbud). Back-ends: ttkbootstrap,
   tkinter and PySide6 (optional extra).
2. Why you made it (your own reason: I have not written one because I do not know it).
3. How to try it: `pip install pyguibud` (Python 3.10-3.13; install `python3-tk` on Linux), or
   `uvx pyguibud` to run it without installing. No signup, MIT licence.
4. Honest limits: this is 0.1.0. The font editor is not in this release. GUI tests on Linux and
   macOS CI do not block merges.
5. How it was built: created by you and programmed with the support of Claude Code.
6. Thanks to the authors of ttkbootstrap, tkinter and PySide6.
7. What feedback you want (for example: which widgets are missing; where the designer gets in the
   way).

Draft wording you can adapt, kept deliberately plain:

> Hi, I'm the author. PyGUIbud is a drag-and-drop designer for ttkbootstrap. It saves a versioned
> XML `.ui` file; you either load it at run time or generate a plain Python module that does not
> import PyGUIbud. There are tkinter and PySide6 back-ends as well.
>
> Try it with `pip install pyguibud` or `uvx pyguibud`. It is MIT licensed, no signup.
>
> It is a first release. The font editor is missing, and I would like to hear which widgets or
> workflows you miss. I wrote it with the support of Claude Code. Thanks to the authors of
> ttkbootstrap, tkinter and PySide6, which it builds on.

## Notes

- Post on a weekday and stay available. Answer questions and criticism factually; do not argue.
- Do not mention this draft or ask anyone to upvote.
- Re-read the guidelines on the day. HN's rules about AI text are strict.

Created by Luciano Arrezze and programmed with the support of Claude Code.
