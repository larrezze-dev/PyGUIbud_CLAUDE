"""Upgrade chain for ``.ui`` files written with an older schema version (ADR-002).

Each step lives in its own module, ``m<from>_to_<to>.py`` (for example ``m1_0_to_1_1.py``),
exposes ``migrate(root) -> (root, "1.1")`` and is registered in :data:`MIGRATIONS` under its
from-version. Steps work on the element tree before it is mapped to the model; elements they
create have no source position.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Final, TypeAlias

from pyguibud.core.errors import XmlIoError
from pyguibud.core.schema import CURRENT_SCHEMA_VERSION, parse_version
from pyguibud.i18n import N_

__all__ = ["MIGRATIONS", "Migration", "migrate"]

Migration: TypeAlias = Callable[[ET.Element], tuple[ET.Element, str]]

#: Registered steps keyed by from-version, e.g. ``"1.0"``. Empty while 1.0 is the only version.
MIGRATIONS: Final[Mapping[str, Migration]] = MappingProxyType({})


def migrate(
    root: ET.Element,
    version: str,
    *,
    source: str,
    registry: Mapping[str, Migration] | None = None,
) -> tuple[ET.Element, str, tuple[str, ...]]:
    """Upgrade ``root`` from ``version`` to :data:`CURRENT_SCHEMA_VERSION`.

    Args:
        root: the root element; steps may edit it in place or return a new one.
        version: the schema version written in the file.
        source: file name used in error locations.
        registry: the steps to use; None reads :data:`MIGRATIONS` at call time.

    Returns:
        The new root, the final version and the from-version of every step applied.

    Raises:
        XmlIoError: ``xml.no_migration`` or ``xml.bad_migration``. Any other exception raised
            by a step is a bug and propagates.
    """
    steps = MIGRATIONS if registry is None else registry
    current = parse_version(CURRENT_SCHEMA_VERSION)
    passed: list[str] = []
    while version != CURRENT_SCHEMA_VERSION:
        step = steps.get(version)
        if step is None:
            raise XmlIoError(
                "xml.no_migration",
                # Translators: {version} and {current} are schema versions such as 1.0.
                N_("Schema version {version} cannot be upgraded to {current}."),
                source=source,
                version=version,
                current=CURRENT_SCHEMA_VERSION,
            )
        root, result = step(root)
        old, new = parse_version(version), parse_version(result)
        # The result must advance and must not overshoot: this rules out loops.
        if old is None or new is None or current is None or not old < new <= current:
            raise XmlIoError(
                "xml.bad_migration",
                # Translators: {version} is a schema version; {result} is what the upgrade
                # produced instead of a valid newer version.
                N_(
                    "The upgrade from schema version {version} failed: "
                    "it produced version '{result}'."
                ),
                source=source,
                version=version,
                result=result,
            )
        passed.append(version)
        version = result
    return root, version, tuple(passed)
