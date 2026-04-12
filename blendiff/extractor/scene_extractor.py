"""
blendiff.extractor.scene_extractor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Reads the active Blender scene via `bpy` and produces a raw Python
dictionary that mirrors the SerializedScene schema (but still contains
mathutils types — that is the Serializer's job to clean up).

Design decisions
----------------
* SceneExtractor is a stateless class with class-methods.
  No __init__ needed; nothing is stored between calls.
* Each extract_* method is independently testable — call only what you need.
* If a property is missing or raises an exception (e.g. a corrupted
  data-block), we catch it, log a warning, and substitute a safe default.
  We never crash the whole extraction for one bad object.
* Collection hierarchy is walked recursively to capture any depth.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class SceneExtractor:
	"""Extract structured scene data from the active Blender scene."""

	# Public API

	@classmethod
	def extract(cls, context: Any) -> dict:
		"""
		Full scene extraction.

		Parameters
		----------
		context:
			A ``bpy.context``-like object with a ``scene`` attribute.

		Returns
		-------
		dict
			Raw scene dict.  Keys match SerializedScene field names.
			Values may still contain mathutils types.
		"""
		import bpy  # local import keeps module importable outside Blender

		scene = context.scene
		version = bpy.app.version_string

		return {
			"blender_version": version,
			"scene_name":      scene.name,
			"objects":         cls._extract_all_objects(scene),
			"collections":     cls._extract_collection_tree(scene.collection),
		}

	# Object extraction

	@classmethod
	def _extract_all_objects(cls, scene: Any) -> dict[str, dict]:
		"""Return a dict keyed by object name."""
		result: dict[str, dict] = {}
		for obj in scene.objects:
			try:
				data = cls._extract_object(obj)
				result[obj.name] = data
			except Exception as exc:
				log.warning("Failed to extract object %r: %s", obj.name, exc)
		return result

	@classmethod
	def _extract_object(cls, obj: Any) -> dict:
		"""Extract a single bpy.types.Object."""
		return {
			"name":             obj.name,
			"type":             obj.type,
			"collection_path":  cls._collection_path(obj),
			"transform":        cls._extract_transform(obj),
			"material_slots":   cls._extract_material_slots(obj),
			"visible":          not obj.hide_viewport,
		}

	@classmethod
	def _extract_transform(cls, obj: Any) -> dict:
		"""
		Extract world-space transform.

		We use world_matrix decompose() so the values are consistent
		regardless of parenting.  Returns mathutils types — Serializer
		converts them to lists.
		"""
		loc, rot, scale = obj.matrix_world.decompose()
		return {
			"location":       loc,
			"rotation_euler": rot.to_euler(),   # convert quaternion → Euler
			"scale":          scale,
		}

	@classmethod
	def _extract_material_slots(cls, obj: Any) -> list[dict]:
		slots = []
		for i, slot in enumerate(obj.material_slots):
			mat = slot.material
			slots.append({
				"index":     i,
				"name":      mat.name if mat else None,
				"use_nodes": mat.use_nodes if mat else None,
			})
		return slots

	# Collection extraction

	@classmethod
	def _extract_collection_tree(
		cls,
		collection: Any,
		parent_path: str = "",
	) -> dict[str, dict]:
		"""
		Recursively walk the collection hierarchy.

		Returns a flat dict keyed by full collection path so the caller
		can look up any collection in O(1) without walking the tree again.
		"""
		result: dict[str, dict] = {}
		cls._walk_collection(collection, parent_path, result)
		return result

	@classmethod
	def _walk_collection(
		cls,
		collection: Any,
		parent_path: str,
		accumulator: dict[str, dict],
	) -> None:
		path = (
			f"{parent_path}/{collection.name}"
			if parent_path
			else collection.name
		)
		node = {
			"name":     collection.name,
			"path":     path,
			"children": [c.name for c in collection.children],
			"objects":  [o.name for o in collection.objects],
		}
		accumulator[path] = node
		for child in collection.children:
			cls._walk_collection(child, path, accumulator)

	# Helpers

	@classmethod
	def _collection_path(cls, obj: Any) -> str:
		"""
		Return the path of the *first* collection that directly contains obj.

		Blender objects can live in multiple collections, but for diff
		purposes we track the primary one.  If none found, return "".
		"""
		for col in obj.users_collection:
			return col.name
		return ""
