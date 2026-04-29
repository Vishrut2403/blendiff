from __future__ import annotations

import pytest
from blendiff.diff_engine.custom_prop_diff import diff_custom_props, diff_all_custom_props
from blendiff.data_model.custom_prop_diff import CustomPropDiff
from blendiff.data_model.diff import PropertyChange


# Fixtures 

def _props(**kwargs) -> dict:
	return dict(kwargs)


# diff_custom_props: no changes 

class TestNoChanges:
	def test_both_empty(self):
		assert diff_custom_props("Cube", {}, {}).changes == []

	def test_identical_int(self):
		assert diff_custom_props("Cube", {"hp": 100}, {"hp": 100}).changes == []

	def test_identical_float(self):
		assert diff_custom_props("Cube", {"scale": 1.5}, {"scale": 1.5}).changes == []

	def test_identical_string(self):
		assert diff_custom_props("Cube", {"tag": "hero"}, {"tag": "hero"}).changes == []

	def test_identical_bool(self):
		assert diff_custom_props("Cube", {"active": True}, {"active": True}).changes == []

	def test_identical_list(self):
		assert diff_custom_props("Cube", {"rgb": [1.0, 0.5, 0.0]}, {"rgb": [1.0, 0.5, 0.0]}).changes == []

	def test_float_epsilon_no_false_positive(self):
		a = {"val": 1.0}
		b = {"val": 1.0 + 1e-7}
		assert diff_custom_props("Cube", a, b).changes == []

	def test_returns_custom_prop_diff(self):
		assert isinstance(diff_custom_props("Cube", {}, {}), CustomPropDiff)

	def test_object_name_set(self):
		assert diff_custom_props("MyObj", {}, {}).object_name == "MyObj"


# Property added / removed 

class TestAddedRemoved:
	def test_prop_added(self):
		result = diff_custom_props("Cube", {}, {"hp": 100})
		assert any(c.property_path == "custom_props.hp" for c in result.changes)

	def test_prop_added_old_is_none(self):
		result = diff_custom_props("Cube", {}, {"hp": 100})
		c = next(x for x in result.changes if x.property_path == "custom_props.hp")
		assert c.old_value is None
		assert c.new_value == 100

	def test_prop_removed(self):
		result = diff_custom_props("Cube", {"hp": 100}, {})
		assert any(c.property_path == "custom_props.hp" for c in result.changes)

	def test_prop_removed_new_is_none(self):
		result = diff_custom_props("Cube", {"hp": 100}, {})
		c = next(x for x in result.changes if x.property_path == "custom_props.hp")
		assert c.old_value == 100
		assert c.new_value is None

	def test_multiple_props_added(self):
		result = diff_custom_props("Cube", {}, {"hp": 100, "tag": "hero"})
		paths = [c.property_path for c in result.changes]
		assert "custom_props.hp" in paths
		assert "custom_props.tag" in paths


# Value changes 

class TestValueChanges:
	def test_int_changed(self):
		result = diff_custom_props("Cube", {"hp": 100}, {"hp": 50})
		assert any(c.property_path == "custom_props.hp" for c in result.changes)

	def test_int_change_values(self):
		result = diff_custom_props("Cube", {"hp": 100}, {"hp": 50})
		c = next(x for x in result.changes if x.property_path == "custom_props.hp")
		assert c.old_value == 100
		assert c.new_value == 50

	def test_float_changed(self):
		result = diff_custom_props("Cube", {"weight": 1.0}, {"weight": 2.5})
		assert any(c.property_path == "custom_props.weight" for c in result.changes)

	def test_float_above_epsilon(self):
		result = diff_custom_props("Cube", {"val": 1.0}, {"val": 1.001})
		assert any(c.property_path == "custom_props.val" for c in result.changes)

	def test_string_changed(self):
		result = diff_custom_props("Cube", {"tag": "hero"}, {"tag": "villain"})
		assert any(c.property_path == "custom_props.tag" for c in result.changes)

	def test_bool_changed(self):
		result = diff_custom_props("Cube", {"active": True}, {"active": False})
		assert any(c.property_path == "custom_props.active" for c in result.changes)

	def test_list_element_changed(self):
		result = diff_custom_props("Cube", {"rgb": [1.0, 0.0, 0.0]}, {"rgb": [0.0, 1.0, 0.0]})
		assert any(c.property_path == "custom_props.rgb" for c in result.changes)

	def test_list_length_changed(self):
		result = diff_custom_props("Cube", {"data": [1, 2]}, {"data": [1, 2, 3]})
		assert any(c.property_path == "custom_props.data" for c in result.changes)

	def test_type_changed_int_to_string(self):
		result = diff_custom_props("Cube", {"id": 1}, {"id": "one"})
		assert any(c.property_path == "custom_props.id" for c in result.changes)


# None handling 

class TestNoneHandling:
	def test_both_none_treated_as_empty(self):
		assert diff_custom_props("Cube", None, None).changes == []

	def test_a_none_vs_props(self):
		result = diff_custom_props("Cube", None, {"hp": 100})
		assert any(c.property_path == "custom_props.hp" for c in result.changes)

	def test_b_none_vs_props(self):
		result = diff_custom_props("Cube", {"hp": 100}, None)
		assert any(c.property_path == "custom_props.hp" for c in result.changes)

	def test_changes_are_property_change_instances(self):
		result = diff_custom_props("Cube", {}, {"hp": 100})
		for c in result.changes:
			assert isinstance(c, PropertyChange)


# Custom prefix 

class TestCustomPrefix:
	def test_custom_prefix_applied(self):
		result = diff_custom_props(
			"Cube", {}, {"hp": 100}, prefix="objects.Cube.custom_props"
		)
		assert all(
			p.startswith("objects.Cube.custom_props.")
			for p in [c.property_path for c in result.changes]
		)


# diff_all_custom_props 

class TestDiffAllCustomProps:
	def _wrap(self, props: dict) -> dict:
		return {"custom_props": props}

	def test_no_changes_empty(self):
		objs = {"Cube": self._wrap({})}
		assert diff_all_custom_props(objs, objs) == []

	def test_detects_change(self):
		a = {"Cube": self._wrap({})}
		b = {"Cube": self._wrap({"hp": 100})}
		result = diff_all_custom_props(a, b)
		assert len(result) == 1
		assert result[0].object_name == "Cube"

	def test_skips_objects_only_in_a(self):
		a = {"Cube": self._wrap({}), "Sphere": self._wrap({})}
		b = {"Cube": self._wrap({"hp": 100})}
		names = [r.object_name for r in diff_all_custom_props(a, b)]
		assert "Sphere" not in names

	def test_skips_objects_only_in_b(self):
		a = {"Cube": self._wrap({})}
		b = {"Cube": self._wrap({"hp": 100}), "Sphere": self._wrap({})}
		names = [r.object_name for r in diff_all_custom_props(a, b)]
		assert "Sphere" not in names

	def test_missing_key_treated_as_empty(self):
		"""Old snapshots without custom_props key don't crash."""
		a = {"Cube": {}}
		b = {"Cube": {}}
		assert diff_all_custom_props(a, b) == []

	def test_empty_dicts(self):
		assert diff_all_custom_props({}, {}) == []

	def test_result_sorted_by_name(self):
		a = {"Zebra": self._wrap({}), "Apple": self._wrap({})}
		b = {"Zebra": self._wrap({"x": 1}), "Apple": self._wrap({"x": 1})}
		result = diff_all_custom_props(a, b)
		assert [r.object_name for r in result] == ["Apple", "Zebra"]

	def test_only_changed_objects_included(self):
		a = {"Cube": self._wrap({"hp": 100}), "Sphere": self._wrap({})}
		b = {"Cube": self._wrap({"hp": 50}), "Sphere": self._wrap({})}
		result = diff_all_custom_props(a, b)
		assert len(result) == 1
		assert result[0].object_name == "Cube"

	def test_returns_custom_prop_diff_instances(self):
		a = {"Cube": self._wrap({})}
		b = {"Cube": self._wrap({"hp": 100})}
		assert all(isinstance(r, CustomPropDiff) for r in diff_all_custom_props(a, b))


# CustomPropDiff.summary 

class TestCustomPropDiffSummary:
	def test_no_changes(self):
		assert "no custom property changes" in CustomPropDiff("Cube", []).summary()

	def test_contains_object_name(self):
		assert "Cube" in CustomPropDiff("Cube", []).summary()

	def test_shows_property_path(self):
		c = PropertyChange("custom_props.hp", 100, 50)
		assert "custom_props.hp" in CustomPropDiff("Cube", [c]).summary()

	def test_shows_values(self):
		c = PropertyChange("custom_props.tag", "hero", "villain")
		summary = CustomPropDiff("Cube", [c]).summary()
		assert "hero" in summary
		assert "villain" in summary


# SceneDiff integration 

class TestSceneDiffIntegration:
	def test_custom_prop_diffs_in_has_changes(self):
		from blendiff.data_model.diff import SceneDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		assert not diff.has_changes
		diff.custom_prop_diffs = [CustomPropDiff("Cube", [
			PropertyChange("custom_props.hp", 100, 50)
		])]
		assert diff.has_changes

	def test_custom_prop_changes_in_summary(self):
		from blendiff.data_model.diff import SceneDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		diff.custom_prop_diffs = [CustomPropDiff("Cube", [
			PropertyChange("custom_props.hp", 100, 50)
		])]
		assert diff.summary()["custom_prop_changes"] == 1