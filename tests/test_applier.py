"""
tests/test_applier.py
~~~~~~~~~~~~~~~~~~~~~~
Merge application against a fake Blender scene.

The applier had no coverage at all, which is how three defects survived:
world-space values written into local-space properties, resolved delete/modify
conflicts that were filtered out before dispatch, and success counted per
proposal so a merge that wrote nothing reported success.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import fake_bpy
from fake_bpy import (
	FakeCollection,
	FakeData,
	FakeMaterial,
	FakeObject,
	FakeSlot,
	FakeStruct,
)

from blendiff.data_model.conflict import (
	ConflictKind,
	MergeProposal,
	NonConflictingChange,
	PropertyConflict,
	Resolution,
	TargetKind,
	ThreeWayDiff,
)
from blendiff.merge_engine.applier import Applier


@pytest.fixture
def bpy():
	module = fake_bpy.install()
	yield module
	fake_bpy.uninstall()


@pytest.fixture
def cube(bpy):
	obj = FakeObject("Cube")
	bpy.data.objects.add(obj)
	return obj


def _tw(*proposals) -> ThreeWayDiff:
	return ThreeWayDiff(
		base_label="Base", label_a="A", label_b="B", proposals=list(proposals),
	)


def _proposal(name="Cube", changes=(), source="a", **kwargs):
	"""A proposal carrying only non-conflicting changes from one side."""
	proposal = MergeProposal(object_name=name, **kwargs)
	bucket = (
		proposal.non_conflicting_from_a if source == "a"
		else proposal.non_conflicting_from_b
	)
	for path, value in changes:
		bucket.append(NonConflictingChange(
			property_path=path, base_value=None, new_value=value, source=source,
		))
	return proposal


def _apply(*proposals):
	return Applier().apply_all(_tw(*proposals), context=None)


class TestGuards:
	def test_unresolved_conflict_refuses_to_apply(self, cube):
		proposal = MergeProposal(object_name="Cube")
		proposal.conflicts.append(PropertyConflict(
			property_path="visible", base_value=True, value_a=False, value_b=True,
			kind=ConflictKind.BOTH_MODIFIED,
		))
		with pytest.raises(RuntimeError, match="unresolved"):
			_apply(proposal)

	def test_missing_object_is_reported_not_silent(self, bpy):
		result = _apply(_proposal("Ghost", [("visible", False)]))
		assert result.missing_targets == ["Ghost"]
		assert result.applied == []

	def test_empty_proposal_does_nothing(self, cube):
		result = _apply(_proposal("Cube", []))
		assert result.total == 0


class TestTransforms:
	def test_location_applied(self, cube):
		_apply(_proposal("Cube", [("transform.location", [1.0, 2.0, 3.0])]))
		assert cube.location == (1.0, 2.0, 3.0)

	def test_rotation_applied(self, cube):
		_apply(_proposal("Cube", [("transform.rotation_euler", [0.5, 0.0, 0.0])]))
		assert cube.rotation_euler == (0.5, 0.0, 0.0)

	def test_scale_applied(self, cube):
		_apply(_proposal("Cube", [("transform.scale", [2.0, 2.0, 2.0])]))
		assert cube.scale == (2.0, 2.0, 2.0)

	def test_rotation_mode_applied_before_rotation_values(self, cube):
		"""
		Blender reinterprets rotation channels when the mode changes, so the
		mode must land first or the values get converted out from under us.
		"""
		proposal = _proposal("Cube", [
			("transform.rotation_quaternion", [1.0, 0.0, 0.0, 0.0]),
			("transform.rotation_mode", "QUATERNION"),
		])

		recorded = []
		original_setattr = FakeObject.__setattr__

		def tracking_setattr(self, key, value):
			if key in ("rotation_mode", "rotation_quaternion"):
				recorded.append(key)
			original_setattr(self, key, value)

		FakeObject.__setattr__ = tracking_setattr
		try:
			_apply(proposal)
		finally:
			FakeObject.__setattr__ = original_setattr

		assert recorded.index("rotation_mode") < recorded.index("rotation_quaternion")

	def test_quaternion_applied(self, cube):
		_apply(_proposal("Cube", [("transform.rotation_quaternion", [0.0, 1.0, 0.0, 0.0])]))
		assert cube.rotation_quaternion == (0.0, 1.0, 0.0, 0.0)


class TestVisibility:
	def test_visible_true_clears_hide_viewport(self, cube):
		cube.hide_viewport = True
		_apply(_proposal("Cube", [("visible", True)]))
		assert cube.hide_viewport is False

	def test_visible_false_sets_hide_viewport(self, cube):
		_apply(_proposal("Cube", [("visible", False)]))
		assert cube.hide_viewport is True

	def test_hide_render_applied(self, cube):
		_apply(_proposal("Cube", [("hide_render", True)]))
		assert cube.hide_render is True

	def test_visible_in_viewlayer_is_reported_unsupported(self, cube):
		"""It is derived state; writing it directly is not possible."""
		result = _apply(_proposal("Cube", [("visible_in_viewlayer", False)]))
		assert result.applied == []
		assert len(result.skipped) == 1
		assert "Derived" in result.skipped[0].detail


class TestRename:
	def test_rename_applied(self, cube, bpy):
		_apply(_proposal("Cube", [("name", "Body_LOW")]))
		assert cube.name == "Body_LOW"
		assert bpy.data.objects.get("Body_LOW") is cube

	def test_rename_collision_fails_loudly(self, cube, bpy):
		bpy.data.objects.add(FakeObject("Body_LOW"))
		result = _apply(_proposal("Cube", [("name", "Body_LOW")]))
		assert result.failed
		assert "already exists" in result.failed[0].detail
		assert cube.name == "Cube"

	def test_object_found_under_previous_name(self, cube):
		"""
		The proposal names the object as the newer snapshot does, but the scene
		may still be using the base name when the rename came from the far side.
		"""
		proposal = _proposal("Body_LOW", [("visible", False)], previous_name="Cube")
		result = _apply(proposal)
		assert cube.hide_viewport is True
		assert result.missing_targets == []


class TestParenting:
	def test_parent_set(self, cube, bpy):
		rig = FakeObject("Rig")
		bpy.data.objects.add(rig)
		_apply(_proposal("Cube", [("parent.parent_name", "Rig")]))
		assert cube.parent is rig

	def test_parent_cleared(self, cube, bpy):
		cube.parent = FakeObject("Rig")
		_apply(_proposal("Cube", [("parent.parent_name", None)]))
		assert cube.parent is None

	def test_reparent_preserves_world_transform(self, cube, bpy):
		"""
		Setting obj.parent alone makes the object jump, because its local
		transform is reinterpreted against the new parent.
		"""
		bpy.data.objects.add(FakeObject("Rig"))
		before = cube.matrix_world.copy()
		_apply(_proposal("Cube", [("parent.parent_name", "Rig")]))
		assert cube.matrix_world == before

	def test_missing_parent_fails(self, cube):
		result = _apply(_proposal("Cube", [("parent.parent_name", "Nope")]))
		assert result.failed and "not found" in result.failed[0].detail

	def test_self_parent_rejected(self, cube):
		result = _apply(_proposal("Cube", [("parent.parent_name", "Cube")]))
		assert result.failed and "own parent" in result.failed[0].detail

	def test_parent_type_applied(self, cube):
		_apply(_proposal("Cube", [("parent.parent_type", "BONE")]))
		assert cube.parent_type == "BONE"


class TestMaterials:
	def test_material_assigned(self, cube, bpy):
		cube.material_slots = [FakeSlot()]
		bpy.data.materials.add(FakeMaterial("Skin"))
		_apply(_proposal("Cube", [("material_slots[0].name", "Skin")]))
		assert cube.material_slots[0].material.name == "Skin"

	def test_material_cleared(self, cube, bpy):
		cube.material_slots = [FakeSlot(FakeMaterial("Skin"))]
		_apply(_proposal("Cube", [("material_slots[0].name", None)]))
		assert cube.material_slots[0].material is None

	def test_missing_material_fails(self, cube):
		cube.material_slots = [FakeSlot()]
		result = _apply(_proposal("Cube", [("material_slots[0].name", "Ghost")]))
		assert result.failed and "not found" in result.failed[0].detail

	def test_out_of_range_slot_fails(self, cube):
		result = _apply(_proposal("Cube", [("material_slots[3].name", "Skin")]))
		assert result.failed and "no material slot" in result.failed[0].detail


class TestCollections:
	def test_object_moved_to_collection(self, cube, bpy):
		source = FakeCollection("Old")
		target = FakeCollection("Props")
		bpy.data.collections.add(source)
		bpy.data.collections.add(target)
		source.objects.link(cube)

		_apply(_proposal("Cube", [("collection_path", "Scene Collection/Props")]))
		assert [c.name for c in cube.users_collection] == ["Props"]

	def test_multi_collection_membership_applied(self, cube, bpy):
		for name in ("Props", "Renderable"):
			bpy.data.collections.add(FakeCollection(name))
		_apply(_proposal("Cube", [("collection_paths", ["Props", "Renderable"])]))
		assert sorted(c.name for c in cube.users_collection) == ["Props", "Renderable"]

	def test_missing_collection_fails(self, cube):
		result = _apply(_proposal("Cube", [("collection_path", "Ghost")]))
		assert result.failed and "not found" in result.failed[0].detail

	def test_refuses_to_orphan_object(self, cube):
		"""Unlinking from every collection would make the object unreachable."""
		result = _apply(_proposal("Cube", [("collection_paths", [])]))
		assert result.failed


class TestCustomProps:
	def test_custom_prop_set(self, cube):
		_apply(_proposal("Cube", [("custom_props.rig_version", 3)]))
		assert cube["rig_version"] == 3

	def test_custom_prop_removed(self, cube):
		cube["rig_version"] = 2
		_apply(_proposal("Cube", [("custom_props.rig_version", None)]))
		assert "rig_version" not in cube

	def test_removing_absent_prop_is_not_an_error(self, cube):
		result = _apply(_proposal("Cube", [("custom_props.gone", None)]))
		assert result.failed == []


class TestCameraAndLight:
	def test_camera_focal_length_maps_to_lens(self, bpy):
		cam = FakeObject("Cam", "CAMERA", data=FakeData(lens=50.0))
		bpy.data.objects.add(cam)
		_apply(_proposal("Cam", [("camera.focal_length", 85.0)]))
		assert cam.data.lens == 85.0

	def test_camera_nested_dof_attribute(self, bpy):
		cam = FakeObject("Cam", "CAMERA",
		                 data=FakeData(dof=FakeStruct(focus_distance=1.0)))
		bpy.data.objects.add(cam)
		_apply(_proposal("Cam", [("camera.dof_distance", 4.5)]))
		assert cam.data.dof.focus_distance == 4.5

	def test_light_energy_applied(self, bpy):
		light = FakeObject("Lamp", "LIGHT", data=FakeData(energy=100.0))
		bpy.data.objects.add(light)
		_apply(_proposal("Lamp", [("light.energy", 750.0)]))
		assert light.data.energy == 750.0

	def test_unknown_camera_property_fails(self, bpy):
		cam = FakeObject("Cam", "CAMERA", data=FakeData())
		bpy.data.objects.add(cam)
		result = _apply(_proposal("Cam", [("camera.made_up", 1)]))
		assert result.failed


class TestStructuralChanges:
	def test_removed_object_is_deleted(self, cube, bpy):
		result = _apply(_proposal("Cube", [("__structural__", "removed")]))
		assert bpy.data.objects.get("Cube") is None
		assert result.applied

	def test_resolved_delete_modify_actually_deletes(self, cube, bpy):
		"""
		The most important conflict in any merge. It was previously filtered
		out before dispatch, making every resolved delete/modify a no-op.
		"""
		proposal = MergeProposal(object_name="Cube", structural_conflict=True)
		proposal.conflicts.append(PropertyConflict(
			property_path="__existence__",
			base_value="exists", value_a="deleted", value_b="modified",
			kind=ConflictKind.DELETE_MODIFY,
			resolution=Resolution.USE_A,
		))
		_apply(proposal)
		assert bpy.data.objects.get("Cube") is None

	def test_resolved_keep_retains_object(self, cube, bpy):
		proposal = MergeProposal(object_name="Cube", structural_conflict=True)
		proposal.conflicts.append(PropertyConflict(
			property_path="__existence__",
			base_value="exists", value_a="deleted", value_b="modified",
			kind=ConflictKind.DELETE_MODIFY,
			resolution=Resolution.USE_B,
		))
		_apply(proposal)
		assert bpy.data.objects.get("Cube") is cube

	def test_delete_skips_remaining_property_writes(self, cube, bpy):
		proposal = _proposal("Cube", [
			("__structural__", "removed"),
			("transform.location", [9.0, 9.0, 9.0]),
		])
		_apply(proposal)
		assert bpy.data.objects.get("Cube") is None
		assert cube.location == (0.0, 0.0, 0.0)

	def test_added_object_reports_it_cannot_be_created(self, bpy):
		result = _apply(_proposal("NewCube", [("__structural__", "added")]))
		assert result.skipped
		assert "cannot create objects" in result.skipped[0].detail

	def test_deleting_absent_object_is_reported(self, bpy):
		result = _apply(_proposal("Ghost", [("__structural__", "removed")]))
		assert result.skipped and "already absent" in result.skipped[0].detail


class TestAutoResolution:
	def test_auto_resolved_applies_the_agreed_value(self, cube):
		"""
		Both sides made the same edit, so the agreed value must be written.
		Applying the *base* value instead silently reverted a change both
		artists had made.
		"""
		proposal = MergeProposal(object_name="Cube")
		proposal.conflicts.append(PropertyConflict(
			property_path="transform.location",
			base_value=[0.0, 0.0, 0.0],
			value_a=[7.0, 0.0, 0.0],
			value_b=[7.0, 0.0, 0.0],
			kind=ConflictKind.BOTH_MODIFIED,
			resolution=Resolution.AUTO,
		))
		_apply(proposal)
		assert cube.location == (7.0, 0.0, 0.0)

	def test_use_base_reverts(self, cube):
		proposal = MergeProposal(object_name="Cube")
		proposal.conflicts.append(PropertyConflict(
			property_path="transform.location",
			base_value=[1.0, 1.0, 1.0],
			value_a=[7.0, 0.0, 0.0],
			value_b=[9.0, 0.0, 0.0],
			kind=ConflictKind.BOTH_MODIFIED,
			resolution=Resolution.USE_BASE,
		))
		_apply(proposal)
		assert cube.location == (1.0, 1.0, 1.0)


class TestHonestAccounting:
	def test_unsupported_property_is_skipped_not_applied(self, cube):
		result = _apply(_proposal("Cube", [("modifiers.0.levels", 3)]))
		assert result.applied == []
		assert len(result.skipped) == 1
		assert not result.all_succeeded

	def test_skipped_carries_a_reason(self, cube):
		result = _apply(_proposal("Cube", [("mesh.vertex_count", 42)]))
		assert "cannot rebuild" in result.skipped[0].detail

	def test_counts_are_per_property_not_per_proposal(self, cube):
		result = _apply(_proposal("Cube", [
			("transform.location", [1.0, 0.0, 0.0]),
			("visible", False),
			("modifiers.0.levels", 3),
		]))
		assert result.summary() == {
			"applied": 2, "skipped": 1, "failed": 0,
			"missing_targets": 0, "total": 3,
		}

	def test_all_succeeded_false_when_anything_skipped(self, cube):
		result = _apply(_proposal("Cube", [("fcurves.location", 1)]))
		assert not result.all_succeeded

	def test_all_succeeded_true_for_clean_merge(self, cube):
		result = _apply(_proposal("Cube", [("visible", False)]))
		assert result.all_succeeded

	def test_one_failure_does_not_block_other_properties(self, cube):
		result = _apply(_proposal("Cube", [
			("parent.parent_name", "Ghost"),
			("transform.location", [4.0, 0.0, 0.0]),
		]))
		assert cube.location == (4.0, 0.0, 0.0)
		assert len(result.failed) == 1

	def test_one_failing_object_does_not_block_others(self, cube, bpy):
		other = FakeObject("Sphere")
		bpy.data.objects.add(other)
		result = _apply(
			_proposal("Ghost", [("visible", False)]),
			_proposal("Sphere", [("visible", False)]),
		)
		assert other.hide_viewport is True
		assert result.missing_targets == ["Ghost"]

	def test_report_line_mentions_every_category(self, cube):
		result = _apply(_proposal("Cube", [
			("visible", False),
			("modifiers.0.levels", 3),
			("parent.parent_name", "Ghost"),
		]))
		line = result.report_line()
		assert "applied 1" in line and "not applicable" in line and "failed" in line


class TestNonObjectTargets:
	def test_collection_changes_are_reported_not_applied(self, bpy):
		proposal = _proposal(
			"Scene Collection/Props", [("objects", ["Cube"])],
			target_kind=TargetKind.COLLECTION,
		)
		result = _apply(proposal)
		assert result.applied == []
		assert "manually" in result.skipped[0].detail

	def test_scene_changes_are_reported_not_applied(self, bpy):
		proposal = _proposal(
			"Scene", [("cycles.samples", 256)], target_kind=TargetKind.SCENE,
		)
		result = _apply(proposal)
		assert result.applied == []
		assert result.skipped


class TestPoseBones:
	"""
	Pose transforms are the animator's output and are directly settable, unlike
	rest bones which live on the armature datablock and need edit mode.
	"""

	def _rig(self, bpy, bones=("Spine", "Head"), armature=False):
		from fake_bpy import FakeArmature, FakePose
		rig = FakeObject("Rig", "ARMATURE",
		                 data=FakeArmature(bones) if armature else None)
		rig.pose = FakePose(bones)
		bpy.data.objects.add(rig)
		bpy.context.view_layer.objects.add(rig)
		return rig

	def test_location_applied(self, bpy):
		rig = self._rig(bpy)
		_apply(_proposal("Rig", [('pose.bones["Head"].location', [0.0, 1.0, 0.0])]))
		assert rig.pose.bones["Head"].location == (0.0, 1.0, 0.0)

	def test_rotation_quaternion_applied(self, bpy):
		rig = self._rig(bpy)
		_apply(_proposal("Rig", [
			('pose.bones["Head"].rotation_quaternion', [0.7, 0.7, 0.0, 0.0]),
		]))
		assert rig.pose.bones["Head"].rotation_quaternion == (0.7, 0.7, 0.0, 0.0)

	def test_scale_applied(self, bpy):
		rig = self._rig(bpy)
		_apply(_proposal("Rig", [('pose.bones["Spine"].scale', [2.0, 2.0, 2.0])]))
		assert rig.pose.bones["Spine"].scale == (2.0, 2.0, 2.0)

	def test_rotation_mode_applied(self, bpy):
		rig = self._rig(bpy)
		_apply(_proposal("Rig", [('pose.bones["Head"].rotation_mode', "XYZ")]))
		assert rig.pose.bones["Head"].rotation_mode == "XYZ"

	def test_only_the_named_bone_is_touched(self, bpy):
		rig = self._rig(bpy)
		_apply(_proposal("Rig", [('pose.bones["Head"].location', [5.0, 0.0, 0.0])]))
		assert rig.pose.bones["Spine"].location == (0.0, 0.0, 0.0)

	def test_rotation_mode_applied_before_rotation_values(self, bpy):
		"""
		Blender reinterprets rotation channels when the mode changes, so the
		mode must land first. Pose bones carry their own mode per bone, so the
		ordering rule has to match on the path suffix.
		"""
		self._rig(bpy)
		recorded = []
		from fake_bpy import FakePoseBone
		original = FakePoseBone.__setattr__

		def tracking(self, key, value):
			if key in ("rotation_mode", "rotation_euler"):
				recorded.append(key)
			original(self, key, value)

		FakePoseBone.__setattr__ = tracking
		try:
			_apply(_proposal("Rig", [
				('pose.bones["Head"].rotation_euler', [1.0, 0.0, 0.0]),
				('pose.bones["Head"].rotation_mode', "XYZ"),
			]))
		finally:
			FakePoseBone.__setattr__ = original

		assert recorded.index("rotation_mode") < recorded.index("rotation_euler")

	def test_missing_bone_fails_loudly(self, bpy):
		self._rig(bpy)
		result = _apply(_proposal("Rig", [('pose.bones["Ghost"].location', [1, 0, 0])]))
		assert result.failed and "no pose bone" in result.failed[0].detail

	def test_object_without_pose_fails(self, cube):
		result = _apply(_proposal("Cube", [('pose.bones["Head"].location', [1, 0, 0])]))
		assert result.failed and "no pose" in result.failed[0].detail

	def test_bone_flags_apply_without_edit_mode(self, bpy):
		"""Deform and inheritance flags are writable on Bone directly."""
		rig = self._rig(bpy, armature=True)
		_apply(_proposal("Rig", [('armature.bones["Head"].use_deform', False)]))
		assert rig.data.bones["Head"].use_deform is False
		assert bpy.mode_set_calls == [], "no mode switch needed for a flag"

	def test_bone_addition_is_reported_unappliable(self, bpy):
		self._rig(bpy)
		result = _apply(_proposal("Rig", [('pose.bones["NewBone"]', "NewBone")]))
		assert result.applied == []
		assert "cannot add or remove bones" in result.skipped[0].detail

	def test_bone_constraints_reported_unappliable(self, bpy):
		self._rig(bpy)
		result = _apply(_proposal("Rig", [
			('pose.bones["Head"].constraints[0].influence', 0.5),
		]))
		assert result.applied == []
		assert "constraint" in result.skipped[0].detail.lower()


class TestRestBones:
	"""
	Rest bones live on EditBone and can only be written in edit mode, so an
	object's changes are applied as a batch in one session rather than one
	attribute at a time.

    Mode, active object and selection belong to the user, who is mid-task —
	leaving them in edit mode on an object they did not pick would be a
	genuinely disruptive thing for a merge to do.
	"""

	def _rig(self, bpy, bones=("Spine", "Chest", "Head")):
		from fake_bpy import FakeArmature
		rig = FakeObject("Rig", "ARMATURE", data=FakeArmature(bones))
		bpy.data.objects.add(rig)
		bpy.context.view_layer.objects.add(rig)
		edit = rig.data.edit_bones
		edit["Spine"].tail = (0.0, 0.0, 1.0)
		edit["Chest"].parent = edit["Spine"]
		edit["Chest"].head, edit["Chest"].tail = (0.0, 0.0, 1.0), (0.0, 0.0, 2.0)
		edit["Head"].parent = edit["Chest"]
		edit["Head"].head, edit["Head"].tail = (0.0, 0.0, 2.0), (0.0, 0.0, 3.0)
		return rig

	def test_reparenting_applies(self, bpy):
		rig = self._rig(bpy)
		_apply(_proposal("Rig", [('armature.bones["Head"].parent', "Spine")]))
		assert rig.data.edit_bones["Head"].parent.name == "Spine"

	def test_unparenting_applies(self, bpy):
		rig = self._rig(bpy)
		_apply(_proposal("Rig", [('armature.bones["Head"].parent', None)]))
		assert rig.data.edit_bones["Head"].parent is None

	def test_rest_position_applies(self, bpy):
		rig = self._rig(bpy)
		_apply(_proposal("Rig", [
			('armature.bones["Head"].head_local', [0.0, 0.5, 2.0]),
			('armature.bones["Head"].tail_local', [0.0, 0.5, 3.0]),
		]))
		assert rig.data.edit_bones["Head"].head == (0.0, 0.5, 2.0)
		assert rig.data.edit_bones["Head"].tail == (0.0, 0.5, 3.0)

	def test_roll_applies(self, bpy):
		rig = self._rig(bpy)
		_apply(_proposal("Rig", [('armature.bones["Head"].roll', 0.5236)]))
		assert abs(rig.data.edit_bones["Head"].roll - 0.5236) < 1e-6

	def test_use_connect_applies_last(self, bpy):
		"""
		Connecting snaps the head onto the parent's tail, so it must land after
		the head write — otherwise the two fight and the result depends on
		dict ordering.
		"""
		rig = self._rig(bpy)
		_apply(_proposal("Rig", [
			('armature.bones["Head"].use_connect', True),
			('armature.bones["Head"].head_local', [9.0, 9.0, 9.0]),
		]))
		head = rig.data.edit_bones["Head"]
		assert head.use_connect is True
		assert head.head == head.parent.tail, "connect must win over the head write"

	def test_one_edit_mode_session_for_many_bones(self, bpy):
		"""Toggling per property would be slow and would spam the undo stack."""
		self._rig(bpy)
		_apply(_proposal("Rig", [
			('armature.bones["Head"].roll', 0.1),
			('armature.bones["Chest"].roll', 0.2),
			('armature.bones["Spine"].roll', 0.3),
		]))
		assert bpy.mode_set_calls.count("EDIT") == 1

	def test_mode_is_restored(self, bpy):
		rig = self._rig(bpy)
		_apply(_proposal("Rig", [('armature.bones["Head"].roll', 0.1)]))
		assert rig.mode == "OBJECT"
		assert bpy.mode_set_calls[-1] == "OBJECT"

	def test_active_object_is_restored(self, bpy):
		"""The user was working on something else; put it back."""
		other = FakeObject("Cube")
		bpy.data.objects.add(other)
		bpy.context.view_layer.objects.add(other)
		bpy.context.view_layer.objects.active = other

		self._rig(bpy)
		_apply(_proposal("Rig", [('armature.bones["Head"].roll', 0.1)]))
		assert bpy.context.view_layer.objects.active is other

	def test_selection_is_restored(self, bpy):
		other = FakeObject("Cube")
		bpy.data.objects.add(other)
		bpy.context.view_layer.objects.add(other)
		other.select_set(True)
		bpy.context.view_layer.objects.active = other

		rig = self._rig(bpy)
		_apply(_proposal("Rig", [('armature.bones["Head"].roll', 0.1)]))
		assert other.select_get() is True
		assert rig.select_get() is False, "the rig was not selected before the merge"

	def test_missing_bone_fails_that_change_only(self, bpy):
		rig = self._rig(bpy)
		result = _apply(_proposal("Rig", [
			('armature.bones["Ghost"].roll', 0.1),
			('armature.bones["Head"].roll', 0.2),
		]))
		assert len(result.failed) == 1 and "not found" in result.failed[0].detail
		assert abs(rig.data.edit_bones["Head"].roll - 0.2) < 1e-6

	def test_missing_parent_fails(self, bpy):
		self._rig(bpy)
		result = _apply(_proposal("Rig", [('armature.bones["Head"].parent', "Ghost")]))
		assert result.failed and "not found" in result.failed[0].detail

	def test_self_parent_rejected(self, bpy):
		self._rig(bpy)
		result = _apply(_proposal("Rig", [('armature.bones["Head"].parent', "Head")]))
		assert result.failed and "own parent" in result.failed[0].detail

    # Linked rigs

	def test_linked_rig_is_skipped_with_a_reason(self, bpy):
		"""A linked rig belongs to another file and cannot be edited at all."""
		rig = self._rig(bpy)
		rig.library = object()

		result = _apply(_proposal("Rig", [('armature.bones["Head"].roll', 0.1)]))
		assert result.applied == []
		assert "linked" in result.skipped[0].detail

	def test_library_override_is_skipped_with_a_reason(self, bpy):
		rig = self._rig(bpy)
		rig.override_library = object()

		result = _apply(_proposal("Rig", [('armature.bones["Head"].roll', 0.1)]))
		assert result.applied == []
		assert "override" in result.skipped[0].detail

	def test_linked_rig_never_enters_edit_mode(self, bpy):
		rig = self._rig(bpy)
		rig.library = object()
		_apply(_proposal("Rig", [('armature.bones["Head"].roll', 0.1)]))
		assert "EDIT" not in bpy.mode_set_calls

	def test_rest_and_pose_changes_apply_together(self, bpy):
		"""A merge usually carries both; neither should block the other."""
		from fake_bpy import FakePose
		rig = self._rig(bpy)
		rig.pose = FakePose(("Spine", "Chest", "Head"))

		_apply(_proposal("Rig", [
			('armature.bones["Head"].roll', 0.25),
			('pose.bones["Head"].location', [1.0, 0.0, 0.0]),
		]))
		assert abs(rig.data.edit_bones["Head"].roll - 0.25) < 1e-6
		assert rig.pose.bones["Head"].location == (1.0, 0.0, 0.0)
