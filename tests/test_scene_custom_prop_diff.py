from __future__ import annotations

import pytest
from blendiff.diff_engine.scene_custom_prop_diff import diff_scene_custom_props
from blendiff.data_model.scene_custom_prop_diff import SceneCustomPropDiff
from blendiff.data_model.diff import PropertyChange


# Fixtures 

def _props(**kwargs) -> dict:
	return dict(kwargs)


# No changes 

class TestNoChanges:
	def test_both_empty(self):
		assert diff_scene_custom_props({}, {}).changes == []

	def test_identical_int(self):
		assert diff_scene_custom_props({"shot": 10}, {"shot": 10}).changes == []

	def test_identical_string(self):
		assert diff_scene_custom_props({"asset": "hero"}, {"asset": "hero"}).changes == []

	def test_identical_float(self):
		assert diff_scene_custom_props({"scale": 1.5}, {"scale": 1.5}).changes == []

	def test_float_epsilon_no_false_positive(self):
		a = {"val": 1.0}
		b = {"val": 1.0 + 1e-7}
		assert diff_scene_custom_props(a, b).changes == []

	def test_returns_scene_custom_prop_diff(self):
		assert isinstance(diff_scene_custom_props({}, {}), SceneCustomPropDiff)

	def test_both_none_treated_as_empty(self):
		assert diff_scene_custom_props(None, None).changes == []


# Added / removed 

class TestAddedRemoved:
	def test_prop_added(self):
		result = diff_scene_custom_props({}, {"shot": 10})
		assert any(c.property_path == "scene.custom_props.shot" for c in result.changes)

	def test_prop_added_old_is_none(self):
		result = diff_scene_custom_props({}, {"shot": 10})
		c = next(x for x in result.changes if "shot" in x.property_path)
		assert c.old_value is None
		assert c.new_value == 10

	def test_prop_removed(self):
		result = diff_scene_custom_props({"shot": 10}, {})
		assert any(c.property_path == "scene.custom_props.shot" for c in result.changes)

	def test_prop_removed_new_is_none(self):
		result = diff_scene_custom_props({"shot": 10}, {})
		c = next(x for x in result.changes if "shot" in x.property_path)
		assert c.old_value == 10
		assert c.new_value is None

	def test_multiple_props_added(self):
		result = diff_scene_custom_props({}, {"shot": 10, "asset": "hero"})
		paths = [c.property_path for c in result.changes]
		assert "scene.custom_props.shot" in paths
		assert "scene.custom_props.asset" in paths


# Value changes 

class TestValueChanges:
	def test_int_changed(self):
		result = diff_scene_custom_props({"shot": 10}, {"shot": 20})
		assert any("shot" in c.property_path for c in result.changes)

	def test_int_values(self):
		result = diff_scene_custom_props({"shot": 10}, {"shot": 20})
		c = next(x for x in result.changes if "shot" in x.property_path)
		assert c.old_value == 10
		assert c.new_value == 20

	def test_string_changed(self):
		result = diff_scene_custom_props({"asset": "hero"}, {"asset": "villain"})
		assert any("asset" in c.property_path for c in result.changes)

	def test_float_changed(self):
		result = diff_scene_custom_props({"scale": 1.0}, {"scale": 2.0})
		assert any("scale" in c.property_path for c in result.changes)

	def test_float_above_epsilon(self):
		result = diff_scene_custom_props({"scale": 1.0}, {"scale": 1.001})
		assert any("scale" in c.property_path for c in result.changes)

	def test_bool_changed(self):
		result = diff_scene_custom_props({"approved": True}, {"approved": False})
		assert any("approved" in c.property_path for c in result.changes)

	def test_changes_are_property_change_instances(self):
		result = diff_scene_custom_props({}, {"shot": 10})
		for c in result.changes:
			assert isinstance(c, PropertyChange)


# Custom prefix 

class TestCustomPrefix:
	def test_custom_prefix_applied(self):
		result = diff_scene_custom_props(
			{}, {"shot": 10}, prefix="scene.meta"
		)
		assert all(p.startswith("scene.meta.") for p in [c.property_path for c in result.changes])


# SceneCustomPropDiff.summary 

class TestSummary:
	def test_no_changes(self):
		assert "no changes" in SceneCustomPropDiff([]).summary()

	def test_shows_property_path(self):
		c = PropertyChange("scene.custom_props.shot", 10, 20)
		assert "scene.custom_props.shot" in SceneCustomPropDiff([c]).summary()

	def test_shows_values(self):
		c = PropertyChange("scene.custom_props.asset", "hero", "villain")
		summary = SceneCustomPropDiff([c]).summary()
		assert "hero" in summary
		assert "villain" in summary


# SceneDiff integration 

class TestSceneDiffIntegration:
	def test_scene_custom_prop_diff_in_has_changes(self):
		from blendiff.data_model.diff import SceneDiff
		from blendiff.data_model.scene_custom_prop_diff import SceneCustomPropDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		assert not diff.has_changes
		diff.scene_custom_prop_diff = SceneCustomPropDiff(changes=[
			PropertyChange("scene.custom_props.shot", 10, 20)
		])
		assert diff.has_changes

	def test_scene_custom_prop_changes_in_summary(self):
		from blendiff.data_model.diff import SceneDiff
		from blendiff.data_model.scene_custom_prop_diff import SceneCustomPropDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		diff.scene_custom_prop_diff = SceneCustomPropDiff(changes=[
			PropertyChange("scene.custom_props.shot", 10, 20)
		])
		assert diff.summary()["scene_custom_prop_changes"] == 1

	def test_none_scene_custom_prop_diff_no_crash(self):
		from blendiff.data_model.diff import SceneDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		assert diff.summary()["scene_custom_prop_changes"] == 0
		assert not diff.has_changes

	def test_empty_scene_custom_prop_diff_no_has_changes(self):
		from blendiff.data_model.diff import SceneDiff
		from blendiff.data_model.scene_custom_prop_diff import SceneCustomPropDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		diff.scene_custom_prop_diff = SceneCustomPropDiff(changes=[])
		assert not diff.has_changes