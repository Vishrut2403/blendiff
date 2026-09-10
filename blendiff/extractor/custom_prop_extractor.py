from __future__ import annotations

import logging
from typing import Any

from .identity import ID_KEY

from .coerce import to_jsonable

log = logging.getLogger(__name__)

# Keys to always skip. These are Blender internals or BlenDiff's own
# bookkeeping — not user data — and reporting them as custom-property changes
# would be noise. ID_KEY in particular is written by BlenDiff itself, so
# surfacing it would make every newly stamped object look edited.
_SKIP_KEYS = {
	"_RNA_UI",
	"cycles",
	"cycles_visibility",
	ID_KEY,
}


def _is_serializable(val: Any) -> bool:
	"""Return True if val can be round-tripped through JSON safely."""
	if val is None:
		return True
	if isinstance(val, (bool, int, float, str)):
		return True
	if isinstance(val, (list, tuple)):
		return all(_is_serializable(v) for v in val)
	if isinstance(val, dict):
		return all(isinstance(k, str) and _is_serializable(v) for k, v in val.items())
	return False


def _coerce(val: Any) -> Any:

	# Handles IDPropertyArray, and mathutils types whose lack of __iter__
	# previously let them through unconverted.
	return to_jsonable(val)


def extract_custom_props(obj: Any) -> dict[str, Any]:

	result: dict[str, Any] = {}

	for key in obj.keys():
		if key in _SKIP_KEYS:
			continue
		try:
			raw = obj[key]
			coerced = _coerce(raw)
			if _is_serializable(coerced):
				result[key] = coerced
			else:
				log.debug("Skipping non-serializable custom prop %r on %r", key, obj.name)
		except Exception as exc:
			log.warning("Failed to read custom prop %r on %r: %s", key, obj.name, exc)

	return result