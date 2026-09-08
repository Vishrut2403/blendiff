"""
blendiff.diff_engine.diff_engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Top-level semantic comparison of two serialized scenes.

Three rules govern everything here:

* **Objects are matched by identity, not name.** A rename is one modified
  object, not a delete plus an add. See ``identity_match``.
* **A domain is only diffed when both snapshots captured it.** Diffing a
  pre-0.5 snapshot against a current one must not report every F-curve as newly
  added just because the older snapshot predates F-curve capture.
* **Transforms are only compared within the same space.** Schema v1 stored
  world-space transforms, v2 stores local ones; comparing across the two
  produces noise on every parented object.
"""

from __future__ import annotations

import math

from ..data_model import schema
from ..data_model.diff import (
	ChangeKind,
	CollectionDiff,
	ObjectDiff,
	PropertyChange,
	SceneDiff,
)
from .camera_light_diff import diff_camera_data, diff_light_data
from .constraint_diff import diff_all_constraints
from .custom_prop_diff import diff_all_custom_props
from .driver_diff import diff_all_drivers
from .fcurve_diff import diff_all_fcurves
from .identity_match import ObjectPairing, pair_objects
from .material_diff import compare_materials
from .mesh_diff import diff_mesh_data
from .modifier_diff import diff_modifier_stack
from .nla_diff import diff_all_nla
from .parent_diff import diff_all_parents
from .render_diff import diff_render_settings
from .scene_custom_prop_diff import diff_scene_custom_props
from .world_diff import diff_world_data

_DEFAULT_EPSILON = 1e-4

#: Transform keys compared as float vectors.
_TRANSFORM_VECTORS = ("location", "rotation_euler", "scale",
					  "rotation_quaternion", "rotation_axis_angle")


class DiffEngine:

	def __init__(self, epsilon: float = _DEFAULT_EPSILON) -> None:
		self._eps = epsilon

	def compare(self, scene_a: dict, scene_b: dict) -> SceneDiff:
		diff = SceneDiff(
			scene_name_a=scene_a.get("scene_name", "A"),
			scene_name_b=scene_b.get("scene_name", "B"),
		)

		objs_a = scene_a.get("objects", {})
		objs_b = scene_b.get("objects", {})

		# Which domains both snapshots actually captured. Anything captured by
		# only one side is recorded as skipped rather than diffed.
		domains = schema.comparable_domains(scene_a, scene_b)
		diff.skipped_domains = sorted(schema.skipped_domains(scene_a, scene_b))
		diff.skip_notes = schema.describe_skipped(scene_a, scene_b)

		compare_transforms = schema.transforms_comparable(scene_a, scene_b)
		if not compare_transforms:
			diff.skipped_domains.append("transform")
			diff.skip_notes.append(
				"Transforms: snapshots use different transform spaces "
				f"({schema.transform_space(scene_a)} vs "
				f"{schema.transform_space(scene_b)}) — skipped, because "
				"world- and local-space values are not comparable"
			)

		# One pairing, shared by every domain, so they all agree on which
		# object in A corresponds to which object in B.
		pairing = pair_objects(objs_a, objs_b)

		diff.object_pairs = list(pairing.matched)
		diff.object_diffs = self._diff_objects(
			objs_a, objs_b, pairing, domains, compare_transforms,
		)
		diff.collection_diffs = self._diff_collections(
			scene_a.get("collections", {}),
			scene_b.get("collections", {}),
		)

		if schema.DOMAIN_RENDER in domains:
			diff.render_diff = diff_render_settings(
				scene_a.get("render", {}), scene_b.get("render", {}),
			)
		if schema.DOMAIN_WORLD in domains:
			diff.world_diff = diff_world_data(
				scene_a.get("world"), scene_b.get("world"),
			)
		if schema.DOMAIN_SCENE_CUSTOM_PROPS in domains:
			diff.scene_custom_prop_diff = diff_scene_custom_props(
				scene_a.get("scene_custom_props", {}),
				scene_b.get("scene_custom_props", {}),
			)

		pairs = pairing.matched
		if schema.DOMAIN_PARENT in domains:
			diff.parent_diffs = diff_all_parents(objs_a, objs_b, pairs)
		if schema.DOMAIN_CONSTRAINTS in domains:
			diff.constraint_diffs = diff_all_constraints(objs_a, objs_b, pairs)
		if schema.DOMAIN_CUSTOM_PROPS in domains:
			diff.custom_prop_diffs = diff_all_custom_props(objs_a, objs_b, pairs)
		if schema.DOMAIN_FCURVES in domains:
			diff.fcurve_diffs = diff_all_fcurves(objs_a, objs_b, pairs)
		if schema.DOMAIN_DRIVERS in domains:
			diff.driver_diffs = diff_all_drivers(objs_a, objs_b, pairs)
		if schema.DOMAIN_NLA in domains:
			diff.nla_diffs = diff_all_nla(objs_a, objs_b, pairs)

		return diff

	# Objects

	def _diff_objects(
		self,
		objs_a: dict[str, dict],
		objs_b: dict[str, dict],
		pairing: ObjectPairing,
		domains: set[str],
		compare_transforms: bool,
	) -> list[ObjectDiff]:
		results: list[ObjectDiff] = []

		for name in pairing.added:
			results.append(ObjectDiff(name=name, kind=ChangeKind.ADDED))

		for name in pairing.removed:
			results.append(ObjectDiff(name=name, kind=ChangeKind.REMOVED))

		for name_a, name_b in pairing.matched:
			changes = self._compare_objects(
				objs_a[name_a], objs_b[name_b], domains, compare_transforms,
			)
			# A rename is itself a change worth reporting, and it is what makes
			# the rest of this object's changes attributable at all.
			if name_a != name_b:
				changes.insert(0, PropertyChange(
					property_path="name",
					old_value=name_a,
					new_value=name_b,
				))
			if changes:
				results.append(ObjectDiff(
					name=name_b,
					kind=ChangeKind.MODIFIED,
					changes=changes,
					previous_name=name_a,
				))

		return results

	def _compare_objects(
		self,
		obj_a: dict,
		obj_b: dict,
		domains: set[str],
		compare_transforms: bool,
	) -> list[PropertyChange]:
		changes: list[PropertyChange] = []

		if obj_a.get("type") != obj_b.get("type"):
			changes.append(PropertyChange(
				property_path="type",
				old_value=obj_a.get("type"),
				new_value=obj_b.get("type"),
			))

		if obj_a.get("collection_path") != obj_b.get("collection_path"):
			changes.append(PropertyChange(
				property_path="collection_path",
				old_value=obj_a.get("collection_path"),
				new_value=obj_b.get("collection_path"),
			))

		# Full collection membership — an object can live in several at once.
		changes.extend(self._compare_optional_set(
			obj_a, obj_b, "collection_paths",
		))

		if obj_a.get("visible") != obj_b.get("visible"):
			changes.append(PropertyChange(
				property_path="visible",
				old_value=obj_a.get("visible"),
				new_value=obj_b.get("visible"),
			))

		# Viewport and render visibility are independent switches; an object
		# visible in the viewport but disabled for render is a common and
		# easily-missed cause of "it's not in my render".
		for key in ("hide_render", "visible_in_viewlayer"):
			changes.extend(self._compare_optional(obj_a, obj_b, key))

		if compare_transforms:
			changes.extend(self._compare_transforms(
				obj_a.get("transform", {}),
				obj_b.get("transform", {}),
			))

		if schema.DOMAIN_MATERIALS in domains:
			changes.extend(self._compare_material_slots(
				obj_a.get("material_slots", []),
				obj_b.get("material_slots", []),
			))

		if schema.DOMAIN_MODIFIERS in domains:
			# Modifier stacks exist on every object type.
			changes.extend(diff_modifier_stack(
				obj_a.get("modifier_stack", []),
				obj_b.get("modifier_stack", []),
				prefix="modifiers",
			))

		obj_type = obj_a.get("type")
		if obj_type == "CAMERA" and schema.DOMAIN_CAMERA in domains:
			changes.extend(diff_camera_data(
				obj_a.get("camera_data"), obj_b.get("camera_data"), prefix="camera",
			))
		elif obj_type == "LIGHT" and schema.DOMAIN_LIGHT in domains:
			changes.extend(diff_light_data(
				obj_a.get("light_data"), obj_b.get("light_data"), prefix="light",
			))
		elif obj_type == "MESH" and schema.DOMAIN_MESH in domains:
			changes.extend(diff_mesh_data(
				obj_a.get("mesh_data"), obj_b.get("mesh_data"), prefix="mesh",
			))

		return changes

	def _compare_optional(
		self,
		obj_a: dict,
		obj_b: dict,
		key: str,
		path: str | None = None,
	) -> list[PropertyChange]:
		"""
		Compare a field only when both snapshots recorded it.

		Fields added in a later schema version are absent from older snapshots.
		Comparing present-against-absent would report a change the user never
		made, so an absent field means "unknown", not "unset".
		"""
		if key not in obj_a or key not in obj_b:
			return []
		if obj_a[key] == obj_b[key]:
			return []
		return [PropertyChange(
			property_path=path or key,
			old_value=obj_a[key],
			new_value=obj_b[key],
		)]

	def _compare_optional_set(
		self,
		obj_a: dict,
		obj_b: dict,
		key: str,
	) -> list[PropertyChange]:
		"""Order-insensitive comparison of an optional list field."""
		if key not in obj_a or key not in obj_b:
			return []
		set_a = set(obj_a[key] or [])
		set_b = set(obj_b[key] or [])
		if set_a == set_b:
			return []
		return [PropertyChange(
			property_path=key,
			old_value=sorted(set_a),
			new_value=sorted(set_b),
		)]

	# Transforms

	def _compare_transforms(self, t_a: dict, t_b: dict) -> list[PropertyChange]:
		changes: list[PropertyChange] = []

		# Rotation mode first: the same Euler triple means different
		# orientations under different modes, so a mode change is the
		# explanation for any rotation difference reported alongside it.
		changes.extend(self._compare_optional(
			t_a, t_b, "rotation_mode", path="transform.rotation_mode",
		))

		for key in _TRANSFORM_VECTORS:
			if key not in t_a and key not in t_b:
				continue
			vec_a = t_a.get(key, [])
			vec_b = t_b.get(key, [])
			if not self._vecs_equal(vec_a, vec_b):
				changes.append(PropertyChange(
					property_path=f"transform.{key}",
					old_value=vec_a,
					new_value=vec_b,
				))
		return changes

	def _vecs_equal(self, a: list[float], b: list[float]) -> bool:
		if len(a) != len(b):
			return False
		return all(math.isclose(x, y, abs_tol=self._eps) for x, y in zip(a, b))

	# Materials

	def _compare_material_slots(
		self,
		slots_a: list[dict],
		slots_b: list[dict],
	) -> list[PropertyChange]:
		changes: list[PropertyChange] = []

		map_a = {s["index"]: s for s in slots_a}
		map_b = {s["index"]: s for s in slots_b}

		for idx in sorted(set(map_a) | set(map_b)):
			slot_a = map_a.get(idx)
			slot_b = map_b.get(idx)

			if slot_a is None:
				changes.append(PropertyChange(
					property_path=f"material_slots[{idx}]",
					old_value=None,
					new_value=slot_b.get("name"),
				))
			elif slot_b is None:
				changes.append(PropertyChange(
					property_path=f"material_slots[{idx}]",
					old_value=slot_a.get("name"),
					new_value=None,
				))
			else:
				name_a = slot_a.get("name")
				name_b = slot_b.get("name")

				if name_a != name_b:
					changes.append(PropertyChange(
						property_path=f"material_slots[{idx}].name",
						old_value=name_a,
						new_value=name_b,
					))

				# Only compare node graphs for the same material: two
				# different materials have unrelated graphs, and diffing them
				# would bury the slot change under dozens of node changes.
				if name_a == name_b and name_a is not None:
					graph_a = slot_a.get("node_graph")
					graph_b = slot_b.get("node_graph")

					if graph_a is not None or graph_b is not None:
						changes.extend(compare_materials(
							graph_a,
							graph_b,
							material_name=name_a,
							epsilon=self._eps,
						))

		return changes

	# Collections

	def _diff_collections(
		self,
		cols_a: dict[str, dict],
		cols_b: dict[str, dict],
	) -> list[CollectionDiff]:
		results: list[CollectionDiff] = []

		paths_a = set(cols_a)
		paths_b = set(cols_b)

		for path in sorted(paths_b - paths_a):
			results.append(CollectionDiff(path=path, kind=ChangeKind.ADDED))

		for path in sorted(paths_a - paths_b):
			results.append(CollectionDiff(path=path, kind=ChangeKind.REMOVED))

		for path in sorted(paths_a & paths_b):
			changes = self._compare_collections(cols_a[path], cols_b[path])
			if changes:
				results.append(CollectionDiff(
					path=path, kind=ChangeKind.MODIFIED, changes=changes,
				))

		return results

	def _compare_collections(self, col_a: dict, col_b: dict) -> list[PropertyChange]:
		changes: list[PropertyChange] = []

		for key in ("children", "objects"):
			set_a = set(col_a.get(key, []))
			set_b = set(col_b.get(key, []))
			if set_a != set_b:
				changes.append(PropertyChange(
					property_path=key,
					old_value=sorted(set_a),
					new_value=sorted(set_b),
				))
		return changes
