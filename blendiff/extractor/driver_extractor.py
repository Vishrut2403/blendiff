from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _extract_variable(var: Any) -> dict:
	"""Extract a single driver variable."""
	targets = []
	for t in var.targets:
		targets.append({
			"id_type":       getattr(t, "id_type", None),
			"data_path":     getattr(t, "data_path", ""),
			"bone_target":   getattr(t, "bone_target", ""),
			"transform_type": getattr(t, "transform_type", None),
			"transform_space": getattr(t, "transform_space", None),
		})
	return {
		"name":    var.name,
		"type":    var.type,   # SINGLE_PROP, TRANSFORMS, ROTATION_DIFF, LOC_DIFF
		"targets": targets,
	}


def _extract_driver(fc: Any) -> dict:
	"""Extract summary data from a single driven FCurve."""
	drv = fc.driver
	variables = []
	for var in drv.variables:
		try:
			variables.append(_extract_variable(var))
		except Exception as exc:
			log.debug("Could not extract driver variable %r: %s", var.name, exc)

	return {
		"data_path":   fc.data_path,
		"array_index": fc.array_index,
		"driver_type": drv.type,          # AVERAGE, SUM, SCRIPTED, MIN, MAX
		"expression":  drv.expression if drv.type == "SCRIPTED" else "",
		"use_self":    getattr(drv, "use_self", False),
		"variables":   variables,
	}


def _iter_driven_fcurves(obj: Any):

	try:
		anim = obj.animation_data
		if anim is None:
			return
		for fc in anim.drivers:
			yield fc
	except Exception as exc:
		log.debug("Could not access drivers for %r: %s", obj.name, exc)


def extract_drivers(obj: Any) -> list[dict]:

	result = []
	for fc in _iter_driven_fcurves(obj):
		try:
			result.append(_extract_driver(fc))
		except Exception as exc:
			log.warning(
				"Failed to extract driver %r[%d] on %r: %s",
				fc.data_path, fc.array_index, obj.name, exc,
			)

	result.sort(key=lambda x: (x["data_path"], x["array_index"]))
	return result