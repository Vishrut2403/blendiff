from __future__ import annotations

import logging
from typing import Any

from .render_extractor import extract_render_settings
from .camera_light_extractor import extract_camera_data, extract_light_data
from .mesh_extractor import extract_mesh_data
from .world_extractor import extract_world_data
from .modifier_extractor import extract_modifier_stack
from .parent_extractor import extract_parent_info
from .material_extractor import MaterialExtractor
from .constraint_extractor import extract_constraint_stack
from .custom_prop_extractor import extract_custom_props

log = logging.getLogger(__name__)


class SceneExtractor:
	"""Extract structured scene data from the active Blender scene."""

	# Public API

	@classmethod
	def extract(cls, context: Any) -> dict:
		
		import bpy  # local import keeps module importable outside Blender

		scene = context.scene
		version = bpy.app.version_string

		return {
			"blender_version": version,
			"scene_name":      scene.name,
			"objects":         cls._extract_all_objects(scene),
			"collections":     cls._extract_collection_tree(scene.collection),
			"render":          extract_render_settings(scene),
			"world":           extract_world_data(scene),
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
		obj_type = obj.type

		data = {
			"name":            obj.name,
			"type":            obj_type,
			"collection_path": cls._collection_path(obj),
			"transform":       cls._extract_transform(obj),
			"material_slots":  cls._extract_material_slots(obj),
			"visible":         not obj.hide_viewport,
			"parent":          None,
			"camera_data":     None,
			"light_data":      None,
			"mesh_data":       None,
			"modifier_stack":  [],
			"constraint_stack":  [],
			"custom_props":      {},
		}

		# Modifiers exist on all object types
		try:
			data["modifier_stack"] = extract_modifier_stack(obj)
		except Exception as exc:
			log.warning("Failed to extract modifiers for %r: %s", obj.name, exc)

		try:
			data["constraint_stack"] = extract_constraint_stack(obj)
		except Exception as exc:
			log.warning("Failed to extract constraints for %r: %s", obj.name, exc)

		try:
			data["custom_props"] = extract_custom_props(obj)
		except Exception as exc:
			log.warning("Failed to extract custom props for %r: %s", obj.name, exc)

		if obj_type == "CAMERA":
			try:
				data["camera_data"] = extract_camera_data(obj)
			except Exception as exc:
				log.warning("Failed to extract camera data for %r: %s", obj.name, exc)

		elif obj_type == "LIGHT":
			try:
				data["light_data"] = extract_light_data(obj)
			except Exception as exc:
				log.warning("Failed to extract light data for %r: %s", obj.name, exc)

		elif obj_type == "MESH":
			try:
				data["mesh_data"] = extract_mesh_data(obj)
			except Exception as exc:
				log.warning("Failed to extract mesh data for %r: %s", obj.name, exc)

		return data

	@classmethod
	def _extract_transform(cls, obj: Any) -> dict:

		loc, rot, scale = obj.matrix_world.decompose()
		return {
			"location":       loc,
			"rotation_euler": rot.to_euler(),  # convert quaternion → Euler
			"scale":          scale,
		}

	@classmethod
	def _extract_material_slots(cls, obj: Any) -> list[dict]:

		slots = []
		for i, slot in enumerate(obj.material_slots):
			mat = slot.material
			slot_data: dict = {
				"index":     i,
				"name":      mat.name if mat else None,
				"use_nodes": mat.use_nodes if mat else None,
			}

			# Extract node graph when material uses nodes
			if mat and mat.use_nodes:
				try:
					slot_data["node_graph"] = MaterialExtractor.extract(mat)
				except Exception as exc:
					log.warning(
						"Failed to extract node graph for material %r "
						"on object %r: %s",
						mat.name,
						obj.name,
						exc,
					)
					slot_data["node_graph"] = None
			else:
				slot_data["node_graph"] = None

			slots.append(slot_data)
		return slots

	# Collection extraction

	@classmethod
	def _extract_collection_tree(
		cls,
		collection: Any,
		parent_path: str = "",
	) -> dict[str, dict]:
		
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
		for col in obj.users_collection:
			return col.name
		return ""