"""
blendiff.extractor.armature_extractor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Armature rest data and pose extraction.

The gap this closes
-------------------
Rigs were nearly invisible. An ARMATURE object recorded its own transform,
visibility and parent — and nothing about the rig: no bones, no hierarchy, no
rest pose, no pose transforms, no bone constraints. For a rigged character,
BlenDiff could tell you the character had moved but not that someone had
reparented a finger, changed the rest pose, or rewired an IK chain.

That is backwards. Rigs are the shared artefact that riggers and animators
actually collide over, so they are the case where a semantic diff and an
assisted merge matter most.

Rest versus pose
----------------
The two are captured separately because they are different things owned by
different people and stored in different places:

* **Rest data** lives on the armature datablock (``obj.data``), which can be
  shared between objects. It is the rigger's output: bone hierarchy, rest
  positions, roll, deform flags.
* **Pose** lives on the object (``obj.pose``). It is the animator's output:
  per-bone transforms layered on top of the rest pose.

Keeping them apart means "the rig changed" and "the pose changed" are
distinguishable, which is the distinction a team actually cares about.

Roll without edit mode
----------------------
``roll`` exists only on ``EditBone``, and reaching it would mean switching the
object into edit mode during extraction — invasive, and impossible on a linked
rig. ``Bone.AxisRollFromMatrix`` recovers the same value from the bone's rest
matrix, so a roll change is detected without touching the user's mode.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .constraint_extractor import extract_constraint_stack

log = logging.getLogger(__name__)

#: Coordinates are rounded to this many places, matching the serializer so the
#: whole codebase agrees on when two positions are "the same".
_PRECISION = 6


def _round_vec(value: Any) -> list[float]:
	try:
		return [round(float(v), _PRECISION) for v in value]
	except (TypeError, ValueError):
		return []


def _bone_roll(bone: Any) -> Optional[float]:
	"""
	Recover a bone's roll from its rest matrix.

	Returns None when the value cannot be derived, so an unknown roll is never
	confused with a roll of zero.
	"""
	try:
		import bpy

		_axis, roll = bpy.types.Bone.AxisRollFromMatrix(bone.matrix_local.to_3x3())
		return round(float(roll), _PRECISION)
	except Exception as exc:
		log.debug("Could not derive roll for bone %r: %s", getattr(bone, "name", "?"), exc)
		return None


def _bone_collections(bone: Any) -> list[str]:
	"""
	Names of the bone collections this bone belongs to.

	Bone collections replaced armature layers in Blender 4.0; on older versions
	the attribute is absent and membership is simply not recorded.
	"""
	try:
		return sorted(c.name for c in bone.collections)
	except Exception:
		return []


def _extract_bone(bone: Any) -> dict:
	"""Rest data for a single bone."""
	parent = getattr(bone, "parent", None)

	return {
		"name": bone.name,
		# Hierarchy. Reparenting a bone is one of the most disruptive rig edits
		# there is, and it is invisible without this.
		"parent": parent.name if parent is not None else None,
		"use_connect": bool(getattr(bone, "use_connect", False)),

		# Rest geometry, in armature space.
		"head_local": _round_vec(bone.head_local),
		"tail_local": _round_vec(bone.tail_local),
		"length": round(float(bone.length), _PRECISION),
		"roll": _bone_roll(bone),

		# Deformation and inheritance flags: these change how the rig behaves
		# without moving anything, so they are easy to break unnoticed.
		"use_deform": bool(getattr(bone, "use_deform", True)),
		"use_inherit_rotation": bool(getattr(bone, "use_inherit_rotation", True)),
		"inherit_scale": str(getattr(bone, "inherit_scale", "FULL")),

		"envelope_distance": round(float(getattr(bone, "envelope_distance", 0.0)), _PRECISION),
		"envelope_weight": round(float(getattr(bone, "envelope_weight", 0.0)), _PRECISION),

		"collections": _bone_collections(bone),
		"hide": bool(getattr(bone, "hide", False)),
	}


def extract_armature_data(obj: Any) -> Optional[dict]:
	"""
	Rest data for an ARMATURE object's armature datablock.

	Returns None when the object carries no armature data.
	"""
	arm = obj.data
	if arm is None:
		return None

	bones: dict[str, dict] = {}
	try:
		for bone in arm.bones:
			try:
				bones[bone.name] = _extract_bone(bone)
			except Exception as exc:
				log.warning("Failed to extract bone %r: %s", bone.name, exc)
	except Exception as exc:
		log.warning("Could not iterate bones on %r: %s", obj.name, exc)

	try:
		collections = sorted(c.name for c in arm.collections_all)
	except Exception:
		collections = []

	return {
		"name": arm.name,
		"bone_count": len(bones),
		# REST hides the pose entirely, so a rig left in rest position looks
		# broken to anyone opening the file. Worth reporting.
		"pose_position": str(getattr(arm, "pose_position", "POSE")),
		"display_type": str(getattr(arm, "display_type", "OCTAHEDRAL")),
		"collections": collections,
		"bones": bones,
	}


def _extract_pose_bone(pose_bone: Any) -> dict:
	"""
	Transform and constraints for a single pose bone.

	Only the rotation channel matching the bone's rotation mode is recorded.
	Pose bones default to quaternion rather than Euler, and storing the
	inactive channel would report changes on values nothing reads.
	"""
	mode = str(getattr(pose_bone, "rotation_mode", "QUATERNION"))

	entry: dict = {
		"name": pose_bone.name,
		"location": _round_vec(pose_bone.location),
		"scale": _round_vec(pose_bone.scale),
		"rotation_mode": mode,
	}

	if mode == "QUATERNION":
		entry["rotation_quaternion"] = _round_vec(pose_bone.rotation_quaternion)
	elif mode == "AXIS_ANGLE":
		entry["rotation_axis_angle"] = _round_vec(pose_bone.rotation_axis_angle)
	else:
		entry["rotation_euler"] = _round_vec(pose_bone.rotation_euler)

	# The widget an animator actually grabs in the viewport. Losing it makes a
	# rig unusable even though nothing about the bones changed.
	shape = getattr(pose_bone, "custom_shape", None)
	entry["custom_shape"] = shape.name if shape is not None else None

	# Pose bone constraints are the heart of a rig — IK chains, Copy Rotation,
	# Limit Rotation. The object constraint extractor reads only .constraints,
	# so it applies here unchanged.
	try:
		entry["constraints"] = extract_constraint_stack(pose_bone)
	except Exception as exc:
		log.warning("Failed to extract constraints on bone %r: %s", pose_bone.name, exc)
		entry["constraints"] = []

	return entry


def extract_pose(obj: Any) -> dict[str, dict]:
	"""
	Pose transforms for an ARMATURE object, keyed by bone name.

	Returns an empty dict for objects with no pose.
	"""
	pose = getattr(obj, "pose", None)
	if pose is None:
		return {}

	result: dict[str, dict] = {}
	try:
		for pose_bone in pose.bones:
			try:
				result[pose_bone.name] = _extract_pose_bone(pose_bone)
			except Exception as exc:
				log.warning("Failed to extract pose bone %r: %s", pose_bone.name, exc)
	except Exception as exc:
		log.warning("Could not iterate pose bones on %r: %s", obj.name, exc)

	return result
