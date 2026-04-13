"""
blendiff.serializer.scene_serializer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Converts the raw Python dict produced by SceneExtractor into a fully
JSON-serialisable dict.

Responsibilities
----------------
* Convert mathutils types (Vector, Euler, Quaternion) to list[float].
* Round floats to a configurable number of decimal places (default 6)
  to avoid meaningless diff noise from floating-point precision.
* Guarantee that all values are: str, int, float, bool, None, list, or dict.
* Return a dict that matches the SerializedScene dataclass schema.

What this module is NOT responsible for
-----------------------------------------
* Knowing anything about Blender internals (no bpy imports).
* Validating semantic correctness — if the extractor gives us garbage,
  we serialise the garbage; validation is a separate concern.
"""

from __future__ import annotations

import math
from typing import Any
from unittest import result

# Number of decimal places used when rounding float components.
# Increase for higher precision; decrease to reduce noise in large scenes.
_FLOAT_PRECISION = 6


class SceneSerializer:
	"""Convert a raw scene dict into a JSON-safe SerializedScene dict."""

	def __init__(self, float_precision: int = _FLOAT_PRECISION) -> None:
		self._precision = float_precision

	# Public API

	def serialize(self, raw: dict) -> dict:
		"""
		Normalise a raw scene dict (as returned by SceneExtractor).

		Parameters
		----------
		raw:
			Dict with keys: blender_version, scene_name, objects, collections.

		Returns
		-------
		dict
			Fully JSON-serialisable dict.
		"""
		return {
			"blender_version": raw["blender_version"],
			"scene_name":      raw["scene_name"],
			"objects":         {
				name: self._serialize_object(obj_data)
				for name, obj_data in raw.get("objects", {}).items()
			},
			"collections": {
				path: self._serialize_collection(col_data)
				for path, col_data in raw.get("collections", {}).items()
			},
		}

	# Object serialization

	def _serialize_object(self, obj: dict) -> dict:
		return {
			"name":            obj["name"],
			"type":            obj["type"],
			"collection_path": obj["collection_path"],
			"transform":       self._serialize_transform(obj["transform"]),
			"material_slots":  [
				self._serialize_material_slot(s)
				for s in obj.get("material_slots", [])
			],
			"visible":         bool(obj.get("visible", True)),
		}

	def _serialize_transform(self, t: dict) -> dict:
		return {
			"location":       self._vec_to_list(t["location"]),
			"rotation_euler": self._vec_to_list(t["rotation_euler"]),
			"scale":          self._vec_to_list(t["scale"]),
		}

	def _serialize_material_slot(self, slot: dict) -> dict:
		result = {
			"index":     int(slot["index"]),
			"name":      slot["name"],
			"use_nodes": slot["use_nodes"],
			"node_graph": slot.get("node_graph"),  # None when no nodes
		}
		return result

	# Collection serialization

	def _serialize_collection(self, col: dict) -> dict:
		return {
			"name":     col["name"],
			"path":     col["path"],
			"children": list(col.get("children", [])),
			"objects":  list(col.get("objects", [])),
		}

	# Type normalisation helpers

	def _vec_to_list(self, value: Any) -> list[float]:
		"""
		Convert any vector-like object (mathutils.Vector, Euler, list,
		tuple) to a list of rounded floats.

		Handles:
		- mathutils.Vector / Euler / Quaternion  (iterable, len 3 or 4)
		- Plain Python list / tuple
		- A single float (length-1 vector)
		"""
		try:
			components = list(value)
		except TypeError:
			# Scalar fallback
			components = [value]

		return [self._round(c) for c in components]

	def _round(self, value: Any) -> float:
		"""Round a numeric value; handle NaN/Inf gracefully."""
		try:
			f = float(value)
		except (TypeError, ValueError):
			return 0.0
		if math.isnan(f) or math.isinf(f):
			return 0.0
		return round(f, self._precision)
