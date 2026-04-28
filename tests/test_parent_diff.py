from __future__ import annotations

import pytest
from blendiff.diff_engine.parent_diff import diff_parent_info, diff_all_parents
from blendiff.data_model.parent_diff import ParentDiff
from blendiff.data_model.diff import PropertyChange


# Fixtures 

def _unparented() -> dict:
	return {"parent_name": None, "parent_type": None, "parent_bone": None}

def _parented_object(name: str = "Armature") -> dict:
	return {"parent_name": name, "parent_type": "OBJECT", "parent_bone": None}

def _parented_bone(parent: str = "Armature", bone: str = "Spine") -> dict:
	return {"parent_name": parent, "parent_type": "BONE", "parent_bone": bone}


# diff_parent_info: no changes 

class TestNoChanges:
	def test_both_unparented(self):
		result = diff_parent_info("Cube", _unparented(), _unparented())
		assert result.changes == []

	def test_both_object_parented_same(self):
		result = diff_parent_info("Cube", _parented_object(), _parented_object())
		assert result.changes == []

	def test_both_bone_parented_same(self):
		result = diff_parent_info("Cube", _parented_bone(), _parented_bone())
		assert result.changes == []

	def test_returns_parent_diff_instance(self):
		result = diff_parent_info("Cube", _unparented(), _unparented())
		assert isinstance(result, ParentDiff)

	def test_object_name_set(self):
		result = diff_parent_info("MyObj", _unparented(), _unparented())
		assert result.object_name == "MyObj"


# diff_parent_info: parent_name changes 

class TestParentNameChanges:
	def test_gained_parent(self):
		result = diff_parent_info("Cube", _unparented(), _parented_object())
		paths = [c.property_path for c in result.changes]
		assert "parent.parent_name" in paths

	def test_gained_parent_old_is_none(self):
		result = diff_parent_info("Cube", _unparented(), _parented_object())
		c = next(x for x in result.changes if x.property_path == "parent.parent_name")
		assert c.old_value is None
		assert c.new_value == "Armature"

	def test_lost_parent(self):
		result = diff_parent_info("Cube", _parented_object(), _unparented())
		paths = [c.property_path for c in result.changes]
		assert "parent.parent_name" in paths

	def test_lost_parent_new_is_none(self):
		result = diff_parent_info("Cube", _parented_object(), _unparented())
		c = next(x for x in result.changes if x.property_path == "parent.parent_name")
		assert c.new_value is None

	def test_parent_renamed(self):
		a = _parented_object("Armature")
		b = _parented_object("Armature.001")
		result = diff_parent_info("Cube", a, b)
		c = next(x for x in result.changes if x.property_path == "parent.parent_name")
		assert c.old_value == "Armature"
		assert c.new_value == "Armature.001"


# diff_parent_info: parent_type changes 

class TestParentTypeChanges:
	def test_object_to_bone(self):
		result = diff_parent_info("Cube", _parented_object(), _parented_bone())
		paths = [c.property_path for c in result.changes]
		assert "parent.parent_type" in paths

	def test_bone_to_object(self):
		result = diff_parent_info("Cube", _parented_bone(), _parented_object())
		paths = [c.property_path for c in result.changes]
		assert "parent.parent_type" in paths

	def test_type_change_values(self):
		result = diff_parent_info("Cube", _parented_object(), _parented_bone())
		c = next(x for x in result.changes if x.property_path == "parent.parent_type")
		assert c.old_value == "OBJECT"
		assert c.new_value == "BONE"


# diff_parent_info: parent_bone changes 

class TestParentBoneChanges:
	def test_bone_changed(self):
		a = _parented_bone(bone="Spine")
		b = _parented_bone(bone="Head")
		result = diff_parent_info("Cube", a, b)
		paths = [c.property_path for c in result.changes]
		assert "parent.parent_bone" in paths

	def test_bone_changed_values(self):
		a = _parented_bone(bone="Spine")
		b = _parented_bone(bone="Head")
		result = diff_parent_info("Cube", a, b)
		c = next(x for x in result.changes if x.property_path == "parent.parent_bone")
		assert c.old_value == "Spine"
		assert c.new_value == "Head"

	def test_bone_gained(self):
		a = _parented_object()
		b = _parented_bone(bone="Spine")
		result = diff_parent_info("Cube", a, b)
		paths = [c.property_path for c in result.changes]
		assert "parent.parent_bone" in paths

	def test_bone_cleared(self):
		a = _parented_bone(bone="Spine")
		b = _parented_object()
		result = diff_parent_info("Cube", a, b)
		paths = [c.property_path for c in result.changes]
		assert "parent.parent_bone" in paths


# diff_parent_info: None input handling 

class TestNoneHandling:
	def test_both_none_treated_as_unparented(self):
		result = diff_parent_info("Cube", None, None)
		assert result.changes == []

	def test_a_none_vs_parented(self):
		result = diff_parent_info("Cube", None, _parented_object())
		assert any(c.property_path == "parent.parent_name" for c in result.changes)

	def test_b_none_vs_parented(self):
		result = diff_parent_info("Cube", _parented_object(), None)
		assert any(c.property_path == "parent.parent_name" for c in result.changes)

	def test_changes_are_property_change_instances(self):
		result = diff_parent_info("Cube", _unparented(), _parented_object())
		for c in result.changes:
			assert isinstance(c, PropertyChange)


# diff_parent_info: custom prefix 

class TestCustomPrefix:
	def test_custom_prefix_applied(self):
		result = diff_parent_info(
			"Cube", _unparented(), _parented_object(), prefix="objects.Cube.parent"
		)
		paths = [c.property_path for c in result.changes]
		assert all(p.startswith("objects.Cube.parent.") for p in paths)


# diff_all_parents 

class TestDiffAllParents:
	def _make_objs(self, parent_info: dict) -> dict:
		return {"Cube": {"parent": parent_info}}

	def test_no_changes_returns_empty(self):
		objs = {"Cube": {"parent": _unparented()}}
		assert diff_all_parents(objs, objs) == []

	def test_detects_change(self):
		a = {"Cube": {"parent": _unparented()}}
		b = {"Cube": {"parent": _parented_object()}}
		result = diff_all_parents(a, b)
		assert len(result) == 1
		assert result[0].object_name == "Cube"

	def test_skips_objects_only_in_a(self):
		a = {"Cube": {"parent": _unparented()}, "Sphere": {"parent": _unparented()}}
		b = {"Cube": {"parent": _parented_object()}}
		result = diff_all_parents(a, b)
		names = [r.object_name for r in result]
		assert "Sphere" not in names

	def test_skips_objects_only_in_b(self):
		a = {"Cube": {"parent": _unparented()}}
		b = {"Cube": {"parent": _parented_object()}, "Sphere": {"parent": _unparented()}}
		result = diff_all_parents(a, b)
		names = [r.object_name for r in result]
		assert "Sphere" not in names

	def test_multiple_objects_with_changes(self):
		a = {
			"Cube":   {"parent": _unparented()},
			"Sphere": {"parent": _unparented()},
		}
		b = {
			"Cube":   {"parent": _parented_object()},
			"Sphere": {"parent": _parented_bone()},
		}
		result = diff_all_parents(a, b)
		assert len(result) == 2

	def test_returns_list_of_parent_diff(self):
		a = {"Cube": {"parent": _unparented()}}
		b = {"Cube": {"parent": _parented_object()}}
		result = diff_all_parents(a, b)
		assert all(isinstance(r, ParentDiff) for r in result)

	def test_missing_parent_key_treated_as_unparented(self):
		"""Snapshots taken before parent diffing was added have no 'parent' key."""
		a = {"Cube": {}}
		b = {"Cube": {}}
		assert diff_all_parents(a, b) == []

	def test_empty_dicts(self):
		assert diff_all_parents({}, {}) == []

	def test_result_sorted_by_name(self):
		a = {
			"Zebra": {"parent": _unparented()},
			"Apple": {"parent": _unparented()},
		}
		b = {
			"Zebra": {"parent": _parented_object("Rig")},
			"Apple": {"parent": _parented_object("Rig")},
		}
		result = diff_all_parents(a, b)
		assert [r.object_name for r in result] == ["Apple", "Zebra"]


# ParentDiff.summary

class TestParentDiffSummary:
	def test_no_changes_summary(self):
		d = ParentDiff(object_name="Cube", changes=[])
		assert "no parent changes" in d.summary()

	def test_summary_contains_object_name(self):
		d = ParentDiff(object_name="Cube", changes=[])
		assert "Cube" in d.summary()

	def test_summary_shows_changes(self):
		c = PropertyChange(
			property_path="parent.parent_name",
			old_value=None,
			new_value="Armature",
		)
		d = ParentDiff(object_name="Cube", changes=[c])
		summary = d.summary()
		assert "parent.parent_name" in summary
		assert "Armature" in summary