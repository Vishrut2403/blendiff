"""
tests/test_armature_diff.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Armature rest data and pose comparison.

The gap this closes: an ARMATURE object recorded only its own transform, so a
rigged character could be reparented, re-rolled, re-posed or have its IK chain
rewired and BlenDiff reported nothing. Rigs are the artefact riggers and
animators actually collide over, which makes them the case where a semantic
diff matters most.

Rest and pose are compared separately on purpose — they are different edits,
usually by different people, and collapsing them would lose that.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.diff_engine.armature_diff import diff_armature_data, diff_pose


def _bone(name="Spine", parent=None, **extra):
	data = {
		"name": name,
		"parent": parent,
		"use_connect": False,
		"head_local": [0.0, 0.0, 0.0],
		"tail_local": [0.0, 0.0, 1.0],
		"length": 1.0,
		"roll": 0.0,
		"use_deform": True,
		"use_inherit_rotation": True,
		"inherit_scale": "FULL",
		"envelope_distance": 0.25,
		"envelope_weight": 1.0,
		"collections": [],
		"hide": False,
	}
	data.update(extra)
	return data


def _armature(bones=None, **extra):
	bones = bones if bones is not None else {"Spine": _bone()}
	data = {
		"name": "Rig",
		"bone_count": len(bones),
		"pose_position": "POSE",
		"display_type": "OCTAHEDRAL",
		"collections": [],
		"bones": bones,
	}
	data.update(extra)
	return data


def _pose_bone(name="Spine", **extra):
	data = {
		"name": name,
		"location": [0.0, 0.0, 0.0],
		"scale": [1.0, 1.0, 1.0],
		"rotation_mode": "QUATERNION",
		"rotation_quaternion": [1.0, 0.0, 0.0, 0.0],
		"custom_shape": None,
		"constraints": [],
	}
	data.update(extra)
	return data


def _paths(changes):
	return [c.property_path for c in changes]


class TestNoChanges:
	def test_identical_armatures(self):
		assert diff_armature_data(_armature(), _armature()) == []

	def test_identical_poses(self):
		pose = {"Spine": _pose_bone()}
		assert diff_pose(pose, dict(pose)) == []

	def test_both_absent(self):
		assert diff_armature_data(None, None) == []
		assert diff_pose(None, None) == []
		assert diff_pose({}, {}) == []


class TestArmaturePresence:
	def test_armature_added(self):
		changes = diff_armature_data(None, _armature())
		assert _paths(changes) == ["armature"]
		assert changes[0].new_value == "Rig"

	def test_armature_removed(self):
		changes = diff_armature_data(_armature(), None)
		assert changes[0].old_value == "Rig"


class TestBoneHierarchy:
	"""Reparenting a bone is one of the most disruptive edits to a rig."""

	def test_bone_added(self):
		a = _armature({"Spine": _bone()})
		b = _armature({"Spine": _bone(), "Head": _bone("Head", parent="Spine")})
		changes = diff_armature_data(a, b)
		assert 'armature.bones["Head"]' in _paths(changes)

	def test_bone_removed(self):
		a = _armature({"Spine": _bone(), "Head": _bone("Head")})
		b = _armature({"Spine": _bone()})
		changes = [c for c in diff_armature_data(a, b)
		           if c.property_path == 'armature.bones["Head"]']
		assert changes[0].old_value == "Head"
		assert changes[0].new_value is None

	def test_reparenting_detected(self):
		a = _armature({"Head": _bone("Head", parent="Spine")})
		b = _armature({"Head": _bone("Head", parent="Chest")})
		changes = diff_armature_data(a, b)
		assert 'armature.bones["Head"].parent' in _paths(changes)

	def test_unparenting_detected(self):
		a = _armature({"Head": _bone("Head", parent="Spine")})
		b = _armature({"Head": _bone("Head", parent=None)})
		assert 'armature.bones["Head"].parent' in _paths(diff_armature_data(a, b))

	def test_connect_flag_detected(self):
		a = _armature({"Head": _bone("Head", use_connect=False)})
		b = _armature({"Head": _bone("Head", use_connect=True)})
		assert 'armature.bones["Head"].use_connect' in _paths(diff_armature_data(a, b))

	def test_bone_count_reported(self):
		a = _armature({"Spine": _bone()})
		b = _armature({"Spine": _bone(), "Head": _bone("Head")})
		assert "armature.bone_count" in _paths(diff_armature_data(a, b))


class TestRestPose:
	def test_moved_bone_head_detected(self):
		a = _armature({"Spine": _bone(head_local=[0.0, 0.0, 0.0])})
		b = _armature({"Spine": _bone(head_local=[0.0, 0.5, 0.0])})
		assert 'armature.bones["Spine"].head_local' in _paths(diff_armature_data(a, b))

	def test_moved_bone_tail_detected(self):
		a = _armature({"Spine": _bone(tail_local=[0.0, 0.0, 1.0])})
		b = _armature({"Spine": _bone(tail_local=[0.0, 0.0, 2.0])})
		assert 'armature.bones["Spine"].tail_local' in _paths(diff_armature_data(a, b))

	def test_roll_change_detected(self):
		"""
		Roll changes the bone's orientation without moving head or tail, so it
		is invisible to position comparison alone.
		"""
		a = _armature({"Spine": _bone(roll=0.0)})
		b = _armature({"Spine": _bone(roll=0.5236)})
		assert 'armature.bones["Spine"].roll' in _paths(diff_armature_data(a, b))

	def test_float_noise_below_tolerance_ignored(self):
		a = _armature({"Spine": _bone(head_local=[0.0, 0.0, 0.0])})
		b = _armature({"Spine": _bone(head_local=[0.0, 0.0, 1e-9])})
		assert diff_armature_data(a, b) == []

	def test_unknown_roll_is_not_a_change(self):
		"""None means the roll could not be derived, not that it is zero."""
		a = _armature({"Spine": _bone(roll=None)})
		b = _armature({"Spine": _bone(roll=None)})
		assert diff_armature_data(a, b) == []


class TestDeformFlags:
	"""These change how a rig behaves without moving anything visible."""

	def test_use_deform_detected(self):
		a = _armature({"Spine": _bone(use_deform=True)})
		b = _armature({"Spine": _bone(use_deform=False)})
		assert 'armature.bones["Spine"].use_deform' in _paths(diff_armature_data(a, b))

	def test_inherit_rotation_detected(self):
		a = _armature({"Spine": _bone(use_inherit_rotation=True)})
		b = _armature({"Spine": _bone(use_inherit_rotation=False)})
		assert 'armature.bones["Spine"].use_inherit_rotation' in _paths(
			diff_armature_data(a, b))

	def test_inherit_scale_detected(self):
		a = _armature({"Spine": _bone(inherit_scale="FULL")})
		b = _armature({"Spine": _bone(inherit_scale="NONE")})
		assert 'armature.bones["Spine"].inherit_scale' in _paths(diff_armature_data(a, b))


class TestBoneCollections:
	def test_membership_change_detected(self):
		a = _armature({"Spine": _bone(collections=["Deform"])})
		b = _armature({"Spine": _bone(collections=["Deform", "Controls"])})
		assert 'armature.bones["Spine"].collections' in _paths(diff_armature_data(a, b))

	def test_membership_order_ignored(self):
		a = _armature({"Spine": _bone(collections=["A", "B"])})
		b = _armature({"Spine": _bone(collections=["B", "A"])})
		assert diff_armature_data(a, b) == []

	def test_armature_collections_change_detected(self):
		a = _armature(collections=["Deform"])
		b = _armature(collections=["Deform", "Controls"])
		assert "armature.collections" in _paths(diff_armature_data(a, b))


class TestArmatureSettings:
	def test_pose_position_change_detected(self):
		"""REST hides the pose entirely and looks like a broken file."""
		a = _armature(pose_position="POSE")
		b = _armature(pose_position="REST")
		assert "armature.pose_position" in _paths(diff_armature_data(a, b))

	def test_display_type_change_detected(self):
		a = _armature(display_type="OCTAHEDRAL")
		b = _armature(display_type="STICK")
		assert "armature.display_type" in _paths(diff_armature_data(a, b))


class TestPose:
	def test_moved_pose_bone_detected(self):
		a = {"Spine": _pose_bone(location=[0.0, 0.0, 0.0])}
		b = {"Spine": _pose_bone(location=[0.5, 0.0, 0.0])}
		assert 'pose.bones["Spine"].location' in _paths(diff_pose(a, b))

	def test_rotated_pose_bone_detected(self):
		a = {"Spine": _pose_bone(rotation_quaternion=[1.0, 0.0, 0.0, 0.0])}
		b = {"Spine": _pose_bone(rotation_quaternion=[0.7, 0.7, 0.0, 0.0])}
		assert 'pose.bones["Spine"].rotation_quaternion' in _paths(diff_pose(a, b))

	def test_scaled_pose_bone_detected(self):
		a = {"Spine": _pose_bone(scale=[1.0, 1.0, 1.0])}
		b = {"Spine": _pose_bone(scale=[2.0, 1.0, 1.0])}
		assert 'pose.bones["Spine"].scale' in _paths(diff_pose(a, b))

	def test_rotation_mode_change_detected(self):
		a = {"Spine": _pose_bone(rotation_mode="QUATERNION")}
		b = {"Spine": _pose_bone(rotation_mode="XYZ")}
		assert 'pose.bones["Spine"].rotation_mode' in _paths(diff_pose(a, b))

	def test_custom_shape_change_detected(self):
		"""The widget an animator grabs; losing it makes a rig unusable."""
		a = {"Spine": _pose_bone(custom_shape=None)}
		b = {"Spine": _pose_bone(custom_shape="WGT-circle")}
		assert 'pose.bones["Spine"].custom_shape' in _paths(diff_pose(a, b))

	def test_pose_bone_added(self):
		a = {"Spine": _pose_bone()}
		b = {"Spine": _pose_bone(), "Head": _pose_bone("Head")}
		assert 'pose.bones["Head"]' in _paths(diff_pose(a, b))

	def test_float_noise_ignored(self):
		a = {"Spine": _pose_bone(location=[0.0, 0.0, 0.0])}
		b = {"Spine": _pose_bone(location=[0.0, 0.0, 1e-9])}
		assert diff_pose(a, b) == []

	def test_inactive_rotation_channel_is_not_compared(self):
		"""
		Only the channel matching the rotation mode is recorded. Comparing an
		absent channel against a present one would invent a change.
		"""
		a = {"Spine": _pose_bone(rotation_mode="QUATERNION")}
		b = {"Spine": _pose_bone(rotation_mode="QUATERNION")}
		b["Spine"]["rotation_euler"] = [1.0, 0.0, 0.0]
		assert diff_pose(a, b) == []


class TestBoneConstraints:
	def _with_constraint(self, influence=1.0, con_type="IK"):
		return _pose_bone(constraints=[{
			"index": 0, "name": "IK", "type": con_type,
			"enabled": True, "influence": influence, "params": {},
		}])

	def test_constraint_influence_change_detected(self):
		a = {"Hand": self._with_constraint(1.0)}
		b = {"Hand": self._with_constraint(0.5)}
		changes = diff_pose(a, b)
		assert any("constraints" in p for p in _paths(changes))

	def test_constraint_added(self):
		a = {"Hand": _pose_bone("Hand")}
		b = {"Hand": self._with_constraint()}
		assert diff_pose(a, b) != []

	def test_constraint_type_change_detected(self):
		a = {"Hand": self._with_constraint(con_type="IK")}
		b = {"Hand": self._with_constraint(con_type="COPY_ROTATION")}
		assert any("constraints" in p for p in _paths(diff_pose(a, b)))

	def test_constraint_path_names_the_bone(self):
		a = {"Hand": self._with_constraint(1.0)}
		b = {"Hand": self._with_constraint(0.5)}
		assert all(p.startswith('pose.bones["Hand"].constraints')
		           for p in _paths(diff_pose(a, b)))


class TestLegacySnapshots:
	"""Snapshots from before this feature carry none of these fields."""

	def test_absent_fields_are_not_changes(self):
		a = {"Spine": {"name": "Spine"}}
		b = {"Spine": {"name": "Spine"}}
		assert diff_pose(a, b) == []

	def test_partial_bone_data_does_not_raise(self):
		a = _armature({"Spine": {"name": "Spine"}})
		b = _armature({"Spine": _bone()})
		diff_armature_data(a, b)  # must not raise

	def test_missing_bones_key_does_not_raise(self):
		a = {"name": "Rig", "bone_count": 0}
		b = {"name": "Rig", "bone_count": 0}
		assert diff_armature_data(a, b) == []
