"""
blendiff.diff_engine.armature_diff
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Comparison of armature rest data and pose.

Bones are matched by **name**, not position, because bones have no stable id
and their order in the datablock is an implementation detail. A bone that
disappears from one snapshot and appears in the next under the same name is the
same bone; a renamed bone reads as one removed and one added, which is honest —
BlenDiff has no way to know the two are related.

Property paths follow Blender's own data-path syntax —
``pose.bones["Head"].location`` — so they match what a user sees in the UI, in
driver expressions, and in the F-curve data paths BlenDiff already reports.
"""

from __future__ import annotations

from typing import Any

from ..data_model.diff import PropertyChange
from .constraint_diff import diff_constraint_stack

#: Tolerance for bone positions and pose transforms.
_EPSILON = 1e-6

#: Rest fields compared as float vectors.
_BONE_VECTORS = ("head_local", "tail_local")

#: Rest fields compared exactly or as scalars.
_BONE_SCALARS = (
	"parent",
	"use_connect",
	"length",
	"roll",
	"use_deform",
	"use_inherit_rotation",
	"inherit_scale",
	"envelope_distance",
	"envelope_weight",
	"hide",
)

#: Pose fields compared as float vectors.
_POSE_VECTORS = (
	"location",
	"scale",
	"rotation_euler",
	"rotation_quaternion",
	"rotation_axis_angle",
)

#: Armature-level fields, excluding the bone map itself.
_ARMATURE_SCALARS = ("name", "bone_count", "pose_position", "display_type")


def _floats_equal(a: Any, b: Any) -> bool:
	if a is None or b is None:
		return a is b or a == b
	try:
		return abs(float(a) - float(b)) < _EPSILON
	except (TypeError, ValueError):
		return a == b


def _vecs_equal(a: Any, b: Any) -> bool:
	if not isinstance(a, list) or not isinstance(b, list):
		return a == b
	if len(a) != len(b):
		return False
	return all(_floats_equal(x, y) for x, y in zip(a, b))


def _compare_fields(
	a: dict,
	b: dict,
	prefix: str,
	vector_fields: tuple[str, ...],
	scalar_fields: tuple[str, ...],
) -> list[PropertyChange]:
	"""
	Compare the named fields of two entries.

	A field absent from both sides is skipped, and a field absent from only one
	is skipped too: rotation channels depend on the bone's rotation mode, and
	snapshots from before this feature have none of these fields at all.
	Reporting present-against-absent would invent changes nobody made.
	"""
	changes: list[PropertyChange] = []

	for field in vector_fields:
		if field not in a or field not in b:
			continue
		if not _vecs_equal(a[field], b[field]):
			changes.append(PropertyChange(f"{prefix}.{field}", a[field], b[field]))

	for field in scalar_fields:
		if field not in a or field not in b:
			continue
		val_a, val_b = a[field], b[field]
		if isinstance(val_a, float) or isinstance(val_b, float):
			if not _floats_equal(val_a, val_b):
				changes.append(PropertyChange(f"{prefix}.{field}", val_a, val_b))
		elif val_a != val_b:
			changes.append(PropertyChange(f"{prefix}.{field}", val_a, val_b))

	return changes


def _compare_name_keyed(
	map_a: dict,
	map_b: dict,
	prefix: str,
	compare_entry,
) -> list[PropertyChange]:
	"""
	Diff two name-keyed maps of bones, reporting additions and removals.

	Shared by rest bones and pose bones, which differ only in which fields
	their entries carry.
	"""
	changes: list[PropertyChange] = []

	for name in sorted(set(map_b) - set(map_a)):
		changes.append(PropertyChange(f'{prefix}["{name}"]', None, name))

	for name in sorted(set(map_a) - set(map_b)):
		changes.append(PropertyChange(f'{prefix}["{name}"]', name, None))

	for name in sorted(set(map_a) & set(map_b)):
		changes.extend(compare_entry(map_a[name], map_b[name], f'{prefix}["{name}"]'))

	return changes


def _compare_bone(bone_a: dict, bone_b: dict, path: str) -> list[PropertyChange]:
	changes = _compare_fields(bone_a, bone_b, path, _BONE_VECTORS, _BONE_SCALARS)

	# Bone collections replaced armature layers; membership drives visibility
	# and selectability, so losing it is a real rig change.
	if "collections" in bone_a and "collections" in bone_b:
		set_a = set(bone_a["collections"] or [])
		set_b = set(bone_b["collections"] or [])
		if set_a != set_b:
			changes.append(PropertyChange(
				f"{path}.collections", sorted(set_a), sorted(set_b),
			))

	return changes


def _compare_pose_bone(pose_a: dict, pose_b: dict, path: str) -> list[PropertyChange]:
	changes = _compare_fields(
		pose_a, pose_b, path, _POSE_VECTORS,
		("rotation_mode", "custom_shape"),
	)

	# Reuse the object constraint comparison: a pose bone's constraint stack has
	# exactly the same shape, and IK or Copy Rotation changes are the edits that
	# actually break a rig.
	if "constraints" in pose_a and "constraints" in pose_b:
		constraint_diff = diff_constraint_stack(
			pose_a.get("constraints") or [],
			pose_b.get("constraints") or [],
			obj_name="",
			prefix=f"{path}.constraints",
		)
		changes.extend(constraint_diff.changes)

	return changes


def diff_armature_data(
	arm_a: dict | None,
	arm_b: dict | None,
	prefix: str = "armature",
) -> list[PropertyChange]:
	"""
	Compare two armature rest-data dicts.

	None means the object had no armature data in that snapshot.
	"""
	if arm_a is None and arm_b is None:
		return []
	if arm_a is None:
		return [PropertyChange(prefix, None, (arm_b or {}).get("name"))]
	if arm_b is None:
		return [PropertyChange(prefix, arm_a.get("name"), None)]

	changes = _compare_fields(arm_a, arm_b, prefix, (), _ARMATURE_SCALARS)

	if "collections" in arm_a and "collections" in arm_b:
		set_a = set(arm_a["collections"] or [])
		set_b = set(arm_b["collections"] or [])
		if set_a != set_b:
			changes.append(PropertyChange(
				f"{prefix}.collections", sorted(set_a), sorted(set_b),
			))

	changes.extend(_compare_name_keyed(
		arm_a.get("bones") or {},
		arm_b.get("bones") or {},
		f"{prefix}.bones",
		_compare_bone,
	))

	return changes


def diff_pose(
	pose_a: dict | None,
	pose_b: dict | None,
	prefix: str = "pose.bones",
) -> list[PropertyChange]:
	"""
	Compare two pose dicts, keyed by bone name.

	Rest data and pose are compared separately so that "the rig changed" and
	"the pose changed" stay distinguishable — they are different edits, usually
	by different people.
	"""
	if not pose_a and not pose_b:
		return []

	return _compare_name_keyed(
		pose_a or {},
		pose_b or {},
		prefix,
		_compare_pose_bone,
	)
