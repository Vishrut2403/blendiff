"""
blendiff.extractor.coerce
~~~~~~~~~~~~~~~~~~~~~~~~~~
Turning Blender values into JSON-safe Python.

The bug this exists to prevent
------------------------------
Three extractors independently guarded their conversion with::

    if hasattr(val, "__iter__") and not isinstance(val, str):
        return list(val)

That guard is wrong for exactly the types it most needs to catch. Every
``mathutils`` type implements the old sequence protocol (``__len__`` and
``__getitem__``) and **none of them expose ``__iter__``**::

    Vector      __iter__=False   list()=ok
    Color       __iter__=False   list()=ok
    Euler       __iter__=False   list()=ok
    Quaternion  __iter__=False   list()=ok
    Matrix      __iter__=False   list()=ok

So a ``Vector`` sailed through unconverted, and ``json.dumps`` refused it when
the sidecar was written. The failure mode was not a wrong value or a phantom
diff: snapshot capture raised ``TypeError`` and produced nothing at all. An
Array modifier with a relative offset was enough to trigger it, which is an
entirely ordinary thing for a scene to contain.

It went unnoticed because every test fixture built its modifiers with plain
Python floats. It surfaced the first time BlenDiff ran on a .blend a person
had actually authored.

The rule here
-------------
Never ask a value what protocol it supports. Try to convert it and see.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

#: Types that are already JSON-safe and must not be treated as sequences.
_SCALARS = (bool, int, float, str, type(None))

#: How deep to follow nested sequences before giving up. Matrices are
#: sequences of rows, so two levels are normal; anything deeper is more likely
#: a cycle or an exotic type than real data.
_MAX_DEPTH = 6


def to_jsonable(value: Any, _depth: int = 0) -> Any:
    """
    Convert a Blender value into something ``json.dumps`` accepts.

    Scalars pass through. Anything sequence-like, including every mathutils
    type, becomes a list, recursively. Dicts are converted by value. Anything
    that resists conversion becomes its ``str()``, because losing fidelity on
    one exotic field is a far better outcome than failing the whole snapshot.
    """
    if isinstance(value, _SCALARS):
        return value

    if _depth >= _MAX_DEPTH:
        return str(value)

    if isinstance(value, dict):
        return {str(k): to_jsonable(v, _depth + 1) for k, v in value.items()}

    # The important line: attempt the conversion rather than interrogating the
    # object about which protocol it implements.
    try:
        items = list(value)
    except TypeError:
        return str(value)
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("Could not convert %r: %s", type(value).__name__, exc)
        return str(value)

    return [to_jsonable(item, _depth + 1) for item in items]


def is_jsonable(value: Any) -> bool:
    """
    True when a value can be written to the sidecar as-is.

    Used by the serializer's safety net and asserted in the tests, so that a
    leak is caught where it happens rather than at ``json.dumps`` time with no
    indication of which field is at fault.
    """
    if isinstance(value, _SCALARS):
        return True
    if isinstance(value, list):
        return all(is_jsonable(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and is_jsonable(v) for k, v in value.items())
    return False
