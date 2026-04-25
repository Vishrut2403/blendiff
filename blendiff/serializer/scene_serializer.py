from __future__ import annotations

import math
from typing import Any

_FLOAT_PRECISION = 6


class SceneSerializer:
	"""Convert a raw scene dict into a JSON-safe SerializedScene dict."""

	def __init__(self, float_precision: int = _FLOAT_PRECISION) -> None:
		self._precision = float_precision

	def serialize(self, raw: dict) -> dict:
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
			"render": self._serialize_render(raw.get("render", {})),
		}

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
			"camera_data":     obj.get("camera_data"),
			"light_data":      obj.get("light_data"),
			"mesh_data":       obj.get("mesh_data"),   # already plain primitives
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
			"node_graph": slot.get("node_graph"),
		}
		return result

	def _serialize_render(self, render: dict) -> dict:
		if not render:
			return {}
		return {
			"engine":                str(render.get("engine", "")),
			"resolution_x":         int(render.get("resolution_x", 1920)),
			"resolution_y":         int(render.get("resolution_y", 1080)),
			"resolution_percentage":int(render.get("resolution_percentage", 100)),
			"filepath":             str(render.get("filepath", "")),
			"file_format":          str(render.get("file_format", "PNG")),
			"color_mode":           str(render.get("color_mode", "RGBA")),
			"color_depth":          str(render.get("color_depth", "8")),
			"frame_start":          int(render.get("frame_start", 1)),
			"frame_end":            int(render.get("frame_end", 250)),
			"frame_step":           int(render.get("frame_step", 1)),
			"fps":                  int(render.get("fps", 24)),
			"fps_base":             float(render.get("fps_base", 1.0)),
			"display_device":       str(render.get("display_device", "sRGB")),
			"view_transform":       str(render.get("view_transform", "Filmic")),
			"look":                 str(render.get("look", "None")),
			"exposure":             float(render.get("exposure", 0.0)),
			"gamma":                float(render.get("gamma", 1.0)),
			"cycles":               dict(render.get("cycles", {})),
			"eevee":                dict(render.get("eevee", {})),
		}

	def _serialize_collection(self, col: dict) -> dict:
		return {
			"name":     col["name"],
			"path":     col["path"],
			"children": list(col.get("children", [])),
			"objects":  list(col.get("objects", [])),
		}

	def _vec_to_list(self, value: Any) -> list[float]:
		try:
			components = list(value)
		except TypeError:
			components = [value]
		return [self._round(c) for c in components]

	def _round(self, value: Any) -> float:
		try:
			f = float(value)
		except (TypeError, ValueError):
			return 0.0
		if math.isnan(f) or math.isinf(f):
			return 0.0
		return round(f, self._precision)