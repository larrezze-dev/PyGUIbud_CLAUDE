"""The document validator (ADR-006; spec ``docs/specs/validate-commands.md`` sections 4 and 5).

:func:`validate` is the only place where semantic rules live. It is pure (it never mutates the
document), iterative (an explicit stack, so deeply nested documents cannot overflow the Python
stack) and never fails fast: every finding is returned, in a deterministic order. The registry is
passed in, so the reader stays registry-free.

Rule codes are stable (``validate.*``, R01 to R82). R49 to R53 (includes) and R75 to R76 (image
files) need disk access, which is injected as ``files=`` (:class:`FileAccess`) and skipped when
it is None; every other rule is pure. The command guards of Step 09 part B compare findings with
:func:`guard_key` and :func:`new_errors`.
"""

from __future__ import annotations

import keyword
import os
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol

from pyguibud.core import keys
from pyguibud.core.colours import colour_problem
from pyguibud.core.diagnostics import EMPTY_SOURCE_MAP, Finding, Severity, SourceMap, node_path
from pyguibud.core.errors import ModelError, XmlIoError
from pyguibud.core.files import (
    IMAGE_SUFFIXES,
    MAX_EXPANDED_NODES,
    MAX_INCLUDE_DEPTH,
    MAX_INCLUDE_FILES,
    ImageProbe,
    is_network_or_device_path,
)
from pyguibud.core.model import (
    CORE_CLASS_NAMES,
    NS_UI,
    Action,
    Document,
    Event,
    GridCell,
    GridLine,
    ImageResource,
    Include,
    Layout,
    Menu,
    Menubar,
    MenuSeparator,
    PackPlacement,
    PagePlacement,
    Prop,
    PropertyDef,
    RawXml,
    Statusbar,
    Variable,
    Widget,
    WidgetSpec,
    Window,
    is_extension,
    is_valid_event,
    split_class_name,
)
from pyguibud.core.schema import (
    CURRENT_SCHEMA_VERSION,
    KNOWN_ATTRIBUTES,
    UI_VOCABULARY,
    parse_version,
)
from pyguibud.core.xmltree import (
    MAX_DEPTH,
    LazyMessage,
    check_attribute_key,
    first_illegal_char,
    parse_fragment,
    split_name,
)
from pyguibud.i18n import LANGUAGE_CODE_RE, N_, NP_

if TYPE_CHECKING:
    from pyguibud.core.xml_io import ReadResult

__all__ = [
    "BIND_TYPES",
    "MAX_DEFAULT_LENGTH",
    "MAX_FINDINGS",
    "MAX_GRID_INDEX",
    "MAX_ID_LENGTH",
    "MAX_NESTING",
    "MAX_PIXELS",
    "MAX_TEXT_LENGTH",
    "MAX_WEIGHT",
    "RESERVED_IDS",
    "TRUNCATED_CODE",
    "WINDOW_PROPERTIES",
    "FileAccess",
    "ValidationReport",
    "WidgetLookup",
    "guard_key",
    "new_errors",
    "validate",
    "validate_read",
]

MAX_FINDINGS: Final = 1000
#: Highest grid row/column (cells and line configuration). Tk 8.6 grids a cell only while
#: ``row + rowspan <= 9999`` ("row out of bounds" otherwise), so the last usable index is
#: 9998 and a span may reach ``MAX_GRID_INDEX + 1``.
MAX_GRID_INDEX: Final = 9998
MAX_PIXELS: Final = 10_000  # padding, gap, padx/pady, minsize, min_width/min_height
MAX_WEIGHT: Final = 10_000  # grid line weight, page weight
MAX_ID_LENGTH: Final = 64
#: Characters of a string property (R79). Shared with the runtime, which clips longer display
#: texts (a translation is never validated). Tk lays a one-line label out in linear time
#: (about 0.04 s at this length on Windows) but stalls for minutes near 4.5 million characters.
MAX_TEXT_LENGTH: Final = 100_000
#: Characters of a variable default (R80). A bound Entry, Combobox or Spinbox shows it, and the
#: Tk entry lays text out in quadratic time: about 0.1 s at this length, 6 s at 100 000.
MAX_DEFAULT_LENGTH: Final = 10_000
#: Deepest XML element depth of a node element (root = 1, window = 2); leaves one level for the
#: node's own layout columns and page text, so the writer never emits ``xml.too_deep``.
MAX_NESTING: Final = MAX_DEPTH - 2

#: Ids that clash with the members of the generated interface (``ui.<id>``; spec runtime.md 2.3).
#: Adding a public member to ``UiScope``/``LoadedUi`` later is a breaking change.
RESERVED_IDS: Final = frozenset(
    {"vars", "widgets", "windows", "setup_ui", "retranslate", "show", "run", "destroy"}
)

#: Code of the last finding when the cap is hit; it never counts for the command guards.
TRUNCATED_CODE: Final = "validate.truncated"

#: Properties of a window (the model has no registry spec for windows).
WINDOW_PROPERTIES: Final = (
    # Translators: the property of a window that holds the text of its title bar.
    PropertyDef(name="title", type="string", translatable=True, display_name=N_("Title")),
)

#: Variable types a core class can be bound to (spec section 5.1); an empty row means "none".
BIND_TYPES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {name: () for name in sorted(CORE_CLASS_NAMES)}
    | {
        "Entry": ("string", "int", "double"),
        "Spinbox": ("string", "int", "double"),
        "Combobox": ("string",),
        "Label": ("string", "int", "double"),
        "Scale": ("double", "int"),
        "Progressbar": ("double", "int"),
        "Checkbutton": ("bool", "int"),
        "Radiobutton": ("string", "int"),
    }
)

_STRUCTURAL: Final = frozenset({"Menubar", "Menu", "Action", "Statusbar"})
# The closed sets the writer accepts (xml_io keeps its own copy; a test keeps them in step).
_WINDOW_KINDS: Final = ("main", "dialog", "component")
_VARIABLE_TYPES: Final = ("string", "int", "double", "bool")
_LAYOUT_TYPES: Final = ("grid", "pack")
_ORIENTS: Final = ("vertical", "horizontal")
_FILLS: Final = ("none", "x", "y", "both")
_ID_RE: Final = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
_BUTTON_TOKENS: Final = ("ok", "cancel", "yes", "no", "close")
_DOMAIN_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_INT_RE: Final = re.compile(r"-?[0-9]{1,9}")
_FLOAT_RE: Final = re.compile(r"-?(?:[0-9]{1,15}(?:\.[0-9]{1,15})?|\.[0-9]{1,15})")
_STICKY_RE: Final = re.compile(r"(?!.*(.).*\1)[nsew]{0,4}")
_SPLIT_PATH_RE: Final = re.compile(r"[\\/]")
_CLIP: Final = 100  # longest user text echoed in a message
_SMALL_AREA: Final = 1024  # grid cells covered by a rectangle that is tracked cell by cell

# ---------------------------------------------------------------- messages (msgids)
# Translators: {id} is an element id from the file, {first} the path of the first element.
_M_DUPLICATE_ID: Final = N_("The id '{id}' is used more than once; the first use is {first}.")
_M_EMPTY_ID: Final = N_("This element has no id; every element needs a unique id.")
# Translators: {id} is the text found in the file, {limit} a whole number.
_M_BAD_ID: Final = N_(
    "'{id}' is not a valid id: use up to {limit} letters (a–z, A–Z), digits and underscores, "  # noqa: RUF001
    "starting with a letter."
)
_M_KEYWORD_ID: Final = N_("'{id}' is a Python keyword and cannot be used as an id.")
# Translators: {first} is the path of the first main window.
_M_MULTIPLE_MAIN: Final = N_("Only one window can be the main window; {first} already is.")
_M_NO_WINDOWS: Final = N_("The document has no windows.")
_M_COMPONENT_CHROME: Final = N_(
    "The component window '{id}' cannot have a menu bar or a status bar."
)
# Translators: {attribute} is an attribute name such as modal; {id} is an element id.
_M_DIALOG_ONLY: Final = N_("'{attribute}' only applies to dialog windows and is ignored on '{id}'.")
# Translators: {field} is a property or attribute name; the other values are numbers.
_M_RANGE_BETWEEN: Final = N_("{field} must be between {minimum} and {maximum}, not {value}.")
_M_RANGE_MIN: Final = N_("{field} must be at least {minimum}, not {value}.")
_M_RANGE_MAX: Final = N_("{field} must be at most {maximum}, not {value}.")
# Translators: {parent} and {id} are element ids, {class_name} a widget class name.
_M_NOT_CONTAINER: Final = N_(
    "'{parent}' ({class_name}) cannot contain other widgets; move '{id}' into a container."
)
_M_LAYOUT_NOT_ALLOWED: Final = N_(
    "'{id}' ({class_name}) is not a container and cannot have a layout."
)
_M_LAYOUT_ON_PAGES: Final = N_(
    "'{id}' ({class_name}) shows its children as pages and cannot have a layout."
)
_M_LAYOUT_MISSING: Final = N_("'{id}' has no layout; add a grid or a pack layout.")
# Translators: {expected} is a placement tag such as <cell>; keep it untranslated.
_M_PLACEMENT_MISSING: Final = N_("'{id}' needs a {expected} placement inside '{parent}'.")
# Translators: {found} and {expected} are placement tags such as <cell>, <pack> or <page>.
_M_PLACEMENT_MISMATCH: Final = N_(
    "'{id}' has a {found} placement, but '{parent}' expects {expected}."
)
_M_GRID_COLLISION: Final = N_(
    "'{id}' overlaps '{other}' in the grid at row {row}, column {column}."
)
# Translators: n, s, e and w are the compass letters of the Tk sticky option; keep them as they are.
_M_BAD_STICKY: Final = N_(
    "'{value}' is not a valid sticky value; use any of n, s, e and w, each at most once."
)
_M_GRID_LINES_ON_PACK: Final = N_("A pack layout cannot configure grid columns or rows.")
_M_DUPLICATE_COLUMN: Final = N_("Grid column {index} is configured more than once.")
_M_DUPLICATE_ROW: Final = N_("Grid row {index} is configured more than once.")
_M_ORIENT_IGNORED: Final = N_("'orient' only applies to pack layouts and is ignored here.")
# Translators: {attribute} is an attribute name such as weight; {class_name} a widget class name.
_M_PAGE_ATTR_IGNORED: Final = N_("'{attribute}' of a page is ignored by {class_name}.")
_M_STRUCTURAL_CLASS: Final = N_(
    "'{class_name}' is a menu or window element and cannot be used as a widget."
)
# Translators: {limit} is a whole number of nesting levels.
_M_TOO_DEEP: Final = N_("'{id}' is nested too deeply; a .ui file allows at most {limit} levels.")
_M_UNKNOWN_CLASS: Final = N_("Unknown widget class '{class_name}'.")
_M_MISSING_FALLBACK: Final = N_(
    "The extension widget '{id}' ({class_name}) needs a fallback core class."
)
_M_BAD_FALLBACK: Final = N_(
    "'{fallback}' is not a core widget class and cannot be the fallback of '{id}'."
)
_M_FALLBACK_MISMATCH: Final = N_(
    "The fallback '{fallback}' of '{id}' does not match {class_name}: one is a container and "
    "the other is not."
)
# Translators: {plugin} is a Python package name; keep the pip command as it is.
_M_PLUGIN_MISSING: Final = N_(
    "'{class_name}' is not installed, so '{fallback}' is shown instead; install it with: "
    "pip install {plugin}"
)
_M_PLUGIN_MISSING_NAMELESS: Final = N_(
    "'{class_name}' is not installed, so '{fallback}' is shown instead."
)
_M_EXTENSION_ATTR_IGNORED: Final = N_(
    "'{attribute}' only applies to extension widgets and is ignored on '{id}'."
)
_M_UNKNOWN_PROP: Final = N_("{class_name} has no property '{name}'; it is kept but ignored.")
# Translators: {name} is a property name and {value} the text found in the file.
_M_BAD_INT: Final = N_("The property '{name}' must be a whole number, not '{value}'.")
_M_BAD_FLOAT: Final = N_("The property '{name}' must be a number, not '{value}'.")
# Translators: keep true and false untranslated.
_M_BAD_BOOL: Final = N_("The property '{name}' must be true or false, not '{value}'.")
# Translators: {choices} is a comma-separated list of the allowed values.
_M_BAD_ENUM: Final = N_("The property '{name}' must be one of {choices}, not '{value}'.")
_M_BAD_COLOUR: Final = N_(
    "The property '{name}' must be a colour such as #1a2b3c or a colour name, not '{value}'."
)
# Translators: {value} is a name such as SystemButtonFace; keep #1a2b3c as it is.
_M_SYSTEM_COLOUR: Final = N_(
    "The property '{name}' uses '{value}', a system colour that exists on one platform only; "
    "use a colour such as #1a2b3c or a colour name."
)
_M_NOT_TRANSLATABLE: Final = N_("The property '{name}' cannot be translatable.")
_M_IMAGE_NEEDS_REF: Final = N_(
    "The image property '{name}' must refer to an image resource (and have no text)."
)
_M_REF_NOT_ALLOWED: Final = N_(
    "The property '{name}' is not an image and cannot refer to a resource."
)
_M_UNKNOWN_RESOURCE: Final = N_("'{ref}' is not a declared image resource.")
# Translators: keep the event names and key:<sequence> untranslated.
_M_BAD_EVENT: Final = N_(
    "'{name}' is not a valid event; use command, change, select, activate, focus_in, "
    "focus_out or key:<sequence>."
)
_M_UNSUPPORTED_EVENT: Final = N_("{class_name} does not support the event '{name}'.")
_M_DUPLICATE_EVENT: Final = N_("The event '{name}' is handled more than once on '{id}'.")
_M_BAD_HANDLER: Final = N_(
    "'{handler}' is not a valid handler name: use letters, digits and underscores, starting "
    "with a letter, and no Python keyword."
)
_M_BAD_BIND: Final = N_("'{bind}' is not a valid variable name.")
_M_UNKNOWN_VARIABLE: Final = N_("'{bind}' is not a declared variable.")
_M_BIND_NOT_SUPPORTED: Final = N_("{class_name} cannot be bound to a variable.")
# Translators: {type} is a variable type (string, int, double or bool); {allowed} a list of them.
_M_BIND_TYPE_MISMATCH: Final = N_(
    "{class_name} cannot be bound to the {type} variable '{bind}'; use one of: {allowed}."
)
_M_BAD_VARIABLE_DEFAULT: Final = N_(
    "The default '{default}' of the variable '{id}' is not a valid {type} value."
)
# Translators: {length} and {limit} are numbers of characters.
_M_TEXT_TOO_LONG: Final = N_(
    "The property '{name}' has {length} characters; at most {limit} are allowed."
)
_M_DEFAULT_TOO_LONG: Final = N_(
    "The default of the variable '{id}' has {length} characters; at most {limit} are allowed."
)
_M_EMPTY_PATH: Final = N_("'{id}' has no file path.")
_M_ABSOLUTE_PATH: Final = N_("The path '{path}' is absolute; use a path relative to the .ui file.")
_M_PATH_ESCAPES: Final = N_("The path '{path}' points outside the folder of the .ui file.")
# Translators: {path} is a file path written in the .ui file.
_M_NETWORK_PATH: Final = N_(
    "The path '{path}' points to a network share or a device, which is never opened; use a "
    "path relative to the .ui file."
)
_M_BAD_COMPONENT: Final = N_("'{component}' is not a valid component id.")
# Translators: {where} is a technical path; {codepoint} a hexadecimal character code such as 0001.
_M_ILLEGAL_CHAR: Final = N_(
    "{where} contains the character U+{codepoint}, which a .ui file cannot store."
)
# Translators: {field} is an attribute name such as kind; {choices} is a comma-separated list of
# the allowed values and {value} the value found.
_M_BAD_CHOICE: Final = N_("{field} must be one of {choices}, not '{value}'.")
_M_BAD_CLASS_NAME: Final = N_("'{name}' is not a valid widget class name.")
# Translators: {where} is a technical path such as window[main]@buttons.
_M_NOT_TEXT: Final = N_("{where} must be text, not '{value}'.")
# Translators: {field} is an attribute name such as modal; keep true and false untranslated.
_M_NOT_FLAG: Final = N_("{field} must be true or false, not '{value}'.")
_M_BAD_PAGE_TEXT: Final = N_("The text of a page must be a property named 'text'.")
# Translators: {name} is an XML attribute name; {where} is a technical path such as
# window[main]/widget[btn]/prop[text].
_M_BAD_ATTRIBUTE_NAME: Final = N_("'{name}' is not a valid extra attribute name for {where}.")
# Translators: {where} is a technical path such as window[main]/widget[btn]/cell.
_M_BAD_RAW_XML: Final = N_("The preserved XML content of {where} is damaged and cannot be saved.")
# Translators: {where} is a technical path; {value} the value found; {expected} is the name of a
# model type such as Event or GridLine (keep it untranslated).
_M_BAD_ITEM: Final = N_("{where} contains '{value}', which is not a {expected}.")
# Translators: {version} is the version stored in the document, {current} the one PyGUIbud saves.
_M_BAD_SCHEMA_VERSION: Final = N_(
    "The schema version '{version}' cannot be saved; it must be {current}."
)
_M_RESERVED_ID: Final = N_(
    "'{id}' is reserved by the generated interface and cannot be used as an id."
)
# Translators: {value} is the text from the file, {choices} a list of button names.
_M_BAD_BUTTONS: Final = N_(
    "'{value}' is not a valid button list; use a comma-separated list of {choices} without repeats."
)
# Translators: {value} is the shortcut as typed in the file.
_M_BAD_SHORTCUT: Final = N_(
    "'{value}' is not a valid shortcut, for example Ctrl+S or Ctrl+Shift+F5."
)
_M_SHORTCUT_MODIFIER: Final = N_(
    "The shortcut '{value}' needs Ctrl or Alt unless it is a function key (F1\u2013F24)."
)
# Translators: {value} is the key sequence as typed in the file.
_M_BAD_KEY_SEQUENCE: Final = N_(
    "'{value}' is not a valid key, for example key:Ctrl+S or key:<Control-s>."
)
# Translators: {shortcut} is a shortcut such as Ctrl+S, {window} a window id.
_M_DUPLICATE_SHORTCUT: Final = N_(
    "The shortcut '{shortcut}' is used more than once in '{window}'; only the first one works."
)
_M_IMAGE_FORMAT: Final = N_("'{src}' is not a supported image; use PNG, GIF, PPM or PGM.")
_M_IMAGE_MISSING: Final = N_("The image file '{src}' does not exist.")
# Translators: {src} is a file path, {reason} says what is wrong with the file.
_M_IMAGE_INVALID: Final = N_("The image file '{src}' cannot be used: {reason}")
_M_BAD_RADIO_VALUE: Final = N_(
    "The value '{value}' of '{id}' must be a whole number, because it is bound to the int "
    "variable '{bind}'."
)
_M_BAD_DOMAIN: Final = N_(
    "'{value}' is not a valid translation domain; use letters, digits, '_', '-' or '.'."
)
# Translators: {value} is the source language attribute of a .ui file.
_M_BAD_SOURCE_LOCALE: Final = N_(
    "'{value}' is not a valid language code for the source texts; use a code such as en_GB."
)
_M_INCLUDE_MISSING: Final = N_("The included file '{src}' does not exist or cannot be read.")
_M_INCLUDE_ERRORS: Final = NP_(
    "The included file '{src}' has {count} error.",
    "The included file '{src}' has {count} errors.",
)
# Translators: {reason} is the cause, for example "The file is not valid UTF-8 text".
_M_INCLUDE_UNREADABLE: Final = N_("The included file '{src}' cannot be read: {reason}")
_M_INCLUDE_NO_WINDOW: Final = N_("'{src}' has no component window '{component}'.")
_M_INCLUDE_NOT_COMPONENT: Final = N_("The window '{component}' in '{src}' is not a component.")
# Translators: {chain} is a path such as a.ui#x -> b.ui#y -> a.ui#x.
_M_INCLUDE_CYCLE: Final = N_("Including '{component}' from '{src}' creates a cycle: {chain}.")
_M_LIMIT_DEPTH: Final = N_("Including '{src}' nests includes deeper than {limit} levels.")
_M_LIMIT_FILES: Final = N_("Including '{src}' reads more than {limit} files.")
_M_LIMIT_NODES: Final = N_("Including '{src}' creates more than {limit} widgets.")
_M_TRUNCATED: Final = NP_(
    "{count} more problem was found but not listed.",
    "{count} more problems were found but not listed.",
)


# ---------------------------------------------------------------- public types
class WidgetLookup(Protocol):
    """What the validator needs from a registry; :class:`~pyguibud.core.registry.Registry` fits."""

    def get(self, name: str) -> WidgetSpec | None:
        """Return the spec registered as ``name``, or None."""
        ...


class FileAccess(Protocol):
    """Disk access injected into :func:`validate` (``core.files.DiskFiles`` fits).

    Files are named by opaque keys; ``root`` is the key of the validated document.
    """

    @property
    def root(self) -> str:
        """The key of the document being validated."""
        ...

    def resolve(self, including: str, src: str) -> str:
        """Key of ``src`` as seen from file ``including`` (``"#"`` is ``including``).

        Raises:
            OSError: ``src`` cannot name a file.
        """
        ...

    def read(self, key: str) -> ReadResult:
        """The file ``key``, read at most once.

        Raises:
            OSError: missing, not a regular file or unreadable.
            XmlIoError: not a valid ``.ui`` file.
        """
        ...

    def probe_image(self, including: str, src: str) -> ImageProbe:
        """Look at the first bytes of an image file; never decodes it."""
        ...


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """The result of :func:`validate`."""

    findings: tuple[Finding, ...]
    #: True when the cap was hit; the last finding is then ``validate.truncated``.
    truncated: bool = False

    @property
    def errors(self) -> tuple[Finding, ...]:
        """The findings with severity ``error``."""
        return tuple(f for f in self.findings if f.severity == "error")

    @property
    def warnings(self) -> tuple[Finding, ...]:
        """The findings with severity ``warning``."""
        return tuple(f for f in self.findings if f.severity == "warning")

    @property
    def ok(self) -> bool:
        """True when there is no error (also exact when the report is truncated)."""
        return all(f.severity != "error" for f in self.findings)


def validate(
    document: Document,
    registry: WidgetLookup,
    *,
    source: str = "<memory>",
    positions: SourceMap | None = None,
    limit: int | None = MAX_FINDINGS,
    files: FileAccess | None = None,
) -> ValidationReport:
    """Validate ``document`` and return every finding, in a deterministic order.

    Pure: the document is not changed. With ``files`` the include rules (R49 to R53) and the
    image file rules (R75, R76) also run; each included file is read once, validated without
    ``files`` and its findings follow those of ``document`` (they carry their own ``source``).
    ``limit=None`` is unbounded (used by the command guards).
    After ``limit`` findings no more are stored; the last stored one is replaced by a
    ``validate.truncated`` finding whose severity is that of the worst dropped finding, so
    ``ok`` stays exact.

    Raises:
        ValueError: ``limit`` is neither None nor an int of at least 1 (a bool is refused).
    """
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        raise ValueError(f"limit must be None or a whole number of at least 1, not {limit!r}")
    sink = _Sink(source, positions if positions is not None else EMPTY_SOURCE_MAP, limit)
    _Validator(document, registry, sink, files).run()
    if files is not None:
        _IncludePass(document, registry, sink, files, limit).run()
    return sink.report()


def validate_read(
    result: ReadResult, registry: WidgetLookup, *, files: FileAccess | None = None
) -> ValidationReport:
    """Validate a freshly read document, with the positions of the file."""
    return validate(
        result.document, registry, source=result.source, positions=result.positions, files=files
    )


def guard_key(finding: Finding) -> tuple[object, ...]:
    """The key under which the command guards compare an error (spec section 6.3).

    Symmetric rules use order-independent keys so that reordering an already broken document is
    not blocked; every other rule is keyed by ``(code, anchor identity, part)``.
    """
    code = finding.code
    if code == "validate.duplicate_id":
        return (code, finding.params.get("id"))
    if code == "validate.multiple_main":
        return (code,)
    if code == "validate.grid_collision":
        return (code, frozenset({finding.anchor, finding.related}))
    return (code, finding.anchor, finding.part)


def new_errors(before: Iterable[Finding], after: Iterable[Finding]) -> tuple[Finding, ...]:
    """Return the errors of ``after`` whose guard key occurs more often than in ``before``.

    ``validate.truncated`` never counts. The result keeps the validation order of ``after``.
    """
    known = Counter(guard_key(f) for f in before if f.is_error and f.code != TRUNCATED_CODE)
    fresh: list[Finding] = []
    for finding in after:
        if not finding.is_error or finding.code == TRUNCATED_CODE:
            continue
        key = guard_key(finding)
        if known[key] > 0:
            known[key] -= 1
        else:
            fresh.append(finding)
    return tuple(fresh)


# ---------------------------------------------------------------- helpers
def _clip(value: object) -> str:
    """Text of a user value for a message (long values are shortened)."""
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= _CLIP else text[:_CLIP] + "…"


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(value)


def _is_identifier(value: object) -> bool:
    return (
        isinstance(value, str)
        and _ID_RE.fullmatch(value) is not None
        and not keyword.iskeyword(value)
    )


def _is_absolute(path: str) -> bool:
    return PurePosixPath(path).is_absolute() or bool(PureWindowsPath(path).anchor)


def _escapes(path: str) -> bool:
    depth = 0
    for segment in _SPLIT_PATH_RE.split(path):
        if segment in ("", "."):
            continue
        if segment == "..":
            depth -= 1
            if depth < 0:
                return True
        else:
            depth += 1
    return False


def _core_name(class_name: object, fallback: object) -> str | None:
    """The core class whose behaviour a widget has (itself, or the fallback of an extension)."""
    name = class_name if isinstance(class_name, str) and not is_extension(class_name) else fallback
    if isinstance(name, str) and name in CORE_CLASS_NAMES and name not in _STRUCTURAL:
        return name
    return None


@lru_cache(maxsize=4096)
def _raw_xml_damaged(xml: str) -> bool:
    """True when the writer would refuse to splice ``xml`` (cached: documents repeat it)."""
    try:
        fragment = parse_fragment(xml)
    except XmlIoError:
        return True
    uri, local = split_name(fragment.tag)
    return uri == NS_UI and local in UI_VOCABULARY


def _raw_damaged(raw: object) -> bool:
    """R66: an ``extra_children`` entry the writer refuses (the depth is left to the writer)."""
    if not isinstance(raw, RawXml) or not isinstance(raw.xml, str) or raw.extra_attrs:
        return True
    return _raw_xml_damaged(raw.xml)


def _bad_attribute_name(key: object, element: str) -> bool:
    """R65: an extra attribute name the writer refuses on ``element``."""
    if not isinstance(key, str) or key in KNOWN_ATTRIBUTES.get(element, ()):
        return True
    try:
        check_attribute_key(key, "")
    except XmlIoError:
        return True
    return False


def _schema_version_ok(version: object) -> bool:
    """R68: the writer saves exactly the current version; a newer one is read-only (no error)."""
    if version == CURRENT_SCHEMA_VERSION:
        return True
    parsed = parse_version(version) if isinstance(version, str) else None
    current = parse_version(CURRENT_SCHEMA_VERSION)
    return parsed is not None and current is not None and parsed > current


def _placement_kind(placement: object) -> str:
    if isinstance(placement, GridCell):
        return "cell"
    if isinstance(placement, PackPlacement):
        return "pack"
    if isinstance(placement, PagePlacement):
        return "page"
    return type(placement).__name__


_Rect = tuple[int, int, int, int, object]  # row, column, rows spanned, columns spanned, node


def _valid_rect(cell: GridCell) -> bool:
    row, column, rowspan, columnspan = cell.row, cell.column, cell.rowspan, cell.columnspan
    return (
        type(row) is int
        and type(column) is int
        and type(rowspan) is int
        and type(columnspan) is int
        and 0 <= row <= MAX_GRID_INDEX
        and 0 <= column <= MAX_GRID_INDEX
        and rowspan >= 1
        and columnspan >= 1
        and row + rowspan <= MAX_GRID_INDEX + 1
        and column + columnspan <= MAX_GRID_INDEX + 1
    )


def _first_overlap(rects: list[_Rect], rect: _Rect) -> tuple[object, int, int] | None:
    row, column, rows, columns, _node = rect
    for other_row, other_column, other_rows, other_columns, other in rects:
        if (
            other_row < row + rows
            and row < other_row + other_rows
            and other_column < column + columns
            and column < other_column + other_columns
        ):
            return other, max(row, other_row), max(column, other_column)
    return None


def _grid_collisions(children: Iterable[Widget | Include]) -> dict[int, tuple[object, int, int]]:
    """Map ``id(child)`` to ``(other, row, column)`` for the later child of each overlap.

    Sweep in ``(row, column, child order)``. Rectangles up to ``_SMALL_AREA`` cells are marked
    cell by cell (O(n) for the usual 1x1 cells); larger ones are compared pairwise, and there are
    few of them in a real document. At most one finding per child.
    """
    rects: list[tuple[int, int, int, int, int, object]] = []
    for index, child in enumerate(children):
        cell = child.placement
        if isinstance(cell, GridCell) and _valid_rect(cell):
            rects.append((cell.row, cell.column, index, cell.rowspan, cell.columnspan, child))
    rects.sort(key=lambda r: r[:3])
    occupied: dict[tuple[int, int], object] = {}
    smalls: list[_Rect] = []
    bigs: list[_Rect] = []
    found: dict[int, tuple[object, int, int]] = {}
    for row, column, _index, rowspan, columnspan, node in rects:
        rect: _Rect = (row, column, rowspan, columnspan, node)
        hit: tuple[object, int, int] | None = None
        if rowspan * columnspan <= _SMALL_AREA:
            cells = [
                (r, c)
                for r in range(row, row + rowspan)
                for c in range(column, column + columnspan)
            ]
            for cell_key in cells:
                other = occupied.get(cell_key)
                if other is not None:
                    hit = (other, cell_key[0], cell_key[1])
                    break
            if hit is None:
                hit = _first_overlap(bigs, rect)
            for cell_key in cells:
                occupied.setdefault(cell_key, node)
            smalls.append(rect)
        else:
            hit = _first_overlap(bigs, rect) or _first_overlap(smalls, rect)
            bigs.append(rect)
        if hit is not None:
            found[id(node)] = hit
    return found


def _probe_image(
    files: FileAccess, including: str, src: str, sink: _Sink, anchor: object, part: str
) -> None:
    """R75 and R76: look at one image file (its suffix is already known to be supported)."""
    probe = files.probe_image(including, src)
    if probe.status == "missing":
        sink.error("validate.image_missing", _M_IMAGE_MISSING, anchor, part, src=_clip(src))
    elif probe.status == "invalid":
        sink.error(
            "validate.image_invalid",
            _M_IMAGE_INVALID,
            anchor,
            part,
            src=_clip(src),
            reason=LazyMessage(probe.reason),
        )


# ---------------------------------------------------------------- result collector
class _Sink:
    """Collects findings, applies the cap and fills in positions and paths."""

    def __init__(self, source: str, positions: SourceMap, limit: int | None) -> None:
        self.source = source
        self.positions = positions
        self.limit = limit
        self.findings: list[Finding] = []
        self.dropped = 0
        self.dropped_error = False
        #: The window being visited: it supplies the path prefix of menu bars and status bars.
        self.window: Window | None = None

    def add(
        self,
        severity: Severity,
        code: str,
        msgid: str,
        anchor: object,
        part: str,
        related: object | None,
        params: dict[str, object],
    ) -> None:
        if self.limit is not None and len(self.findings) >= self.limit:
            self.dropped += 1
            self.dropped_error = self.dropped_error or severity == "error"
            return
        position = self.positions.get(anchor, part)
        line, column = position if position is not None else (None, None)
        self.findings.append(
            Finding(
                code=code,
                msgid=msgid,
                params=params,
                source=self.source,
                line=line,
                column=column,
                severity=severity,
                path=node_path(anchor, part, window=self.window),
                anchor=anchor,
                part=part,
                related=related,
            )
        )

    def error(
        self,
        code: str,
        msgid: str,
        anchor: object,
        part: str = "",
        /,
        *,
        related: object | None = None,
        **params: object,
    ) -> None:
        self.add("error", code, msgid, anchor, part, related, params)

    def warning(
        self,
        code: str,
        msgid: str,
        anchor: object,
        part: str = "",
        /,
        **params: object,
    ) -> None:
        self.add("warning", code, msgid, anchor, part, None, params)

    def extend(self, findings: Iterable[Finding]) -> None:
        """Append findings of another file, honouring the cap."""
        for finding in findings:
            if self.limit is not None and len(self.findings) >= self.limit:
                self.dropped += 1
                self.dropped_error = self.dropped_error or finding.severity == "error"
            else:
                self.findings.append(finding)

    def report(self) -> ValidationReport:
        findings = self.findings
        if not self.dropped:
            return ValidationReport(findings=tuple(findings), truncated=False)
        last = findings.pop()
        worst: Severity = "error" if self.dropped_error or last.severity == "error" else "warning"
        findings.append(
            Finding(
                code=TRUNCATED_CODE,
                msgid=_M_TRUNCATED,
                params={"count": self.dropped + 1},
                source=self.source,
                severity=worst,
            )
        )
        return ValidationReport(findings=tuple(findings), truncated=True)


@dataclass(slots=True)
class _Scope:
    """What the children of a container must satisfy."""

    owner_id: str
    class_name: str
    #: "unknown" (no checks), "none" (cannot hold children), "nolayout" (placement unknown),
    #: or the placement kind the children need: "grid", "pack" or "pages".
    mode: str
    core_name: str | None
    collisions: dict[int, tuple[object, int, int]]


@dataclass(slots=True)
class _Effective:
    spec: WidgetSpec | None
    fallback_mode: bool
    core_name: str | None


_EXPECTED: Final = {"grid": "cell", "pack": "pack", "pages": "page"}
_PAGE_TEXT: Final = PropertyDef(name="text", type="string", translatable=True)
_Item = tuple[object, "_Scope | None", int]


class _Validator:
    """One validation run over one document."""

    def __init__(
        self,
        document: Document,
        registry: WidgetLookup,
        sink: _Sink,
        files: FileAccess | None = None,
    ) -> None:
        self.document = document
        self.registry = registry
        self.sink = sink
        self.files = files
        #: Canonical shortcuts of the window being visited (R73): identity -> first action.
        self.shortcuts: dict[tuple[frozenset[str], str], Action] = {}
        self.ids: dict[str, tuple[object, str, Window | None]] = {}
        self.first_main: Window | None = None
        self._specs: dict[str, WidgetSpec | None] = {}
        self._defs: dict[int, tuple[WidgetSpec | None, dict[str, PropertyDef]]] = {}

    # ------------------------------------------------ small services
    def spec(self, name: str) -> WidgetSpec | None:
        if name not in self._specs:
            self._specs[name] = self.registry.get(name)
        return self._specs[name]

    def defs_of(self, properties: tuple[PropertyDef, ...]) -> dict[str, PropertyDef]:
        return {definition.name: definition for definition in properties}

    def chars(
        self,
        value: object,
        anchor: object,
        part: str = "",
        attribute: str = "",
        *,
        required: bool = False,
    ) -> None:
        """R54 and R62: report a value the writer cannot store as text.

        ``None`` means "absent" for optional attributes; for ``required`` text (the writer has
        no way to omit it) ``None`` is reported as R62 too.
        """
        if value is None and not required:
            return
        where = node_path(anchor, part, window=self.sink.window)
        if attribute:
            where = f"{where}@{attribute}"
        if not isinstance(value, str):
            # R62: the writer refuses anything but text.
            self.sink.error(
                "validate.not_text", _M_NOT_TEXT, anchor, part, where=where, value=_clip(value)
            )
            return
        illegal = first_illegal_char(value)
        if illegal is None:
            return
        self.sink.error(
            "validate.illegal_char",
            _M_ILLEGAL_CHAR,
            anchor,
            part,
            where=where,
            codepoint=f"{ord(illegal):04X}",
        )

    def check_choice(
        self,
        anchor: object,
        part: str,
        code: str,
        field: str,
        value: object,
        choices: tuple[str, ...],
    ) -> None:
        """R56 to R59 and R60: report a value outside a closed set the writer accepts."""
        if isinstance(value, str) and value in choices:
            return
        self.sink.error(
            code,
            _M_BAD_CHOICE,
            anchor,
            part,
            field=field,
            choices=", ".join(choices),
            value=_clip(value),
        )

    def check_flag(self, anchor: object, part: str, field: str, value: object) -> None:
        """R63: report a flag that is not a real bool (the writer refuses it)."""
        if not isinstance(value, bool):
            self.sink.error(
                "validate.not_flag", _M_NOT_FLAG, anchor, part, field=field, value=_clip(value)
            )

    def bad_item(self, anchor: object, part: str, value: object, expected: str) -> None:
        """R67: a collection entry of the wrong model type (a hand-built model)."""
        self.sink.error(
            "validate.bad_item",
            _M_BAD_ITEM,
            anchor,
            part,
            where=node_path(anchor, part, window=self.sink.window),
            value=_clip(value),
            expected=expected,
        )

    def check_extras(self, item: object, element: str, anchor: object, part: str = "") -> None:
        """R65, R66 and R54/R62 for the preserved attributes and children of ``item``.

        ``element`` is the local name ``item`` is written as, so an extra attribute can never
        shadow one of its known attributes.
        """
        attrs = getattr(item, "extra_attrs", None)
        children = getattr(item, "extra_children", ())
        if not attrs and (children == () or children == []):
            return  # the usual case, kept cheap: this runs for every node and value object
        sink = self.sink
        if attrs:
            if not isinstance(attrs, Mapping):
                attrs = {_clip(attrs): ""}
            for key in sorted(attrs, key=str):
                if _bad_attribute_name(key, element):
                    sink.error(
                        "validate.bad_attribute_name",
                        _M_BAD_ATTRIBUTE_NAME,
                        anchor,
                        part,
                        name=_clip(key),
                        where=node_path(anchor, part, window=sink.window),
                    )
                else:
                    self.chars(attrs[key], anchor, part, key, required=True)
        if not isinstance(children, list | tuple) or (
            children and any(_raw_damaged(raw) for raw in children)
        ):
            sink.error(
                "validate.bad_raw_xml",
                _M_BAD_RAW_XML,
                anchor,
                part,
                where=node_path(anchor, part, window=sink.window),
            )

    def check_range(
        self,
        anchor: object,
        part: str,
        field: str,
        value: object,
        minimum: float | None,
        maximum: float | None,
        *,
        whole: bool = True,
        shown: str | None = None,
    ) -> None:
        """R09: report a number outside ``minimum..maximum`` (or one of the wrong type)."""
        if whole:
            valid = type(value) is int
        else:
            valid = isinstance(value, int | float) and not isinstance(value, bool)
        if valid:
            assert isinstance(value, int | float)
            valid = (minimum is None or value >= minimum) and (maximum is None or value <= maximum)
        if valid:
            return
        params: dict[str, object] = {
            "field": field,
            "value": _clip(value) if shown is None else _clip(shown),
        }
        if minimum is not None:
            params["minimum"] = _num(minimum)
        if maximum is not None:
            params["maximum"] = _num(maximum)
        if minimum is not None and maximum is not None:
            msgid = _M_RANGE_BETWEEN
        elif minimum is not None:
            msgid = _M_RANGE_MIN
        else:
            msgid = _M_RANGE_MAX
        self.sink.error("validate.out_of_range", msgid, anchor, part, **params)

    # ------------------------------------------------ ids
    def check_id(self, anchor: object, value: object, part: str = "") -> None:
        sink = self.sink
        if not isinstance(value, str):
            sink.error(
                "validate.bad_id", _M_BAD_ID, anchor, part, id=_clip(value), limit=MAX_ID_LENGTH
            )
            return
        if value == "":
            sink.error("validate.empty_id", _M_EMPTY_ID, anchor, part)
            return
        first = self.ids.get(value)
        if first is None:
            self.ids[value] = (anchor, part, sink.window)
        else:
            first_anchor, first_part, first_window = first
            sink.error(
                "validate.duplicate_id",
                _M_DUPLICATE_ID,
                anchor,
                part,
                id=_clip(value),
                first=node_path(first_anchor, first_part, window=first_window),
            )
        if _ID_RE.fullmatch(value) is None:
            sink.error(
                "validate.bad_id", _M_BAD_ID, anchor, part, id=_clip(value), limit=MAX_ID_LENGTH
            )
        elif keyword.iskeyword(value):
            sink.error("validate.keyword_id", _M_KEYWORD_ID, anchor, part, id=value)
        elif value in RESERVED_IDS:
            sink.error("validate.reserved_id", _M_RESERVED_ID, anchor, part, id=value)

    def check_depth(self, node: object, depth: int, label: object) -> None:
        """R23: report once per subtree root that exceeds the nesting limit."""
        if depth == MAX_NESTING + 1:
            self.sink.error(
                "validate.too_deep", _M_TOO_DEEP, node, id=_clip(label), limit=MAX_NESTING
            )

    # ------------------------------------------------ the run
    def run(self) -> None:
        document = self.document
        sink = self.sink
        windows = document.children
        if not windows:
            sink.warning("validate.no_windows", _M_NO_WINDOWS, document)
        version = document.schema_version
        if not _schema_version_ok(version):
            sink.error(
                "validate.bad_schema_version",
                _M_BAD_SCHEMA_VERSION,
                document,
                version=_clip(version),
                current=CURRENT_SCHEMA_VERSION,
            )
        self.check_extras(document, "pyguibud-ui", document)
        meta = document.meta
        for attribute in ("generator", "source_locale", "i18n_domain", "theme"):
            self.chars(
                getattr(meta, attribute, None),
                document,
                "meta",
                attribute,
                required=attribute == "source_locale",
            )
        domain = getattr(meta, "i18n_domain", None)
        if (
            isinstance(domain, str)
            and domain != ""
            and (_DOMAIN_RE.fullmatch(domain) is None or ".." in domain)
        ):
            self.sink.error(
                "validate.bad_i18n_domain", _M_BAD_DOMAIN, document, "meta", value=_clip(domain)
            )
        locale = getattr(meta, "source_locale", None)
        if isinstance(locale, str) and LANGUAGE_CODE_RE.fullmatch(locale) is None:
            # R81: generated modules compare it with the requested language (QA-11-11).
            self.sink.error(
                "validate.bad_source_locale",
                _M_BAD_SOURCE_LOCALE,
                document,
                "meta",
                value=_clip(locale),
            )
        self.check_extras(meta, "meta", document, "meta")
        self.check_extras(document.resources_extra, "resources", document, "resources")
        self.check_extras(document.variables_extra, "variables", document, "variables")
        # Typed as object: a hand-built model may hold anything in these mappings.
        resources: dict[str, object] = dict(document.resources)
        variables: dict[str, object] = dict(document.variables)
        for key, image in resources.items():
            if isinstance(image, ImageResource):
                self.check_resource(image)
            else:
                self.bad_item(document, f"resources/image[{key}]", image, "ImageResource")
        for key, variable in variables.items():
            if isinstance(variable, Variable):
                self.check_variable(variable)
            else:
                self.bad_item(document, f"variables/var[{key}]", variable, "Variable")
        stack: list[_Item] = [(window, None, 2) for window in reversed(windows)]
        while stack:
            node, scope, depth = stack.pop()
            if isinstance(node, Window):
                self.visit_window(node, stack)
            elif isinstance(node, Widget):
                self.visit_widget(node, scope, depth, stack)
            elif isinstance(node, Include):
                self.visit_include(node, scope, depth)
            elif isinstance(node, Menubar):
                self.check_extras(node, "menubar", node)
                stack.extend((menu, None, depth + 1) for menu in reversed(node.children))
            elif isinstance(node, Menu):
                self.visit_menu(node, depth)
                stack.extend((child, None, depth + 1) for child in reversed(node.children))
            elif isinstance(node, Action):
                self.visit_action(node, depth)
            elif isinstance(node, MenuSeparator):
                self.check_depth(node, depth, "separator")
                self.check_extras(node, "separator", node)
            elif isinstance(node, Statusbar):
                self.visit_statusbar(node)

    # ------------------------------------------------ document level
    def check_resource(self, image: ImageResource) -> None:
        document = self.document
        part = f"resources/image[{image.id}]"
        self.check_id(document, image.id, part)
        self.check_path(document, part, image.id, image.src)
        src = image.src
        if isinstance(src, str) and src != "":
            if os.path.splitext(src)[1].lower() not in IMAGE_SUFFIXES:
                self.sink.error(
                    "validate.image_format", _M_IMAGE_FORMAT, document, part, src=_clip(src)
                )
            elif self.files is not None and not is_network_or_device_path(src):
                _probe_image(self.files, self.files.root, src, self.sink, document, part)
        self.check_extras(image, "image", document, part)

    def check_variable(self, variable: Variable) -> None:
        document = self.document
        part = f"variables/var[{variable.id}]"
        self.check_id(document, variable.id, part)
        default, kind = variable.default, variable.type
        self.check_choice(
            document, part, "validate.bad_variable_type", "type", kind, _VARIABLE_TYPES
        )
        if isinstance(default, str) and default != "":
            valid = True
            if kind == "int":
                valid = _INT_RE.fullmatch(default) is not None
            elif kind == "double":
                valid = _FLOAT_RE.fullmatch(default) is not None
            elif kind == "bool":
                valid = default in ("true", "false")
            if not valid:
                self.sink.error(
                    "validate.bad_variable_default",
                    _M_BAD_VARIABLE_DEFAULT,
                    document,
                    part,
                    default=_clip(default),
                    id=_clip(variable.id),
                    type=kind,
                )
            elif len(default) > MAX_DEFAULT_LENGTH:
                self.sink.error(
                    "validate.text_too_long",
                    _M_DEFAULT_TOO_LONG,
                    document,
                    part,
                    id=_clip(variable.id),
                    length=len(default),
                    limit=MAX_DEFAULT_LENGTH,
                )
        self.chars(default, document, part, "default")
        self.check_extras(variable, "var", document, part)

    def check_path(self, anchor: object, part: str, label: object, value: object) -> None:
        """R45 to R47, R54 and R82 for a ``src`` attribute."""
        sink = self.sink
        if not isinstance(value, str) or value == "":
            sink.error("validate.empty_path", _M_EMPTY_PATH, anchor, part, id=_clip(label))
            return
        self.chars(value, anchor, part, "src")
        if is_network_or_device_path(value):
            # R82 (QA-11-03): never opened, so the file rules skip it too.
            sink.error("validate.network_path", _M_NETWORK_PATH, anchor, part, path=_clip(value))
        elif _is_absolute(value):
            sink.warning(
                "validate.absolute_path", _M_ABSOLUTE_PATH, anchor, part, path=_clip(value)
            )
        elif _escapes(value):
            sink.warning("validate.path_escapes", _M_PATH_ESCAPES, anchor, part, path=_clip(value))

    # ------------------------------------------------ windows
    def visit_window(self, window: Window, stack: list[_Item]) -> None:
        sink = self.sink
        sink.window = window
        self.check_id(window, window.id)
        self.check_choice(
            window, "", "validate.bad_window_kind", "kind", window.kind, _WINDOW_KINDS
        )
        self.check_flag(window, "", "modal", window.modal)
        if window.kind == "main":
            if self.first_main is None:
                self.first_main = window
            else:
                sink.error(
                    "validate.multiple_main",
                    _M_MULTIPLE_MAIN,
                    window,
                    first=node_path(self.first_main),
                )
        if window.kind == "component" and (
            window.menubar is not None or window.statusbar is not None
        ):
            sink.error(
                "validate.component_chrome", _M_COMPONENT_CHROME, window, id=_clip(window.id)
            )
        if window.kind != "dialog":
            if window.modal:
                sink.warning(
                    "validate.dialog_only",
                    _M_DIALOG_ONLY,
                    window,
                    attribute="modal",
                    id=_clip(window.id),
                )
            if window.buttons is not None:
                sink.warning(
                    "validate.dialog_only",
                    _M_DIALOG_ONLY,
                    window,
                    attribute="buttons",
                    id=_clip(window.id),
                )
        for name in ("min_width", "min_height"):
            value = getattr(window, name)
            if value is not None:
                self.check_range(window, "", name, value, 0, MAX_PIXELS)
        if window.layout is None:
            sink.error("validate.layout_missing", _M_LAYOUT_MISSING, window, id=_clip(window.id))
        else:
            self.check_layout(window, window.layout)
        self.check_props(window, window.props, self.defs_of(WINDOW_PROPERTIES), "Window")
        self.chars(window.buttons, window, "", "buttons")
        if window.kind == "dialog" and isinstance(window.buttons, str):
            tokens = window.buttons.split(",")
            if len(set(tokens)) != len(tokens) or not set(tokens) <= set(_BUTTON_TOKENS):
                sink.error(
                    "validate.bad_buttons",
                    _M_BAD_BUTTONS,
                    window,
                    value=_clip(window.buttons),
                    choices=", ".join(_BUTTON_TOKENS),
                )
        self.shortcuts = {}
        self.check_extras(window, "window", window)
        scope = self.make_scope(window.id, "window", "layout", window.layout, None, window.children)
        stack.extend((child, scope, 3) for child in reversed(window.children))
        if window.statusbar is not None:
            stack.append((window.statusbar, None, 3))
        if window.menubar is not None:
            stack.append((window.menubar, None, 3))

    def make_scope(
        self,
        owner_id: object,
        class_name: str,
        kind: str | None,
        layout: Layout | None,
        core_name: str | None,
        children: Iterable[Widget | Include],
    ) -> _Scope:
        mode = "unknown"
        collisions: dict[int, tuple[object, int, int]] = {}
        if kind in ("none", "menu"):
            mode = "none"
        elif kind == "pages":
            mode = "pages"
        elif kind == "layout":
            mode = "nolayout"
            if layout is not None and layout.type == "grid":
                mode = "grid"
                collisions = _grid_collisions(children)
            elif layout is not None and layout.type == "pack":
                mode = "pack"
        return _Scope(
            owner_id=owner_id if isinstance(owner_id, str) else _clip(owner_id),
            class_name=class_name,
            mode=mode,
            core_name=core_name,
            collisions=collisions,
        )

    # ------------------------------------------------ layouts and placements
    def check_layout(self, owner: object, layout: Layout) -> None:
        sink = self.sink
        part = "layout"
        self.check_choice(
            owner, part, "validate.bad_layout_type", "type", layout.type, _LAYOUT_TYPES
        )
        self.check_choice(owner, part, "validate.bad_orient", "orient", layout.orient, _ORIENTS)
        self.check_range(owner, part, "padding", layout.padding, 0, MAX_PIXELS)
        self.check_range(owner, part, "gap", layout.gap, 0, MAX_PIXELS)
        grid_lines: tuple[tuple[str, object, str], ...] = (
            ("column", layout.columns, _M_DUPLICATE_COLUMN),
            ("row", layout.rows, _M_DUPLICATE_ROW),
        )
        for kind, lines, duplicate in grid_lines:
            seen: set[int] = set()
            if not isinstance(lines, tuple | list):
                self.bad_item(owner, part, lines, "tuple")
                continue
            for index, line in enumerate(lines):
                line_part = f"layout/{kind}[{index}]"
                if not isinstance(line, GridLine):
                    self.bad_item(owner, line_part, line, "GridLine")
                    continue
                # Tk configures one line more than it grids cells into (rowconfigure 9999).
                self.check_range(owner, line_part, "index", line.index, 0, MAX_GRID_INDEX + 1)
                self.check_range(owner, line_part, "weight", line.weight, 0, MAX_WEIGHT)
                self.check_range(owner, line_part, "minsize", line.minsize, 0, MAX_PIXELS)
                if type(line.index) is int:
                    if line.index in seen:
                        sink.error(
                            "validate.duplicate_grid_line",
                            duplicate,
                            owner,
                            line_part,
                            index=line.index,
                        )
                    seen.add(line.index)
                self.check_extras(line, kind, owner, line_part)
        if layout.type == "pack" and (layout.columns or layout.rows):
            sink.error("validate.grid_lines_on_pack", _M_GRID_LINES_ON_PACK, owner, part)
        if layout.type == "grid" and layout.orient == "horizontal":
            sink.warning("validate.orient_ignored", _M_ORIENT_IGNORED, owner, part)
        self.check_extras(layout, "layout", owner, part)

    def check_child_placement(self, node: Widget | Include, scope: _Scope) -> None:
        """R10, R14 to R16 and the values of the placement of a child."""
        sink = self.sink
        placement = node.placement
        label = _clip(node.id)
        if scope.mode == "none":
            sink.error(
                "validate.not_a_container",
                _M_NOT_CONTAINER,
                node,
                parent=scope.owner_id,
                class_name=scope.class_name,
                id=label,
            )
        expected = _EXPECTED.get(scope.mode)
        if expected is not None:
            if placement is None:
                sink.error(
                    "validate.placement_missing",
                    _M_PLACEMENT_MISSING,
                    node,
                    expected=f"<{expected}>",
                    id=label,
                    parent=scope.owner_id,
                )
            else:
                kind = _placement_kind(placement)
                if kind != expected:
                    sink.error(
                        "validate.placement_mismatch",
                        _M_PLACEMENT_MISMATCH,
                        node,
                        found=f"<{kind}>",
                        expected=f"<{expected}>",
                        id=label,
                        parent=scope.owner_id,
                    )
        collision = scope.collisions.get(id(node))
        if collision is not None:
            other, row, column = collision
            sink.error(
                "validate.grid_collision",
                _M_GRID_COLLISION,
                node,
                "cell",
                related=other,
                id=label,
                other=_clip(getattr(other, "id", "")),
                row=row,
                column=column,
            )
        if isinstance(placement, GridCell):
            self.check_cell(node, placement)
            self.check_extras(placement, "cell", node, "cell")
        elif isinstance(placement, PackPlacement):
            self.check_choice(node, "pack", "validate.bad_fill", "fill", placement.fill, _FILLS)
            self.check_flag(node, "pack", "expand", placement.expand)
            self.check_range(node, "pack", "padx", placement.padx, 0, MAX_PIXELS)
            self.check_range(node, "pack", "pady", placement.pady, 0, MAX_PIXELS)
            self.check_extras(placement, "pack", node, "pack")
        elif isinstance(placement, PagePlacement):
            self.check_page(node, placement, scope)
            self.check_extras(placement, "page", node, "page")

    def check_cell(self, node: object, cell: GridCell) -> None:
        part = "cell"
        self.check_range(node, part, "row", cell.row, 0, MAX_GRID_INDEX)
        self.check_range(node, part, "column", cell.column, 0, MAX_GRID_INDEX)
        row_limit = MAX_GRID_INDEX + 1
        column_limit = MAX_GRID_INDEX + 1
        if type(cell.row) is int and 0 <= cell.row <= MAX_GRID_INDEX:
            row_limit -= cell.row
        if type(cell.column) is int and 0 <= cell.column <= MAX_GRID_INDEX:
            column_limit -= cell.column
        self.check_range(node, part, "rowspan", cell.rowspan, 1, row_limit)
        self.check_range(node, part, "columnspan", cell.columnspan, 1, column_limit)
        if not isinstance(cell.sticky, str) or _STICKY_RE.fullmatch(cell.sticky) is None:
            self.sink.error(
                "validate.bad_sticky", _M_BAD_STICKY, node, part, value=_clip(cell.sticky)
            )
        self.check_range(node, part, "padx", cell.padx, 0, MAX_PIXELS)
        self.check_range(node, part, "pady", cell.pady, 0, MAX_PIXELS)

    def check_page(self, node: object, page: PagePlacement, scope: _Scope) -> None:
        sink = self.sink
        self.check_range(node, "page", "weight", page.weight, 0, MAX_WEIGHT)
        if scope.core_name == "Notebook" and page.weight != 0:
            sink.warning(
                "validate.page_attr_ignored",
                _M_PAGE_ATTR_IGNORED,
                node,
                "page",
                attribute="weight",
                class_name=scope.class_name,
            )
        if scope.core_name == "PanedWindow":
            for attribute, value in (("text", page.text), ("image", page.image)):
                if value is not None:
                    sink.warning(
                        "validate.page_attr_ignored",
                        _M_PAGE_ATTR_IGNORED,
                        node,
                        "page",
                        attribute=attribute,
                        class_name=scope.class_name,
                    )
        image = page.image
        if isinstance(image, str) and image != "" and image not in self.document.resources:
            sink.error(
                "validate.unknown_resource", _M_UNKNOWN_RESOURCE, node, "page", ref=_clip(image)
            )
        self.chars(page.image, node, "page", "image")
        text: object = page.text
        if text is not None and (not isinstance(text, Prop) or text.name != "text"):
            sink.error("validate.bad_page_text", _M_BAD_PAGE_TEXT, node, "page")
        if isinstance(text, Prop):
            self.check_prop(node, "page/prop[text]", text, _PAGE_TEXT, True, "Page")

    # ------------------------------------------------ widgets
    def visit_widget(
        self, widget: Widget, scope: _Scope | None, depth: int, stack: list[_Item]
    ) -> None:
        sink = self.sink
        self.check_id(widget, widget.id)
        self.check_depth(widget, depth, widget.id)
        if scope is not None:
            self.check_child_placement(widget, scope)
        effective = self.check_class(widget)
        spec = effective.spec
        kind = spec.children if spec is not None else None
        label = _clip(widget.id)
        class_label = _clip(widget.class_name)
        if widget.layout is not None:
            if kind in ("none", "menu"):
                sink.error(
                    "validate.layout_not_allowed",
                    _M_LAYOUT_NOT_ALLOWED,
                    widget,
                    "layout",
                    id=label,
                    class_name=class_label,
                )
            elif kind == "pages":
                sink.error(
                    "validate.layout_on_pages",
                    _M_LAYOUT_ON_PAGES,
                    widget,
                    "layout",
                    id=label,
                    class_name=class_label,
                )
            self.check_layout(widget, widget.layout)
        elif kind == "layout":
            sink.error("validate.layout_missing", _M_LAYOUT_MISSING, widget, id=label)
        defs = None if spec is None or effective.fallback_mode else self.defs_of(spec.properties)
        self.check_props(widget, widget.props, defs, class_label)
        self.check_events(widget, label, None if effective.fallback_mode else spec)
        self.check_bind(widget, effective)
        self.chars(widget.fallback, widget, "", "fallback")
        self.chars(widget.plugin, widget, "", "plugin")
        self.check_extras(widget, "widget", widget)
        child_scope = self.make_scope(
            widget.id,
            widget.class_name if isinstance(widget.class_name, str) else class_label,
            kind,
            widget.layout,
            effective.core_name,
            widget.children,
        )
        stack.extend((child, child_scope, depth + 1) for child in reversed(widget.children))

    def check_class(self, widget: Widget) -> _Effective:
        """R22 and R24 to R29: find the spec that governs the widget."""
        sink = self.sink
        name: object = widget.class_name  # object: a hand-built model may hold anything
        label = _clip(widget.id)
        if not isinstance(name, str):
            sink.error("validate.unknown_class", _M_UNKNOWN_CLASS, widget, class_name=_clip(name))
            return _Effective(None, False, None)
        registered = self.spec(name)
        if name in _STRUCTURAL or (registered is not None and registered.children == "menu"):
            sink.error("validate.structural_class", _M_STRUCTURAL_CLASS, widget, class_name=name)
            return _Effective(None, False, None)
        if not is_extension(name):
            if registered is None:
                sink.error(
                    "validate.unknown_class", _M_UNKNOWN_CLASS, widget, class_name=_clip(name)
                )
            for attribute in ("fallback", "plugin"):
                if getattr(widget, attribute) is not None:
                    sink.warning(
                        "validate.extension_attr_ignored",
                        _M_EXTENSION_ATTR_IGNORED,
                        widget,
                        attribute=attribute,
                        id=label,
                    )
            return _Effective(registered, False, _core_name(name, None))
        try:
            split_class_name(name)
        except ModelError:
            sink.error("validate.bad_class_name", _M_BAD_CLASS_NAME, widget, name=_clip(name))
        fallback = widget.fallback
        fallback_valid = False
        fallback_spec: WidgetSpec | None = None
        if fallback is None:
            sink.error(
                "validate.missing_fallback",
                _M_MISSING_FALLBACK,
                widget,
                id=label,
                class_name=_clip(name),
            )
        elif _core_name(fallback, None) is None:
            sink.error(
                "validate.bad_fallback",
                _M_BAD_FALLBACK,
                widget,
                fallback=_clip(fallback),
                id=label,
            )
        else:
            fallback_valid = True
            fallback_spec = self.spec(fallback)
        core = fallback if fallback_valid and isinstance(fallback, str) else None
        if registered is not None:
            if (
                fallback_spec is not None
                and fallback_valid
                and registered.container != fallback_spec.container
            ):
                sink.error(
                    "validate.fallback_mismatch",
                    _M_FALLBACK_MISMATCH,
                    widget,
                    fallback=_clip(fallback),
                    id=label,
                    class_name=_clip(name),
                )
            return _Effective(registered, False, core)
        if fallback_valid and fallback_spec is not None:
            plugin = widget.plugin
            if plugin:
                sink.warning(
                    "validate.plugin_missing",
                    _M_PLUGIN_MISSING,
                    widget,
                    class_name=_clip(name),
                    fallback=_clip(fallback),
                    plugin=_clip(plugin),
                )
            else:
                sink.warning(
                    "validate.plugin_missing",
                    _M_PLUGIN_MISSING_NAMELESS,
                    widget,
                    class_name=_clip(name),
                    fallback=_clip(fallback),
                )
            return _Effective(fallback_spec, True, core)
        return _Effective(None, False, core)

    def check_events(self, widget: Widget, label: str, spec: WidgetSpec | None) -> None:
        """R36 to R39. ``spec`` is None when event support cannot be judged."""
        sink = self.sink
        seen: set[str] = set()
        bound: list[frozenset[tuple[frozenset[str], str]]] = []  # the Tk keys of key: events
        events: object = widget.events  # object: a hand-built model may hold anything
        if not isinstance(events, list | tuple):
            self.bad_item(widget, "", events, "list")
            return
        for index, event in enumerate(events):
            part = f"event[{index}]"
            if not isinstance(event, Event):
                self.bad_item(widget, part, event, "Event")
                continue
            name = event.name
            if not isinstance(name, str) or not is_valid_event(name):
                sink.error("validate.bad_event", _M_BAD_EVENT, widget, part, name=_clip(name))
            else:
                if name.startswith("key:") and not keys.is_valid_key_sequence(name[4:]):
                    sink.error(
                        "validate.bad_key_sequence",
                        _M_BAD_KEY_SEQUENCE,
                        widget,
                        part,
                        value=_clip(name[4:]),
                    )
                if spec is not None:
                    supported = (
                        "focus_in" in spec.events
                        if name.startswith("key:")
                        else name in spec.events
                    )
                    if not supported:
                        sink.error(
                            "validate.unsupported_event",
                            _M_UNSUPPORTED_EVENT,
                            widget,
                            part,
                            class_name=_clip(widget.class_name),
                            name=_clip(name),
                        )
                # One chord in two spellings (key:Ctrl+S, key:<Control-s>) is one event too.
                keys_bound = keys.key_bindings(name[4:]) if name.startswith("key:") else None
                clash = keys_bound is not None and any(keys_bound & other for other in bound)
                if name in seen or clash:
                    sink.error(
                        "validate.duplicate_event",
                        _M_DUPLICATE_EVENT,
                        widget,
                        part,
                        name=_clip(name),
                        id=label,
                    )
                seen.add(name)
                if keys_bound:
                    bound.append(keys_bound)
            if not _is_identifier(event.handler):
                sink.error(
                    "validate.bad_handler",
                    _M_BAD_HANDLER,
                    widget,
                    part,
                    handler=_clip(event.handler),
                )
            self.chars(event.handler, widget, part, "handler")
            self.check_extras(event, "event", widget, part)

    def check_bind(self, widget: Widget, effective: _Effective) -> None:
        """R40 to R43."""
        sink = self.sink
        bind = widget.bind
        if bind is None:
            return
        if not _is_identifier(bind):
            sink.error("validate.bad_bind", _M_BAD_BIND, widget, bind=_clip(bind))
            return
        assert isinstance(bind, str)
        self.chars(bind, widget, "", "bind")
        variable = self.document.variables.get(bind)
        if variable is None:
            sink.error("validate.unknown_variable", _M_UNKNOWN_VARIABLE, widget, bind=bind)
            return
        row = BIND_TYPES.get(effective.core_name or "")
        if row is None:
            return
        if not row:
            sink.error(
                "validate.bind_not_supported",
                _M_BIND_NOT_SUPPORTED,
                widget,
                class_name=_clip(widget.class_name),
            )
        elif variable.type in row:
            if effective.core_name == "Radiobutton" and variable.type == "int":
                prop = widget.props.get("value")
                value: object = prop.value if isinstance(prop, Prop) else ""
                if not isinstance(value, str) or _INT_RE.fullmatch(value) is None:
                    sink.error(
                        "validate.bad_radio_value",
                        _M_BAD_RADIO_VALUE,
                        widget,
                        "prop[value]" if isinstance(prop, Prop) else "",
                        value=_clip(value),
                        id=_clip(widget.id),
                        bind=bind,
                    )
        else:
            sink.error(
                "validate.bind_type_mismatch",
                _M_BIND_TYPE_MISMATCH,
                widget,
                class_name=_clip(widget.class_name),
                type=variable.type,
                bind=bind,
                allowed=", ".join(row),
            )

    # ------------------------------------------------ includes
    def visit_include(self, include: Include, scope: _Scope | None, depth: int) -> None:
        sink = self.sink
        self.check_id(include, include.id)
        self.check_depth(include, depth, include.id)
        if scope is not None:
            self.check_child_placement(include, scope)
        self.check_path(include, "", include.id, include.src)
        if not _is_identifier(include.component):
            sink.error(
                "validate.bad_component",
                _M_BAD_COMPONENT,
                include,
                component=_clip(include.component),
            )
        self.chars(include.component, include, "", "component")
        self.check_extras(include, "include", include)

    # ------------------------------------------------ menus and status bar
    def visit_menu(self, menu: Menu, depth: int) -> None:
        self.check_id(menu, menu.id)
        self.check_depth(menu, depth, menu.id)
        self.check_chrome_props(menu, menu.props, "Menu")
        self.check_extras(menu, "menu", menu)

    def visit_action(self, action: Action, depth: int) -> None:
        self.check_id(action, action.id)
        self.check_depth(action, depth, action.id)
        if action.handler is not None and not _is_identifier(action.handler):
            self.sink.error(
                "validate.bad_handler", _M_BAD_HANDLER, action, handler=_clip(action.handler)
            )
        self.check_chrome_props(action, action.props, "Action")
        self.chars(action.handler, action, "", "handler")
        self.chars(action.shortcut, action, "", "shortcut")
        self.check_shortcut(action)
        self.check_extras(action, "action", action)

    def check_shortcut(self, action: Action) -> None:
        """R71 and R73 for the ``shortcut`` attribute of an action."""
        shortcut = action.shortcut
        if not isinstance(shortcut, str):
            return  # None is fine; other types are R62 (chars)
        problem = keys.shortcut_problem(shortcut)
        if problem is not None:
            msgid = _M_BAD_SHORTCUT if problem == "syntax" else _M_SHORTCUT_MODIFIER
            self.sink.error("validate.bad_shortcut", msgid, action, "", value=_clip(shortcut))
            return
        chord = keys.parse_chord(shortcut)
        assert chord is not None
        if chord.identity in self.shortcuts:
            window = self.sink.window
            self.sink.warning(
                "validate.duplicate_shortcut",
                _M_DUPLICATE_SHORTCUT,
                action,
                shortcut=keys.format_chord(chord),
                window=_clip(window.id) if window is not None else "",
            )
        else:
            self.shortcuts[chord.identity] = action

    def visit_statusbar(self, statusbar: Statusbar) -> None:
        self.check_id(statusbar, statusbar.id)
        self.check_chrome_props(statusbar, statusbar.props, "Statusbar")
        self.check_extras(statusbar, "statusbar", statusbar)

    def check_chrome_props(self, owner: object, props: Mapping[str, Prop], name: str) -> None:
        spec = self.spec(name)
        defs = None if spec is None else self.defs_of(spec.properties)
        self.check_props(owner, props, defs, name)

    # ------------------------------------------------ properties
    def check_props(
        self,
        owner: object,
        props: Mapping[str, Prop],
        defs: dict[str, PropertyDef] | None,
        class_name: str,
    ) -> None:
        """R30 to R35 and R54, with the properties visited sorted by name."""
        for key in sorted(props, key=str):
            prop: object = props[key]  # object: a hand-built model may hold anything
            if not isinstance(prop, Prop):
                self.bad_item(owner, f"prop[{key}]", prop, "Prop")
                continue
            name = prop.name if isinstance(prop.name, str) else str(prop.name)
            definition = None if defs is None else defs.get(name)
            if defs is not None and definition is None:
                self.sink.warning(
                    "validate.unknown_prop",
                    _M_UNKNOWN_PROP,
                    owner,
                    f"prop[{name}]",
                    class_name=class_name,
                    name=_clip(name),
                )
            self.check_prop(owner, f"prop[{name}]", prop, definition, defs is not None, class_name)

    def check_prop(
        self,
        owner: object,
        part: str,
        prop: Prop,
        definition: PropertyDef | None,
        typed: bool,
        class_name: str,
    ) -> None:
        sink = self.sink
        name = _clip(prop.name)
        value = prop.value
        if typed and definition is not None:
            self.check_value(owner, part, name, value, definition)
            if prop.translatable and not definition.translatable:
                sink.error("validate.not_translatable", _M_NOT_TRANSLATABLE, owner, part, name=name)
            if definition.type == "image":
                if not prop.ref or value != "":
                    sink.error(
                        "validate.image_needs_ref", _M_IMAGE_NEEDS_REF, owner, part, name=name
                    )
            elif prop.ref is not None:
                sink.error("validate.ref_not_allowed", _M_REF_NOT_ALLOWED, owner, part, name=name)
        ref = prop.ref
        if isinstance(ref, str) and ref != "" and ref not in self.document.resources:
            sink.error(
                "validate.unknown_resource", _M_UNKNOWN_RESOURCE, owner, part, ref=_clip(ref)
            )
        self.check_flag(owner, part, "translatable", prop.translatable)
        # The writer emits the name and the value through text(): None cannot be stored.
        self.chars(prop.name, owner, part, "name", required=True)
        self.chars(value, owner, part, required=True)
        self.chars(prop.ref, owner, part, "ref")
        self.chars(prop.context, owner, part, "context")
        self.chars(prop.comment, owner, part, "comment")
        self.check_extras(prop, "prop", owner, part)

    def check_value(
        self, owner: object, part: str, name: str, value: object, definition: PropertyDef
    ) -> None:
        """R31 and the numeric range of R09 for one property value."""
        sink = self.sink
        text = value if isinstance(value, str) else None
        kind = definition.type
        if kind == "int":
            if text is None or _INT_RE.fullmatch(text) is None:
                sink.error(
                    "validate.bad_prop_value",
                    _M_BAD_INT,
                    owner,
                    part,
                    name=name,
                    value=_clip(value),
                )
            else:
                self.check_range(
                    owner,
                    part,
                    name,
                    int(text),
                    definition.minimum,
                    definition.maximum,
                    shown=text,
                )
        elif kind == "float":
            if text is None or _FLOAT_RE.fullmatch(text) is None:
                sink.error(
                    "validate.bad_prop_value",
                    _M_BAD_FLOAT,
                    owner,
                    part,
                    name=name,
                    value=_clip(value),
                )
            else:
                self.check_range(
                    owner,
                    part,
                    name,
                    float(text),
                    definition.minimum,
                    definition.maximum,
                    whole=False,
                    shown=text,
                )
        elif kind == "bool":
            if text not in ("true", "false"):
                sink.error(
                    "validate.bad_prop_value",
                    _M_BAD_BOOL,
                    owner,
                    part,
                    name=name,
                    value=_clip(value),
                )
        elif kind == "enum":
            if text is None or text not in definition.choices:
                sink.error(
                    "validate.bad_prop_value",
                    _M_BAD_ENUM,
                    owner,
                    part,
                    name=name,
                    choices=", ".join(definition.choices),
                    value=_clip(value),
                )
        elif kind == "colour" and (problem := colour_problem(text)) is not None:
            msgid = _M_SYSTEM_COLOUR if problem == "system" else _M_BAD_COLOUR
            sink.error("validate.bad_prop_value", msgid, owner, part, name=name, value=_clip(value))
        elif kind == "string" and text is not None and len(text) > MAX_TEXT_LENGTH:
            sink.error(
                "validate.text_too_long",
                _M_TEXT_TOO_LONG,
                owner,
                part,
                name=name,
                length=len(text),
                limit=MAX_TEXT_LENGTH,
            )


# ---------------------------------------------------------------- include pass (R49 to R53)
@dataclass(slots=True)
class _Ctx:
    """One document taking part in the include pass."""

    key: str
    name: str  # file name shown in cycle chains
    windows: dict[str, Window]
    sink: _Sink  # findings about the includes *of this document*
    validated: tuple[Finding, ...] = ()  # the document's own findings (foreign files only)
    errors: int = 0


@dataclass(slots=True)
class _Frame:
    """The includes of one component being explored (an explicit stack replaces recursion)."""

    ctx: _Ctx
    includes: Iterator[Include]
    #: ``(file key, component id)`` of the component; None for a main or dialog window.
    kc: tuple[str, str] | None
    chain: tuple[tuple[str, str], ...]  # active components, for cycle detection
    level: int  # include levels above this frame (0 for windows of the root file)
    inst: int = 0  # widgets and includes instantiated by this component, nested ones included
    height: int = 0  # include levels below this component
    pending: Include | None = None  # the include whose child frame is on the stack


def _scan(window: Window) -> tuple[int, list[Include]]:
    """Count the widgets and includes below ``window`` and list its includes (pre-order)."""
    count = 0
    found: list[Include] = []
    stack: list[object] = list(reversed(window.children))
    while stack:
        node = stack.pop()
        if isinstance(node, Include):
            count += 1
            found.append(node)
        elif isinstance(node, Widget):
            count += 1
            stack.extend(reversed(node.children))
    return count, found


class _IncludePass:
    """R49 to R53 and the image rules of included files, with bounded work.

    Every file is read and validated once; every ``(file, component)`` is explored once and its
    depth and size are remembered, so a fan-out bomb (each level including the next ten times)
    costs one visit per component. Once a limit is hit nothing more is followed.
    """

    def __init__(
        self,
        document: Document,
        registry: WidgetLookup,
        sink: _Sink,
        files: FileAccess,
        limit: int | None,
    ) -> None:
        self.document = document
        self.registry = registry
        self.files = files
        self.limit = limit
        root = files.root
        self.root = _Ctx(
            key=root,
            name=os.path.basename(sink.source) or sink.source,
            windows=self._windows(document),
            sink=sink,
        )
        self.ctxs: dict[str, _Ctx] = {root: self.root}
        self.failed: dict[str, OSError | XmlIoError] = {}
        self.memo: dict[tuple[str, str], tuple[int, int]] = {}
        self.stopped = False

    @staticmethod
    def _windows(document: Document) -> dict[str, Window]:
        found: dict[str, Window] = {}
        for window in document.children:
            if isinstance(window, Window) and isinstance(window.id, str):
                found.setdefault(window.id, window)
        return found

    def run(self) -> None:
        windows: list[object] = list(self.document.children)  # a hand-built model may hold anything
        for window in windows:
            if self.stopped:
                break
            if not isinstance(window, Window):
                continue
            own, includes = _scan(window)
            kc: tuple[str, str] | None = None
            if window.kind == "component" and isinstance(window.id, str):
                kc = (self.root.key, window.id)
                if kc in self.memo:
                    continue  # already explored while following an include
            self.drive(
                _Frame(
                    ctx=self.root,
                    includes=iter(includes),
                    kc=kc,
                    chain=() if kc is None else (kc,),
                    level=0,
                    inst=own if kc is not None else 0,
                )
            )
        for ctx in list(self.ctxs.values())[1:]:
            self.root.sink.extend(ctx.validated)
            self.root.sink.extend(ctx.sink.findings)

    def drive(self, start: _Frame) -> None:
        stack = [start]
        while stack and not self.stopped:
            frame = stack[-1]
            include = next(frame.includes, None)
            if include is None:
                stack.pop()
                if frame.kc is not None:
                    self.memo[frame.kc] = (frame.height, frame.inst)
                if stack:
                    parent = stack[-1]
                    assert parent.pending is not None
                    self.add(parent, parent.pending, frame.height, frame.inst)
                continue
            child = self.enter(include, frame)
            if child is not None:
                frame.pending = include
                stack.append(child)

    def add(self, parent: _Frame, include: Include, height: int, nodes: int) -> None:
        """Account for a finished component below ``parent``."""
        parent.height = max(parent.height, 1 + height)
        parent.inst += nodes
        # A component explored on its own is not instantiated; its includer checks the size.
        standalone = parent.kc is not None and parent.level == 0
        if not standalone and parent.inst > MAX_EXPANDED_NODES:
            self.limit_hit(parent.ctx, include, _M_LIMIT_NODES, MAX_EXPANDED_NODES)

    def limit_hit(self, ctx: _Ctx, include: Include, msgid: str, limit: int) -> None:
        ctx.sink.error(
            "validate.include_limit", msgid, include, src=_clip(include.src), limit=limit
        )
        self.stopped = True

    def enter(self, include: Include, frame: _Frame) -> _Frame | None:
        """Check one include; return the frame to explore when its component is new."""
        ctx = frame.ctx
        src, component = include.src, include.component
        if (
            not isinstance(src, str)
            or src == ""
            or not _is_identifier(component)
            or is_network_or_device_path(src)
        ):
            return None  # already reported by R44/R45/R82
        if frame.level + 1 > MAX_INCLUDE_DEPTH:
            self.limit_hit(ctx, include, _M_LIMIT_DEPTH, MAX_INCLUDE_DEPTH)
            return None
        try:
            key = self.files.resolve(ctx.key, src)
        except OSError:
            ctx.sink.error("validate.include_missing", _M_INCLUDE_MISSING, include, src=_clip(src))
            return None
        target = self.load(include, ctx, key)
        if target is None:
            return None
        window = target.windows.get(component)
        if window is None:
            ctx.sink.error(
                "validate.include_not_component",
                _M_INCLUDE_NO_WINDOW,
                include,
                src=_clip(src),
                component=component,
            )
            return None
        if window.kind != "component":
            ctx.sink.error(
                "validate.include_not_component",
                _M_INCLUDE_NOT_COMPONENT,
                include,
                src=_clip(src),
                component=component,
            )
            return None
        kc = (key, component)
        if kc in frame.chain:
            loop = (*frame.chain[frame.chain.index(kc) :], kc)
            ctx.sink.error(
                "validate.include_cycle",
                _M_INCLUDE_CYCLE,
                include,
                src=_clip(src),
                component=component,
                chain=" → ".join(f"{self.ctxs[k].name}#{c}" for k, c in loop),
            )
            return None
        known = self.memo.get(kc)
        if known is not None:
            height, nodes = known
            if frame.level + 1 + height > MAX_INCLUDE_DEPTH:
                self.limit_hit(ctx, include, _M_LIMIT_DEPTH, MAX_INCLUDE_DEPTH)
            else:
                self.add(frame, include, height, nodes)
            return None
        own, includes = _scan(window)
        return _Frame(
            ctx=target,
            includes=iter(includes),
            kc=kc,
            chain=(*frame.chain, kc),
            level=frame.level + 1,
            inst=own,
        )

    def load(self, include: Include, ctx: _Ctx, key: str) -> _Ctx | None:
        """The context of the file ``key`` (read and validated once), or None after an error."""
        src = _clip(include.src)
        error = self.failed.get(key)
        target = self.ctxs.get(key)
        if error is None and target is None:
            if len(self.ctxs) >= MAX_INCLUDE_FILES:
                self.limit_hit(ctx, include, _M_LIMIT_FILES, MAX_INCLUDE_FILES)
                return None
            try:
                target = self.open(key, self.files.read(key))
            except (OSError, XmlIoError) as exc:
                self.failed[key] = error = exc
        if error is not None:
            if isinstance(error, XmlIoError):
                ctx.sink.error(
                    "validate.include_invalid",
                    _M_INCLUDE_UNREADABLE,
                    include,
                    src=src,
                    reason=LazyMessage(error.msgid, **error.params),
                )
            else:
                ctx.sink.error("validate.include_missing", _M_INCLUDE_MISSING, include, src=src)
            return None
        assert target is not None
        if target.errors:
            ctx.sink.error(
                "validate.include_invalid",
                _M_INCLUDE_ERRORS,
                include,
                src=src,
                count=target.errors,
            )
            return None
        return target

    def open(self, key: str, result: ReadResult) -> _Ctx:
        """Validate a newly read file once and probe its images."""
        report = validate(
            result.document,
            self.registry,
            source=result.source,
            positions=result.positions,
            limit=self.limit,
        )
        sink = _Sink(result.source, result.positions, None)
        for image in result.document.resources.values():
            src = image.src
            if (
                isinstance(image, ImageResource)
                and isinstance(src, str)
                and os.path.splitext(src)[1].lower() in IMAGE_SUFFIXES
                and not is_network_or_device_path(src)  # R82 in its own validation
            ):
                part = f"resources/image[{image.id}]"
                _probe_image(self.files, key, src, sink, result.document, part)
        ctx = _Ctx(
            key=key,
            name=os.path.basename(result.source) or result.source,
            windows=self._windows(result.document),
            sink=sink,
            validated=report.findings,
            errors=len(report.errors) + len(sink.findings),
        )
        self.ctxs[key] = ctx
        return ctx
