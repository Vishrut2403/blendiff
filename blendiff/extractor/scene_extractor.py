from __future__ import annotations

import logging
from typing import Any

from .render_extractor import extract_render_settings
from .camera_light_extractor import extract_camera_data, extract_light_data
from .armature_extractor import extract_armature_data, extract_pose
from .mesh_extractor import extract_mesh_data
from .world_extractor import extract_world_data
from .modifier_extractor import extract_modifier_stack
from .parent_extractor import extract_parent_info
from .material_extractor import MaterialExtractor
from .constraint_extractor import extract_constraint_stack
from .custom_prop_extractor import extract_custom_props
from .fcurve_extractor import extract_fcurves
from .driver_extractor import extract_drivers
from .nla_extractor import extract_nla_tracks
from .scene_custom_prop_extractor import extract_scene_custom_props
from .identity import read_id, stamp_scene
from ..data_model import schema

log = logging.getLogger(__name__)


class SceneExtractor:
	"""Extract structured scene data from the active Blender scene."""

	# Public API

	@classmethod
	def extract(
		cls,
		context: Any,
		stamp_identity: bool = False,
		known_ids: dict | None = None,
	) -> dict:
		"""
		Extract the active scene into a plain, JSON-ready dict.

		Parameters
		----------
		context:
			``bpy.context``.
		stamp_identity:
			When True, objects lacking a persistent BlenDiff id are given one.
			This writes to the .blend and therefore marks it modified, so it is
			reserved for snapshot capture — an action the user explicitly asked
			for. A read-only diff leaves this False and simply records whichever
			ids already exist.
		known_ids:
			Object name to identity from the most recent snapshot, used to
			recover ids for objects that lost theirs because the .blend was
			closed without saving. See identity.stamp_scene.
		"""
		import bpy  # local import keeps module importable outside Blender

		scene = context.scene
		version = bpy.app.version_string

		if stamp_identity:
			try:
				stamped = stamp_scene(scene, known_ids)
				if stamped:
					log.info("Stamped %d object(s) with a BlenDiff identity.", stamped)
			except Exception as exc:
				log.warning("Could not stamp object identities: %s", exc)

		collections = cls._extract_collection_tree(scene.collection)
		# Objects record their collection membership as full paths, so the
		# tree must be walked before objects are extracted.
		path_lookup = cls._build_collection_path_lookup(collections)

		raw = {
			"blender_version": version,
			"scene_name":      scene.name,
			"objects":         cls._extract_all_objects(scene, path_lookup),
			"collections":     collections,
			"render":          extract_render_settings(scene),
			"world":           extract_world_data(scene),
			"scene_custom_props": extract_scene_custom_props(scene),
		}

		# Record which domains this snapshot actually captured, so a future
		# release diffing against it never invents changes for a domain that
		# did not exist yet.
		return schema.stamp(raw, cls._captured_domains())

	@staticmethod
	def _captured_domains() -> tuple[str, ...]:
		"""
		Domains this extractor version captures.

		Every domain is attempted for every object; individual failures are
		logged and leave that object's entry empty rather than un-captured, so
		the domain list is static.
		"""
		return schema.ALL_DOMAINS

	# Object extraction

	@classmethod
	def _extract_all_objects(
		cls,
		scene: Any,
		path_lookup: dict[str, list[str]] | None = None,
	) -> dict[str, dict]:
		"""Return a dict keyed by object name."""
		result: dict[str, dict] = {}
		for obj in scene.objects:
			try:
				data = cls._extract_object(obj, path_lookup or {})
				result[obj.name] = data
			except Exception as exc:
				log.warning("Failed to extract object %r: %s", obj.name, exc)
		return result

	@classmethod
	def _extract_object(cls, obj: Any, path_lookup: dict[str, list[str]]) -> dict:
		"""Extract a single bpy.types.Object."""
		obj_type = obj.type

		paths = cls._collection_paths(obj, path_lookup)

		data = {
			"name":            obj.name,
			# Persistent identity, so a rename stays one object across
			# snapshots instead of a delete plus an add. None when the object
			# was never stamped or is linked from another file.
			"blendiff_id":     read_id(obj),
			"type":            obj_type,
			# Primary path, kept for backwards compatibility with snapshots
			# and reports that assume a single collection.
			"collection_path": paths[0] if paths else "",
			# Full membership: an object can be linked into several collections
			# at once, and losing that hides real scene-organisation changes.
			"collection_paths": paths,
			"transform":       cls._extract_transform(obj),
			"material_slots":  cls._extract_material_slots(obj),
			"visible":         not obj.hide_viewport,
			"hide_viewport":   bool(obj.hide_viewport),
			# Viewport and render visibility are independent switches, and an
			# object hidden in one but not the other is a common source of
			# "why is it missing from the render?" — so both are tracked.
			"hide_render":     bool(getattr(obj, "hide_render", False)),
			"visible_in_viewlayer": cls._visible_in_viewlayer(obj),
			"parent":          None,
			"camera_data":     None,
			"light_data":      None,
			"mesh_data":       None,
			"armature_data":   None,
			"pose_bones":      {},
			"modifier_stack":  [],
			"constraint_stack":[],
			"custom_props":    {},
			"fcurves":         [],
			"drivers":         [],
			"nla_tracks":      [],
		}

		# Modifiers exist on all object types
		try:
			data["modifier_stack"] = extract_modifier_stack(obj)
		except Exception as exc:
			log.warning("Failed to extract modifiers for %r: %s", obj.name, exc)

		try:
			data["parent"] = extract_parent_info(obj)
		except Exception as exc:
			log.warning("Failed to extract parent info for %r: %s", obj.name, exc)

		try:
			data["constraint_stack"] = extract_constraint_stack(obj)
		except Exception as exc:
			log.warning("Failed to extract constraints for %r: %s", obj.name, exc)

		try:
			data["custom_props"] = extract_custom_props(obj)
		except Exception as exc:
			log.warning("Failed to extract custom props for %r: %s", obj.name, exc)

		try:
			data["fcurves"] = extract_fcurves(obj)
		except Exception as exc:
			log.warning("Failed to extract F-curves for %r: %s", obj.name, exc)

		try:
			data["drivers"] = extract_drivers(obj)
		except Exception as exc:
			log.warning("Failed to extract drivers for %r: %s", obj.name, exc)
			
		try:
			data["nla_tracks"] = extract_nla_tracks(obj)
		except Exception as exc:	
			log.warning("Failed to extract NLA tracks for %r: %s", obj.name, exc)

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

		elif obj_type == "ARMATURE":
			# Rest data and pose are captured separately: the first belongs to
			# the rigger and lives on the shared datablock, the second belongs
			# to the animator and lives on the object.
			try:
				data["armature_data"] = extract_armature_data(obj)
			except Exception as exc:
				log.warning("Failed to extract armature data for %r: %s", obj.name, exc)

			try:
				data["pose_bones"] = extract_pose(obj)
			except Exception as exc:
				log.warning("Failed to extract pose for %r: %s", obj.name, exc)

		return data

	@classmethod
	def _extract_transform(cls, obj: Any) -> dict:
		"""
		Extract the object's **local** transform.

		This deliberately does not decompose ``matrix_world``. World space is
		wrong here for two reasons:

		* Moving a parent changes the world transform of every descendant, so a
		  single edit is reported as a change on dozens of untouched objects.
		* The merge applier writes to ``obj.location`` / ``rotation_euler`` /
		  ``scale``, which are local. Feeding world-space values into local
		  properties teleports any parented object.

		``rotation_mode`` is recorded alongside the Euler because the same
		numbers mean different orientations under different modes, and because
		quaternion- and axis-angle-mode objects need their native values to
		round-trip correctly.
		"""
		mode = getattr(obj, "rotation_mode", "XYZ")

		transform = {
			"location":       tuple(obj.location),
			"rotation_euler": tuple(obj.rotation_euler),
			"scale":          tuple(obj.scale),
			"rotation_mode":  mode,
		}

		# Euler values are meaningless when the object is driven by a
		# quaternion or axis-angle, so capture the authoritative channel too.
		if mode == "QUATERNION":
			transform["rotation_quaternion"] = tuple(obj.rotation_quaternion)
		elif mode == "AXIS_ANGLE":
			transform["rotation_axis_angle"] = tuple(obj.rotation_axis_angle)

		return transform

	@classmethod
	def _visible_in_viewlayer(cls, obj: Any) -> bool | None:
		"""
		Effective visibility in the active view layer.

		``visible_get()`` needs an evaluated view layer and raises for objects
		outside it, so a failure records "unknown" rather than guessing.
		"""
		try:
			return bool(obj.visible_get())
		except Exception:
			return None

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
	def _build_collection_path_lookup(
		cls,
		collections: dict[str, dict],
	) -> dict[str, list[str]]:
		"""
		Map each collection name to every full path it occupies.

		A collection can be linked under more than one parent, so the mapping
		is one-to-many. Paths are sorted for deterministic output.
		"""
		lookup: dict[str, list[str]] = {}
		for path, node in collections.items():
			lookup.setdefault(node["name"], []).append(path)
		for paths in lookup.values():
			paths.sort()
		return lookup

	@classmethod
	def _collection_paths(
		cls,
		obj: Any,
		path_lookup: dict[str, list[str]],
	) -> list[str]:
		"""
		Full paths of every collection this object belongs to.

		Previously only the first collection's bare *name* was recorded, which
		could not be matched against the collection tree (keyed by full path)
		and silently dropped multi-collection membership entirely.
		"""
		paths: list[str] = []
		try:
			users = list(obj.users_collection)
		except Exception as exc:
			log.warning("Could not read collections for %r: %s", obj.name, exc)
			return []

		for col in users:
			resolved = path_lookup.get(col.name)
			if resolved:
				paths.extend(resolved)
			else:
				# Collection outside this scene's tree (e.g. linked); its bare
				# name is the best identifier available.
				paths.append(col.name)

		return sorted(set(paths))