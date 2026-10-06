"""Generation-time plan (spec ``docs/specs/codegen.md`` 5): documents, includes, images, locales.

Everything is read through the ``DiskFiles`` instance the validator used, so a file is read once
and the plan sees exactly what was validated. Numbers are given by first use in traversal order,
never by file key, so the output does not depend on paths or hash seeds.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from pyguibud.codegen._errors import M_IMAGE_CHANGED, M_LOCALE_FALLBACK, CodegenError
from pyguibud.core.diagnostics import Finding
from pyguibud.core.files import MAX_IMAGE_BYTES, DiskFiles, probe_bytes
from pyguibud.core.model import Document, Include, Window

__all__ = ["DocInfo", "ImageData", "Plan"]

_FORMATS = {".png": "png", ".gif": "gif", ".ppm": "ppm", ".pgm": "ppm"}


@dataclass(frozen=True, slots=True, eq=False)
class DocInfo:
    """One ``.ui`` file taking part in the generated module (``_DOCS[index]``)."""

    index: int
    key: str
    source: str  # the path shown in findings
    document: Document


@dataclass(frozen=True, slots=True)
class ImageData:
    """One embedded image (``_IMG_<number>``)."""

    number: int
    data: bytes
    fmt: str


class Plan:
    """Lazily numbered documents, components and images of one generation."""

    def __init__(self, files: DiskFiles, document: Document, source: str, output: str) -> None:
        self._files = files
        self._output_dir = os.path.realpath(os.path.dirname(os.path.abspath(output)))
        self.docs: list[DocInfo] = []
        self._by_key: dict[str, DocInfo] = {}
        self.components: dict[tuple[str, str], int] = {}
        self.images: list[ImageData] = []
        self._image_numbers: dict[tuple[int, str], int] = {}
        self.warnings: list[Finding] = []
        self.top = self._doc(files.root, document, source)

    def _doc(self, key: str, document: Document, source: str) -> DocInfo:
        found = self._by_key.get(key)
        if found is None:
            found = DocInfo(len(self.docs), key, source, document)
            self.docs.append(found)
            self._by_key[key] = found
        return found

    def include(self, doc: DocInfo, node: Include) -> tuple[DocInfo, Window, bool]:
        """The document and component window of ``node``, and whether variables are shared."""
        files = self._files
        target = files.resolve(doc.key, node.src)
        included = files.read(target).document
        component = next(w for w in included.children if w.id == node.component)
        return self._doc(target, included, files.path_of(target)), component, target == doc.key

    def component(self, doc: DocInfo, window: Window) -> tuple[int, bool]:
        """The method number of a component, and True the first time it is seen."""
        key = (doc.key, window.id)
        number = self.components.get(key)
        if number is not None:
            return number, False
        number = self.components[key] = len(self.components)
        return number, True

    def image(self, doc: DocInfo, image_id: str) -> int:
        """The constant number of an image; the file is read once and its bytes re-checked."""
        key = (doc.index, image_id)
        number = self._image_numbers.get(key)
        if number is not None:
            return number
        src = doc.document.resources[image_id].src
        suffix = os.path.splitext(src)[1].lower()
        try:
            path = self._files.path_of(self._files.resolve(doc.key, src))
            with open(path, "rb") as stream:
                data = stream.read(MAX_IMAGE_BYTES + 1)
        except OSError as exc:
            raise CodegenError("codegen.image_changed", M_IMAGE_CHANGED, src=src) from exc
        if suffix not in _FORMATS or probe_bytes(data, suffix).status != "ok":
            raise CodegenError("codegen.image_changed", M_IMAGE_CHANGED, src=src)
        number = self._image_numbers[key] = len(self.images)
        self.images.append(ImageData(number, data, _FORMATS[suffix]))
        return number

    def locale_dir(self, doc: DocInfo, output: str) -> str:
        """``<ui dir>/locale`` relative to the output folder, in POSIX form (decision C4)."""
        folder = os.path.join(os.path.dirname(self._files.path_of(doc.key)), "locale")
        try:
            relative = os.path.relpath(folder, self._output_dir)
        except ValueError:  # another drive
            self.warnings.append(
                Finding(
                    code="codegen.locale_fallback",
                    msgid=M_LOCALE_FALLBACK,
                    params={"path": doc.source, "output": output},
                    source=doc.source,
                )
            )
            return "locale"
        return relative.replace(os.sep, "/")
