from __future__ import annotations

import math
from typing import Any
from blendiff.diff_engine.render_diff import diff_render_settings
from blendiff.diff_engine.camera_light_diff import diff_camera_data, diff_light_data
from blendiff.diff_engine.mesh_diff import diff_mesh_data
from blendiff.diff_engine.world_diff import diff_world_data
from blendiff.diff_engine.modifier_diff import diff_modifier_stack
from blendiff.diff_engine.parent_diff import diff_all_parents
from blendiff.diff_engine.constraint_diff import diff_all_constraints
from blendiff.diff_engine.custom_prop_diff import diff_all_custom_props

from ..data_model.diff import (
		ChangeKind,
		CollectionDiff,
		ObjectDiff,
		PropertyChange,
		SceneDiff,
)
from .material_diff import compare_materials

_DEFAULT_EPSILON = 1e-4


class DiffEngine:

		def __init__(self, epsilon: float = _DEFAULT_EPSILON) -> None:
				self._eps = epsilon

		def compare(self, scene_a: dict, scene_b: dict) -> SceneDiff:

				diff = SceneDiff(
						scene_name_a=scene_a.get("scene_name", "A"),
						scene_name_b=scene_b.get("scene_name", "B"),
				)

				diff.object_diffs     = self._diff_objects(
						scene_a.get("objects", {}),
						scene_b.get("objects", {}),
				)
				diff.collection_diffs = self._diff_collections(
						scene_a.get("collections", {}),
						scene_b.get("collections", {}),
				)
				diff.render_diff = diff_render_settings(
						scene_a.get("render", {}),
						scene_b.get("render", {}),
				)
				diff.world_diff = diff_world_data(
						scene_a.get("world"),
						scene_b.get("world"),
				)
				diff.parent_diffs = diff_all_parents(
						scene_a.get("objects", {}),
						scene_b.get("objects", {}),
				)
				diff.constraint_diffs = diff_all_constraints(
						scene_a.get("objects", {}),
						scene_b.get("objects", {}),
				)
				diff.custom_prop_diffs = diff_all_custom_props(
						scene_a.get("objects", {}),
						scene_b.get("objects", {}),
				)
				return diff

		def _diff_objects(
				self,
				objs_a: dict[str, dict],
				objs_b: dict[str, dict],
		) -> list[ObjectDiff]:
				results: list[ObjectDiff] = []

				keys_a = set(objs_a)
				keys_b = set(objs_b)

				for name in sorted(keys_b - keys_a):
						results.append(ObjectDiff(name=name, kind=ChangeKind.ADDED))

				for name in sorted(keys_a - keys_b):
						results.append(ObjectDiff(name=name, kind=ChangeKind.REMOVED))

				for name in sorted(keys_a & keys_b):
						changes = self._compare_objects(objs_a[name], objs_b[name])
						if changes:
								results.append(
										ObjectDiff(name=name, kind=ChangeKind.MODIFIED, changes=changes)
								)

				return results

		def _compare_objects(self, obj_a: dict, obj_b: dict) -> list[PropertyChange]:
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

				if obj_a.get("visible") != obj_b.get("visible"):
						changes.append(PropertyChange(
								property_path="visible",
								old_value=obj_a.get("visible"),
								new_value=obj_b.get("visible"),
						))

				changes.extend(
						self._compare_transforms(
								obj_a.get("transform", {}),
								obj_b.get("transform", {}),
						)
				)

				changes.extend(
						self._compare_material_slots(
								obj_a.get("material_slots", []),
								obj_b.get("material_slots", []),
						)
				)

				# Modifier stack — applies to all object types
				changes.extend(diff_modifier_stack(
						obj_a.get("modifier_stack", []),
						obj_b.get("modifier_stack", []),
						prefix="modifiers",
				))

				obj_type = obj_a.get("type")
				if obj_type == "CAMERA":
						changes.extend(diff_camera_data(
								obj_a.get("camera_data"),
								obj_b.get("camera_data"),
								prefix="camera",
						))
				elif obj_type == "LIGHT":
						changes.extend(diff_light_data(
								obj_a.get("light_data"),
								obj_b.get("light_data"),
								prefix="light",
						))
				elif obj_type == "MESH":
						changes.extend(diff_mesh_data(
								obj_a.get("mesh_data"),
								obj_b.get("mesh_data"),
								prefix="mesh",
						))

				return changes

		def _compare_transforms(
				self, t_a: dict, t_b: dict
		) -> list[PropertyChange]:
				changes: list[PropertyChange] = []
				for key in ("location", "rotation_euler", "scale"):
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

		def _compare_material_slots(
				self,
				slots_a: list[dict],
				slots_b: list[dict],
		) -> list[PropertyChange]:
				changes: list[PropertyChange] = []

				map_a = {s["index"]: s for s in slots_a}
				map_b = {s["index"]: s for s in slots_b}

				all_indices = sorted(set(map_a) | set(map_b))

				for idx in all_indices:
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

								if name_a == name_b and name_a is not None:
										graph_a = slot_a.get("node_graph")
										graph_b = slot_b.get("node_graph")

										if graph_a is not None or graph_b is not None:
												node_changes = compare_materials(
														graph_a,
														graph_b,
														material_name=name_a,
														epsilon=self._eps,
												)
												changes.extend(node_changes)

				return changes

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
								results.append(
										CollectionDiff(path=path, kind=ChangeKind.MODIFIED, changes=changes)
								)

				return results

		def _compare_collections(
				self, col_a: dict, col_b: dict
		) -> list[PropertyChange]:
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
