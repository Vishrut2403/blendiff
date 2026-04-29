from __future__ import annotations

import pytest
from blendiff.diff_engine.constraint_diff import diff_constraint_stack, diff_all_constraints
from blendiff.data_model.constraint_diff import ConstraintDiff
from blendiff.data_model.diff import PropertyChange


# Fixtures 

def _copy_loc(idx=0, name="Copy Location", target="Empty", influence=1.0, enabled=True) -> dict:
	return {
		"index":     idx,
		"name":      name,
		"type":      "COPY_LOCATION",
		"enabled":   enabled,
		"influence": influence,
		"params":    {"target": target, "subtarget": "", "use_x": True, "use_y": True, "use_z": True, "use_offset": False},
	}

def _track_to(idx=1, name="Track To", target="Camera") -> dict:
	return {
		"index":     idx,
		"name":      name,
		"type":      "TRACK_TO",
		"enabled":   True,
		"influence": 1.0,
		"params":    {"target": target, "subtarget": "", "track_axis": "TRACK_Y", "up_axis": "UP_Z"},
	}

def _ik(idx=0, chain=3, iterations=500) -> dict:
	return {
		"index":      idx,
		"name":       "IK",
		"type":       "IK",
		"enabled":    True,
		"influence":  1.0,
		"params":     {"target": "Empty", "subtarget": "Tip", "chain_count": chain, "iterations": iterations},
	}


# diff_constraint_stack: no changes 

class TestNoChanges:
	def test_both_empty(self):
		result = diff_constraint_stack([], [], "Cube")
		assert result.changes == []

	def test_identical_single(self):
		c = _copy_loc()
		assert diff_constraint_stack([c], [c], "Cube").changes == []

	def test_identical_multiple(self):
		stack = [_copy_loc(0), _track_to(1)]
		assert diff_constraint_stack(stack, stack, "Cube").changes == []

	def test_returns_constraint_diff(self):
		assert isinstance(diff_constraint_stack([], [], "Cube"), ConstraintDiff)

	def test_object_name_set(self):
		result = diff_constraint_stack([], [], "MyObj")
		assert result.object_name == "MyObj"

	def test_influence_epsilon_no_false_positive(self):
		a = _copy_loc(influence=1.0)
		b = _copy_loc(influence=1.0 + 1e-7)
		assert diff_constraint_stack([a], [b], "Cube").changes == []


# Structural changes 

class TestStructuralChanges:
	def test_constraint_added(self):
		result = diff_constraint_stack([], [_copy_loc()], "Cube")
		assert any(c.old_value is None for c in result.changes)

	def test_constraint_added_path(self):
		result = diff_constraint_stack([], [_copy_loc()], "Cube")
		assert result.changes[0].property_path == "constraints[0]"

	def test_constraint_removed(self):
		result = diff_constraint_stack([_copy_loc()], [], "Cube")
		assert any(c.new_value is None for c in result.changes)

	def test_constraint_removed_path(self):
		result = diff_constraint_stack([_copy_loc()], [], "Cube")
		assert result.changes[0].property_path == "constraints[0]"

	def test_type_changed(self):
		a = _copy_loc(idx=0)
		b = _track_to(idx=0)
		result = diff_constraint_stack([a], [b], "Cube")
		assert any(c.property_path == "constraints[0].type" for c in result.changes)

	def test_type_changed_values(self):
		a = _copy_loc(idx=0)
		b = _track_to(idx=0)
		result = diff_constraint_stack([a], [b], "Cube")
		c = next(x for x in result.changes if x.property_path == "constraints[0].type")
		assert c.old_value == "COPY_LOCATION"
		assert c.new_value == "TRACK_TO"

	def test_type_change_no_deep_dive(self):
		"""When type changes, only .type is reported — no param noise."""
		a = _copy_loc(idx=0)
		b = _track_to(idx=0)
		result = diff_constraint_stack([a], [b], "Cube")
		paths = [c.property_path for c in result.changes]
		assert len([p for p in paths if p.startswith("constraints[0].")]) == 1


# Property changes 

class TestPropertyChanges:
	def test_name_changed(self):
		a = _copy_loc(name="Copy Location")
		b = _copy_loc(name="Copy Location.001")
		result = diff_constraint_stack([a], [b], "Cube")
		assert any(c.property_path == "constraints[0].name" for c in result.changes)

	def test_enabled_changed(self):
		a = _copy_loc(enabled=True)
		b = _copy_loc(enabled=False)
		result = diff_constraint_stack([a], [b], "Cube")
		assert any(c.property_path == "constraints[0].enabled" for c in result.changes)

	def test_enabled_values(self):
		a = _copy_loc(enabled=True)
		b = _copy_loc(enabled=False)
		result = diff_constraint_stack([a], [b], "Cube")
		c = next(x for x in result.changes if x.property_path == "constraints[0].enabled")
		assert c.old_value is True
		assert c.new_value is False

	def test_influence_changed(self):
		a = _copy_loc(influence=1.0)
		b = _copy_loc(influence=0.5)
		result = diff_constraint_stack([a], [b], "Cube")
		assert any(c.property_path == "constraints[0].influence" for c in result.changes)

	def test_influence_values(self):
		a = _copy_loc(influence=1.0)
		b = _copy_loc(influence=0.5)
		result = diff_constraint_stack([a], [b], "Cube")
		c = next(x for x in result.changes if x.property_path == "constraints[0].influence")
		assert c.old_value == 1.0
		assert c.new_value == 0.5


# Param changes 

class TestParamChanges:
	def test_target_changed(self):
		a = _copy_loc(target="Empty")
		b = _copy_loc(target="Empty.001")
		result = diff_constraint_stack([a], [b], "Cube")
		assert any(c.property_path == "constraints[0].target" for c in result.changes)

	def test_target_values(self):
		a = _copy_loc(target="Empty")
		b = _copy_loc(target="Armature")
		result = diff_constraint_stack([a], [b], "Cube")
		c = next(x for x in result.changes if x.property_path == "constraints[0].target")
		assert c.old_value == "Empty"
		assert c.new_value == "Armature"

	def test_chain_count_changed(self):
		a = _ik(chain=3)
		b = _ik(chain=5)
		result = diff_constraint_stack([a], [b], "Hand")
		assert any("chain_count" in c.property_path for c in result.changes)

	def test_iterations_changed(self):
		a = _ik(iterations=500)
		b = _ik(iterations=200)
		result = diff_constraint_stack([a], [b], "Hand")
		assert any("iterations" in c.property_path for c in result.changes)

	def test_bool_param_changed(self):
		a = _copy_loc()
		b = _copy_loc()
		b["params"]["use_offset"] = True
		result = diff_constraint_stack([a], [b], "Cube")
		assert any("use_offset" in c.property_path for c in result.changes)

	def test_no_param_changes_silent(self):
		a = _copy_loc(target="Empty")
		b = _copy_loc(target="Empty")
		assert diff_constraint_stack([a], [b], "Cube").changes == []


# Multiple constraints 

class TestMultipleConstraints:
	def test_only_changed_slot_reported(self):
		a = [_copy_loc(0), _track_to(1)]
		b = [_copy_loc(0), _track_to(1, target="Sun")]
		result = diff_constraint_stack(a, b, "Cube")
		paths = [c.property_path for c in result.changes]
		assert not any("constraints[0]" in p for p in paths)
		assert any("constraints[1]" in p for p in paths)

	def test_second_constraint_added(self):
		a = [_copy_loc(0)]
		b = [_copy_loc(0), _track_to(1)]
		result = diff_constraint_stack(a, b, "Cube")
		assert any(c.property_path == "constraints[1]" for c in result.changes)

	def test_first_constraint_removed(self):
		a = [_copy_loc(0), _track_to(1)]
		b = [_track_to(1)]
		result = diff_constraint_stack(a, b, "Cube")
		assert any(c.property_path == "constraints[0]" for c in result.changes)


# Custom prefix 

class TestCustomPrefix:
	def test_custom_prefix(self):
		a = _copy_loc(influence=1.0)
		b = _copy_loc(influence=0.5)
		result = diff_constraint_stack([a], [b], "Cube", prefix="objects.Cube.constraints")
		assert all(
			p.startswith("objects.Cube.constraints")
			for p in [c.property_path for c in result.changes]
		)


# diff_all_constraints 

class TestDiffAllConstraints:
	def _wrap(self, stack: list) -> dict:
		return {"constraint_stack": stack}

	def test_no_changes_empty(self):
		objs = {"Cube": self._wrap([])}
		assert diff_all_constraints(objs, objs) == []

	def test_detects_change(self):
		a = {"Cube": self._wrap([])}
		b = {"Cube": self._wrap([_copy_loc()])}
		result = diff_all_constraints(a, b)
		assert len(result) == 1
		assert result[0].object_name == "Cube"

	def test_skips_objects_only_in_a(self):
		a = {"Cube": self._wrap([]), "Sphere": self._wrap([])}
		b = {"Cube": self._wrap([_copy_loc()])}
		names = [r.object_name for r in diff_all_constraints(a, b)]
		assert "Sphere" not in names

	def test_skips_objects_only_in_b(self):
		a = {"Cube": self._wrap([])}
		b = {"Cube": self._wrap([_copy_loc()]), "Sphere": self._wrap([])}
		names = [r.object_name for r in diff_all_constraints(a, b)]
		assert "Sphere" not in names

	def test_missing_key_treated_as_empty(self):
		"""Old snapshots without constraint_stack key don't crash."""
		a = {"Cube": {}}
		b = {"Cube": {}}
		assert diff_all_constraints(a, b) == []

	def test_empty_dicts(self):
		assert diff_all_constraints({}, {}) == []

	def test_result_sorted_by_name(self):
		a = {"Zebra": self._wrap([]), "Apple": self._wrap([])}
		b = {
			"Zebra": self._wrap([_copy_loc()]),
			"Apple": self._wrap([_copy_loc()]),
		}
		result = diff_all_constraints(a, b)
		assert [r.object_name for r in result] == ["Apple", "Zebra"]

	def test_only_changed_objects_included(self):
		a = {"Cube": self._wrap([_copy_loc()]), "Sphere": self._wrap([])}
		b = {"Cube": self._wrap([_copy_loc(influence=0.5)]), "Sphere": self._wrap([])}
		result = diff_all_constraints(a, b)
		assert len(result) == 1
		assert result[0].object_name == "Cube"

	def test_returns_constraint_diff_instances(self):
		a = {"Cube": self._wrap([])}
		b = {"Cube": self._wrap([_copy_loc()])}
		assert all(isinstance(r, ConstraintDiff) for r in diff_all_constraints(a, b))


# ConstraintDiff.summary 

class TestConstraintDiffSummary:
	def test_no_changes(self):
		assert "no constraint changes" in ConstraintDiff("Cube", []).summary()

	def test_contains_object_name(self):
		assert "Cube" in ConstraintDiff("Cube", []).summary()

	def test_shows_property_path(self):
		c = PropertyChange("constraints[0].influence", 1.0, 0.5)
		assert "constraints[0].influence" in ConstraintDiff("Cube", [c]).summary()

	def test_shows_values(self):
		c = PropertyChange("constraints[0].target", "Empty", "Armature")
		summary = ConstraintDiff("Cube", [c]).summary()
		assert "Empty" in summary
		assert "Armature" in summary


# SceneDiff integration 

class TestSceneDiffIntegration:
	def test_constraint_diffs_in_has_changes(self):
		from blendiff.data_model.diff import SceneDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		assert not diff.has_changes
		diff.constraint_diffs = [ConstraintDiff("Cube", [
			PropertyChange("constraints[0].influence", 1.0, 0.5)
		])]
		assert diff.has_changes

	def test_constraint_changes_in_summary(self):
		from blendiff.data_model.diff import SceneDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		diff.constraint_diffs = [ConstraintDiff("Cube", [
			PropertyChange("constraints[0].influence", 1.0, 0.5)
		])]
		assert diff.summary()["constraint_changes"] == 1