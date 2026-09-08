from __future__ import annotations

import logging
from typing import Any

from .custom_prop_extractor import _coerce, _is_serializable
from .identity import ID_KEY

log = logging.getLogger(__name__)

_SKIP_KEYS = {
	"_RNA_UI",
	"cycles",
	"cycles_curves",
	"unit_settings",
	ID_KEY,
}


def extract_scene_custom_props(scene: Any) -> dict:

	try:
		result = {}
		for key in scene.keys():
			if key in _SKIP_KEYS:
				continue
			try:
				raw = scene[key]
				coerced = _coerce(raw)
				if _is_serializable(coerced):
					result[key] = coerced
				else:
					log.debug("Skipping non-serializable scene prop %r", key)
			except Exception as exc:
				log.warning("Failed to read scene custom prop %r: %s", key, exc)
		return result
	except Exception as exc:
		log.warning("Failed to extract scene custom props: %s", exc)
		return {}