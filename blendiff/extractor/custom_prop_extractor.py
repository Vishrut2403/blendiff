from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# bpy internal keys to always skip — these are Blender internals, not user data
_SKIP_KEYS = {
	"_RNA_UI",
	"cycles",
	"cycles_visibility",
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

	if val is None or isinstance(val, (bool, int, float, str)):
		return val
	# IDPropertyArray (int[], float[]) — iterate to list
	if hasattr(val, "__iter__") and not isinstance(val, (str, dict)):
		try:
			items = [_coerce(v) for v in val]
			return items
		except Exception:
			pass
	return str(val)


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