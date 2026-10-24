"""Install the built PyGUIbud distributions into clean environments and smoke-test them.

Spec packaging section 6 (shared by CI, this script and the UAT), decision D11. Usage::

    uv run python tools/verify_install.py                      # build both dists, pip + uv paths
    python tools/verify_install.py --dist dist                 # use dists that are already built
    python tools/verify_install.py --from-index testpypi --version 0.1.0rc1

Everything happens in one temporary folder outside the checkout: virtual environments, the copy
of ``examples/hello.ui`` and the checks' scratch files. Checks run with the environment's own
interpreter (by absolute path, ``-I``) and with the temporary folder as the working directory.

The subprocess environment is cleaned (no inherited ``VIRTUAL_ENV``, ``PYTHONPATH``,
``PYGUIBUD_*`` ...), and ``PYGUIBUD_CONFIG_DIR`` / ``PYGUIBUD_STATE_DIR`` always point into the
temporary folder, so that no designer started here can touch the real settings or recovery data.
The uv path keeps ``UV_TOOL_DIR`` and ``UV_TOOL_BIN_DIR`` in the temporary folder too, so
``uv tool install`` never changes the real tools or ``PATH``. ``UV_CACHE_DIR`` stays the user's:
the cache is content-addressed and shared, and it keeps a second run fast. Only the uv path can
then work offline from that cache; the pip path needs PyPI for ``ttkbootstrap`` and ``pillow``.

Prints one line per check (``PASS``/``FAIL <path> <check>``), then ``OK: ...`` or
``FAILED: n check(s)``, and exits 0 or 1. A failed check never stops the others.
Standard library only; Python 3.10+. Linux needs a display for the Tk checks (CI uses xvfb).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ABOUT = ROOT / "runtime" / "src" / "pyguibud" / "__about__.py"
EXAMPLES = ROOT / "examples"
TESTPYPI_SIMPLE = "https://test.pypi.org/simple/"
CREDIT_NAME = "Luciano Arrezze"

#: Expected German texts, held here as literals on purpose (spec section 6 check 7). They must
#: equal the de_DE msgstrs of runtime/src/pyguibud/locale/de_DE/LC_MESSAGES/pyguibud.po;
#: tests/test_verify_install_literals.py fails when a translation is reworded.
#: msgid "'{path}' has no main window; pass {argument} to load its dialogs." with
#: path="dialog.ui" and argument="master=".
GERMAN_NO_MAIN_WINDOW = (
    "'dialog.ui' enthält kein Hauptfenster; übergeben Sie master=, um seine Dialoge zu laden."
)
#: msgid "_Cancel" and msgid "_OK" (the dialog button labels the runtime owns).
GERMAN_CANCEL = "_Abbrechen"
GERMAN_OK = "_OK"

GERMAN = {"no_main_window": GERMAN_NO_MAIN_WINDOW, "cancel": GERMAN_CANCEL, "ok": GERMAN_OK}

#: A dialog-only document: ``load_ui`` without ``master=`` must refuse it before any Tk object.
DIALOG_UI = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">\n'
    '  <meta source_locale="en_GB"/>\n'
    '  <window id="dlg" kind="dialog" modal="true" buttons="ok,cancel">\n'
    '    <prop name="title" translatable="true">Dialog</prop>\n'
    '    <layout type="pack"/>\n'
    "  </window>\n"
    "</pyguibud-ui>\n"
)

#: Run inside a venv as ``python -I probe.py <check> <json parameters>``; one check per process,
#: because ttkbootstrap allows one Tk root per process. ASCII only.
PROBE = r"""
import importlib.metadata as metadata
import importlib.util
import json
import pathlib
import sys
import sysconfig


class Handlers:  # the two handlers hello.ui binds
    def on_greet(self):
        pass

    def on_quit(self):
        pass


def hello_load(params):
    from pyguibud_runtime import load_ui

    load_ui("hello.ui", Handlers()).destroy()


def generated_module(params):
    sys.path.insert(0, ".")
    import hello_ui  # noqa: F401 - generated code depends on ttkbootstrap only (ADR-003)

    leaked = sorted(k for k in sys.modules if k.startswith("pyguibud"))
    assert not leaked, "the generated code imports pyguibud: %s" % leaked


def installed_in_site_packages(params):
    import pyguibud.core
    import pyguibud.designer

    site = pathlib.Path(sysconfig.get_paths()["purelib"]).resolve()
    for module in (pyguibud.core, pyguibud.designer):
        found = pathlib.Path(module.__file__).resolve()
        assert site in found.parents, "%s is not in %s" % (found, site)


def designer_app(params):
    from ttkbootstrap import App

    from pyguibud.core import Widget
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.settings import Settings

    root = App(title="verify_install")
    root.withdraw()
    app = DesignerApp(root, settings=Settings())
    try:
        app.open_path(pathlib.Path("hello.ui"))
        root.update()
        ids = {n.id for n in app.session.document.walk() if isinstance(n, Widget)}
        assert "btn_greet" in ids, "hello.ui did not open: %s" % sorted(ids)
    finally:
        app.dispose()
        root.destroy()


def german(params):
    from pyguibud.i18n import set_language
    from pyguibud_runtime import load_ui
    from pyguibud_runtime._texts import Texts
    from pyguibud_runtime.errors import UiError

    set_language("de_DE")  # the runtime does not read PYGUIBUD_LANG
    try:
        load_ui("dialog.ui")
    except UiError as exc:
        assert str(exc) == params["no_main_window"], repr(str(exc))
    else:
        raise AssertionError("load_ui accepted a dialog-only document without master=")
    texts = Texts({}, "de_DE", None)  # the path of runtime/src/pyguibud_runtime/_texts.py
    assert texts.runtime_text("_Cancel") == params["cancel"], texts.runtime_text("_Cancel")
    assert texts.runtime_text("_OK") == params["ok"], texts.runtime_text("_OK")


def no_designer_module(params):
    assert importlib.util.find_spec("pyguibud.designer") is None


def no_designer_distribution(params):
    try:
        metadata.distribution("pyguibud")
    except metadata.PackageNotFoundError:
        return
    raise AssertionError("the distribution pyguibud is installed")


def no_scripts(params):
    found = sorted(p.name for p in pathlib.Path(sysconfig.get_path("scripts")).glob("pyguibud*"))
    assert not found, "scripts found: %s" % found


def no_toolkit_on_import(params):
    import pyguibud_runtime  # noqa: F401

    loaded = {"tkinter", "ttkbootstrap"} & set(sys.modules)
    assert not loaded, "import pyguibud_runtime loads %s" % sorted(loaded)


CHECKS = {f.__name__: f for f in (
    hello_load, generated_module, installed_in_site_packages, designer_app, german,
    no_designer_module, no_designer_distribution, no_scripts, no_toolkit_on_import,
)}
CHECKS[sys.argv[1]](json.loads(sys.argv[2]))
"""

#: Environment variables that would make a clean environment less clean.
_DROPPED = {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT", "CONDA_PREFIX"}
_TAIL = 25  # lines of output shown for a failed check
_PREFIX = "pyguibud-verify-"  # the only folders this script makes (and ever sweeps) in the temp dir
_STALE_SECONDS = 24 * 3600
MIN_PYTHON = (3, 10)


def read_version() -> str:
    """The version literal of ``runtime/src/pyguibud/__about__.py`` (read, never imported)."""
    found = re.search(r'^__version__ = "([^"]+)"\s*$', ABOUT.read_text("utf-8"), re.MULTILINE)
    if found is None:
        raise SystemExit(f"no __version__ literal in {ABOUT}")
    return found.group(1)


def default_python() -> str:
    """The interpreter that makes the venvs: the base of the running one when it is a venv."""
    if sys.prefix != sys.base_prefix:
        return getattr(sys, "_base_executable", None) or sys.executable
    return sys.executable


def clean_environment(work: Path) -> dict[str, str]:
    """The inherited environment minus anything that could leak in, plus private profile folders."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() not in _DROPPED and not key.upper().startswith("PYGUIBUD_")
    }
    env["PYGUIBUD_CONFIG_DIR"] = str(work / "profile" / "config")
    env["PYGUIBUD_STATE_DIR"] = str(work / "profile" / "state")
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def venv_script(venv: Path, name: str) -> Path:
    """Absolute path of an executable in a venv (``Scripts\\x.exe`` on Windows)."""
    if os.name == "nt":
        return venv / "Scripts" / (name + ("" if name.endswith(".exe") else ".exe"))
    return venv / "bin" / name


def bin_script(directory: Path, name: str) -> Path:
    """Absolute path of a script in a plain folder (the uv tool bin directory)."""
    return directory / (name + ".exe" if os.name == "nt" else name)


class Verifier:
    """Runs the commands and checks, and keeps the tally."""

    def __init__(self, work: Path, python: str, version: str) -> None:
        self.work = work
        self.python = python
        self.version = version
        self.env = clean_environment(work)
        self.failures = 0
        self.passes = 0
        self.dist = Path()  # set once the artefacts are known (an absolute folder)
        self.probe_file = work / "probe.py"
        self.probe_file.write_text(PROBE, encoding="utf-8")

    def run(
        self,
        command: Sequence[object],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 900,
    ) -> tuple[int, str]:
        """Run a command; returns (exit code, stdout + stderr). Never raises for a bad command."""
        try:
            done = subprocess.run(
                [str(part) for part in command],
                cwd=cwd or self.work,
                env=env or self.env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return 124, f"timed out after {exc.timeout} s"
        except OSError as exc:
            return 127, f"cannot run {command[0]}: {exc}"
        return done.returncode, (done.stdout or "") + (done.stderr or "")

    def record(self, path: str, name: str, ok: bool, detail: str = "") -> bool:
        """Print the PASS/FAIL line (and the tail of ``detail`` for a failure)."""
        print(f"{'PASS' if ok else 'FAIL'} {path} {name}", flush=True)
        if ok:
            self.passes += 1
        else:
            self.failures += 1
            lines = detail.strip().splitlines()[-_TAIL:]
            for line in lines:
                print(f"     | {line}")
        return ok

    def command(
        self,
        path: str,
        name: str,
        command: Sequence[object],
        *,
        contains: Sequence[str] = (),
        env: dict[str, str] | None = None,
        timeout: float = 900,
    ) -> bool:
        """A check that passes when the command exits 0 and prints every text of ``contains``."""
        code, output = self.run(command, env=env, timeout=timeout)
        missing = [text for text in contains if text not in output]
        detail = output if code else f"missing {missing!r} in:\n{output}"
        return self.record(path, name, code == 0 and not missing, detail)

    def probe(self, path: str, python: Path, name: str, **params: str) -> bool:
        """Run one embedded check in the environment's interpreter, isolated (``-I``)."""
        code, output = self.run(
            [python, "-I", self.probe_file, name, json.dumps(params)], timeout=300
        )
        return self.record(path, name, code == 0, output)

    def make_venv(self, path: str, venv: Path) -> Path | None:
        """Create a venv; returns its interpreter, or None after recording a failure."""
        code, output = self.run([self.python, "-m", "venv", venv])
        python = venv_script(venv, "python")
        ok = self.record(path, "create venv", code == 0 and python.exists(), output)
        return python if ok else None

    def pip_install(self, path: str, python: Path, dist: Path, requirement: str) -> bool:
        command = [python, "-m", "pip", "install", "--find-links", dist, requirement]
        return self.command(path, f"pip install {requirement}", command)

    # ------------------------------------------------------------------ the pip path
    def designer_venv(self, python: Path, venv: Path) -> None:
        path = "pip/designer"
        self.command(path, "pip check", [python, "-m", "pip", "check"])
        self.command(
            path,
            "(1) pyguibud --version",
            [venv_script(venv, "pyguibud"), "--version"],
            contains=[f"pyguibud {self.version}", CREDIT_NAME],
        )
        uic = venv_script(venv, "pyguibud-uic")
        self.command(path, "(2) pyguibud-uic --check hello.ui", [uic, "--check", "hello.ui"])
        generated = self.command(path, "(3a) pyguibud-uic hello.ui", [uic, "hello.ui"])
        if generated:
            self.probe(path, python, "generated_module")
        else:
            self.record(path, "(3b) generated_module", False, "skipped: no generated module")
        self.probe(path, python, "hello_load")  # (4)
        self.probe(path, python, "designer_app")  # (5)
        self.probe(path, python, "installed_in_site_packages")  # (6)
        self.probe(path, python, "german", **GERMAN)  # (7)

    def runtime_venv(self, python: Path) -> None:
        path = "pip/runtime-only"
        self.probe(path, python, "hello_load")  # (4)
        self.probe(path, python, "german", **GERMAN)  # (7)
        self.probe(path, python, "no_designer_module")
        self.probe(path, python, "no_designer_distribution")
        self.probe(path, python, "no_scripts")
        self.probe(path, python, "no_toolkit_on_import")

    def pip_path(self, dist: Path, index: bool) -> None:
        version = self.version
        designer = self.work / "venv-designer"
        python = self.make_venv("pip/designer", designer)
        if python is not None:
            if index:  # the pip download half of the spec section 7 recipe
                dist = self.work / "rc"
                dist.mkdir()
                code, output = self.run(
                    [
                        *(python, "-m", "pip", "download", "--no-deps", "--only-binary=:all:"),
                        *("-d", dist, "-i", TESTPYPI_SIMPLE),
                        f"pyguibud=={version}",
                        f"pyguibud-runtime=={version}",
                    ]
                )
                if not self.record("pip/designer", "download from TestPyPI", code == 0, output):
                    return
            self.dist = dist
            if self.pip_install("pip/designer", python, dist, f"pyguibud=={version}"):
                self.designer_venv(python, designer)
        runtime = self.work / "venv-runtime"
        python = self.make_venv("pip/runtime-only", runtime)
        if (
            python is not None
            and self.dist.is_absolute()
            and self.pip_install(
                "pip/runtime-only", python, self.dist, f"pyguibud-runtime=={version}"
            )
        ):
            self.runtime_venv(python)

    # ------------------------------------------------------------------ the uv path
    def uv_path(self, dist: Path) -> None:
        path = "uv"
        uv = shutil.which("uv")
        if uv is None:
            self.record(path, "uv is on PATH", False, "uv not found; install it or use --skip-uv")
            return
        env = dict(self.env)
        env["UV_TOOL_DIR"] = str(self.work / "uv" / "tools")
        env["UV_TOOL_BIN_DIR"] = str(self.work / "uv" / "bin")
        bin_dir = self.work / "uv" / "bin"
        requirement = f"pyguibud=={self.version}"
        installed = self.command(
            path,
            "uv tool install",
            [uv, "tool", "install", "--python", self.python, "--find-links", dist, requirement],
            env=env,
        )
        if installed:
            self.command(
                path,
                "tool pyguibud --version",
                [bin_script(bin_dir, "pyguibud"), "--version"],
                contains=[f"pyguibud {self.version}", CREDIT_NAME],
                env=env,
            )
            self.command(
                path,
                "tool pyguibud-uic --check hello.ui",
                [bin_script(bin_dir, "pyguibud-uic"), "--check", "hello.ui"],
                env=env,
            )
        uvx = shutil.which("uvx")
        runner = [uvx] if uvx else [uv, "tool", "run"]
        self.command(
            path,
            "uvx pyguibud-uic --check hello.ui",
            [
                *runner,
                *("--python", self.python, "--find-links", dist, "--from", requirement),
                *("pyguibud-uic", "--check", "hello.ui"),
            ],
            env=env,
        )


def copy_example(work: Path) -> None:
    """hello.ui and the files it references (``src="..."``), plus the dialog-only document."""
    source = EXAMPLES / "hello.ui"
    shutil.copy2(source, work / "hello.ui")
    for reference in re.findall(r'\bsrc="([^"]+)"', source.read_text("utf-8")):
        target = EXAMPLES / reference
        if target.is_file():
            (work / reference).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, work / reference)
    (work / "dialog.ui").write_text(DIALOG_UI, encoding="utf-8")


def build(verifier: Verifier, out_dir: Path) -> bool:
    """``uv build --all-packages`` into ``out_dir`` (both sdists and both wheels)."""
    uv = shutil.which("uv")
    if uv is None:
        return verifier.record("build", "uv build", False, "uv not found; pass --dist instead")
    code, output = verifier.run([uv, "build", "--all-packages", "--out-dir", out_dir], cwd=ROOT)
    return verifier.record("build", "uv build --all-packages", code == 0, output)


def _wheel_versions(dist: Path, name: str) -> list[str]:
    return sorted({p.name.split("-")[1] for p in dist.glob(f"{name}-*.whl") if "-" in p.name})


def check_artefacts(verifier: Verifier, dist: Path) -> bool:
    """Both wheels of this version must be in ``dist`` and be real zip files."""
    name = "both wheels present"
    if not dist.exists():
        return verifier.record("build", name, False, f"the folder {dist} does not exist")
    if not dist.is_dir():
        return verifier.record("build", name, False, f"{dist} is not a folder")
    problems: list[str] = []
    for distribution in ("pyguibud", "pyguibud_runtime"):
        found = list(dist.glob(f"{distribution}-{verifier.version}-*.whl"))
        if not found:
            versions = _wheel_versions(dist, distribution)
            have = ", ".join(versions) if versions else "none"
            problems.append(
                f"no wheel of {distribution} {verifier.version} in {dist} (versions found: {have})"
            )
        problems.extend(
            f"{wheel.name} is not a valid wheel (empty or not a zip file)"
            for wheel in found
            if not zipfile.is_zipfile(wheel)
        )
    return verifier.record("build", name, not problems, "\n".join(problems))


def check_python(verifier: Verifier) -> bool:
    """``--python`` must run and be Python 3.10 or newer (PyGUIbud's ``requires-python``)."""
    code, output = verifier.run(
        [verifier.python, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"], timeout=60
    )
    wanted = ".".join(map(str, MIN_PYTHON))
    try:
        found = tuple(int(part) for part in output.strip().splitlines()[-1].split("."))
    except (ValueError, IndexError):
        found = ()
    ok = code == 0 and len(found) == 2 and found >= MIN_PYTHON
    detail = (
        f"{verifier.python} is Python {output.strip()}; PyGUIbud needs {wanted} or newer"
        if code == 0 and found
        else f"cannot use {verifier.python} as Python {wanted}+: {output.strip()}"
    )
    return verifier.record("python", f"interpreter is Python {wanted}+", ok, detail)


def sweep_stale(now: float | None = None) -> None:
    """Remove ``pyguibud-verify-*`` folders in the temp dir that are older than 24 hours."""
    cutoff = (time.time() if now is None else now) - _STALE_SECONDS
    try:
        for folder in Path(tempfile.gettempdir()).glob(_PREFIX + "*"):
            if folder.is_dir() and not folder.is_symlink() and folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
    except OSError:
        pass  # a sweep must never stop a verification


def parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--dist", type=Path, help="use these built artefacts, skip building")
    parser.add_argument(
        "--from-index",
        choices=["testpypi"],
        help="download only our two wheels from TestPyPI (everything else comes from PyPI)",
    )
    parser.add_argument("--version", help="version to install (default: the __about__ literal)")
    parser.add_argument(
        "--python", default=default_python(), help="interpreter that makes the venvs"
    )
    parser.add_argument("--skip-uv", action="store_true", help="skip the uv path")
    parser.add_argument("--keep", action="store_true", help="keep the temporary folder")
    args = parser.parse_args(argv)
    if args.dist and args.from_index:
        parser.error("--dist and --from-index exclude each other")
    if args.version and not args.from_index:
        parser.error("--version is for --from-index; otherwise the version is read from the source")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a cp1252 pipe must not crash on an odd character
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    args = parse(argv)
    version = args.version or read_version()
    sweep_stale()
    work = Path(tempfile.mkdtemp(prefix=_PREFIX)).resolve()
    try:
        return _run(args, version, work)
    except KeyboardInterrupt:
        print("interrupted", flush=True)
        return 130
    finally:
        if args.keep:
            print(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
            if work.exists():
                print(f"could not remove the temporary folder {work}; delete it by hand")


def _run(args: argparse.Namespace, version: str, work: Path) -> int:
    if ROOT in work.parents or work == ROOT:
        print(f"FAILED: the temporary folder {work} lies inside the checkout")
        return 1
    verifier = Verifier(work, args.python, version)
    print(f"PyGUIbud {version}; temporary folder {work}; venvs from {args.python}", flush=True)
    if not check_python(verifier):
        print(f"FAILED: {verifier.failures} check(s) ({verifier.passes} passed)")
        return 1
    copy_example(work)
    dist: Path = Path()
    if args.from_index:
        ready = True  # downloaded inside pip_path, with the new venv's own pip
    elif args.dist:
        dist = args.dist.resolve()
        ready = check_artefacts(verifier, dist)
    else:
        dist = work / "dist"
        ready = build(verifier, dist) and check_artefacts(verifier, dist)
    if ready:
        verifier.dist = dist
        verifier.pip_path(dist, bool(args.from_index))
        if not args.skip_uv and verifier.dist.is_absolute():
            verifier.uv_path(verifier.dist)
    if verifier.failures:
        print(f"FAILED: {verifier.failures} check(s) ({verifier.passes} passed)")
        return 1
    paths = "pip" if args.skip_uv else "pip and uv"
    print(f"OK: {verifier.passes} checks passed on the {paths} path(s), version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
