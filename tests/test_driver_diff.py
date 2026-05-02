from __future__ import annotations

import pytest
from blendiff.diff_engine.driver_diff import diff_drivers, diff_all_drivers
from blendiff.data_model.driver_diff import DriverDiff
from blendiff.data_model.diff import PropertyChange


# Fixtures 

def _var(name="var", type="SINGLE_PROP", data_path="location", bone="") -> dict:
	return {
		"name": name,
		"type": type,
		"targets": [{"id_type": "OBJECT", "data_path": data_path,
					 "bone_target": bone, "transform_type": None,
					 "transform_space": None}],
	}

def _driver(
	data_path="location",
	array_index=0,
	driver_type="AVERAGE",
	expression="",
	use_self=False,
	variables=None,
) -> dict:
	return {
		"data_path":   data_path,
		"array_index": array_index,
		"driver_type": driver_type,
		"expression":  expression,
		"use_self":    use_self,
		"variables":   variables if variables is not None else [_var()],
	}

def _scripted(expression="var * 2", **kw) -> dict:
	return _driver(driver_type="SCRIPTED", expression=expression, **kw)


# diff_drivers: no changes 

class TestNoChanges:
	def test_both_empty(self):
		assert diff_drivers("Cube", [], []).changes == []

	def test_identical_single(self):
		d = _driver()
		assert diff_drivers("Cube", [d], [d]).changes == []

	def test_identical_scripted(self):
		d = _scripted()
		assert diff_drivers("Cube", [d], [d]).changes == []

	def test_identical_multiple(self):
		drivers = [_driver("location", 0), _driver("rotation_euler", 0)]
		assert diff_drivers("Cube", drivers, drivers).changes == []

	def test_returns_driver_diff(self):
		assert isinstance(diff_drivers("Cube", [], []), DriverDiff)

	def test_object_name_set(self):
		assert diff_drivers("MyObj", [], []).object_name == "MyObj"


# Structural changes 

class TestStructuralChanges:
	def test_driver_added(self):
		result = diff_drivers("Cube", [], [_driver()])
		assert len(result.changes) == 1
		assert result.changes[0].old_value is None

	def test_driver_added_path(self):
		result = diff_drivers("Cube", [], [_driver("location", 0)])
		assert "location" in result.changes[0].property_path
		assert "[0]" in result.changes[0].property_path

	def test_driver_added_new_value_is_type(self):
		result = diff_drivers("Cube", [], [_driver(driver_type="AVERAGE")])
		assert result.changes[0].new_value == "AVERAGE"

	def test_driver_removed(self):
		result = diff_drivers("Cube", [_driver()], [])
		assert len(result.changes) == 1
		assert result.changes[0].new_value is None

	def test_driver_removed_old_value_is_type(self):
		result = diff_drivers("Cube", [_driver(driver_type="SUM")], [])
		assert result.changes[0].old_value == "SUM"

	def test_second_driver_added(self):
		a = [_driver("location", 0)]
		b = [_driver("location", 0), _driver("rotation_euler", 0)]
		result = diff_drivers("Cube", a, b)
		assert any("rotation_euler" in c.property_path for c in result.changes)


# Property changes 

class TestDriverTypeChanges:
	def test_type_changed(self):
		a = _driver(driver_type="AVERAGE")
		b = _driver(driver_type="SUM")
		result = diff_drivers("Cube", [a], [b])
		assert any("driver_type" in c.property_path for c in result.changes)

	def test_type_values(self):
		a = _driver(driver_type="AVERAGE")
		b = _driver(driver_type="SUM")
		result = diff_drivers("Cube", [a], [b])
		c = next(x for x in result.changes if "driver_type" in x.property_path)
		assert c.old_value == "AVERAGE"
		assert c.new_value == "SUM"


class TestExpressionChanges:
	def test_expression_changed(self):
		a = _scripted(expression="var * 2")
		b = _scripted(expression="var * 3")
		result = diff_drivers("Cube", [a], [b])
		assert any("expression" in c.property_path for c in result.changes)

	def test_expression_values(self):
		a = _scripted(expression="var * 2")
		b = _scripted(expression="var + 1")
		result = diff_drivers("Cube", [a], [b])
		c = next(x for x in result.changes if "expression" in x.property_path)
		assert c.old_value == "var * 2"
		assert c.new_value == "var + 1"

	def test_empty_expression_no_change(self):
		a = _driver(driver_type="AVERAGE", expression="")
		b = _driver(driver_type="AVERAGE", expression="")
		assert diff_drivers("Cube", [a], [b]).changes == []


class TestUseSelfChanges:
	def test_use_self_changed(self):
		a = _driver(use_self=False)
		b = _driver(use_self=True)
		result = diff_drivers("Cube", [a], [b])
		assert any("use_self" in c.property_path for c in result.changes)

	def test_use_self_values(self):
		a = _driver(use_self=False)
		b = _driver(use_self=True)
		result = diff_drivers("Cube", [a], [b])
		c = next(x for x in result.changes if "use_self" in x.property_path)
		assert c.old_value is False
		assert c.new_value is True


class TestVariableChanges:
	def test_variable_added(self):
		a = _driver(variables=[_var("x")])
		b = _driver(variables=[_var("x"), _var("y")])
		result = diff_drivers("Cube", [a], [b])
		assert any("variables" in c.property_path for c in result.changes)

	def test_variable_removed(self):
		a = _driver(variables=[_var("x"), _var("y")])
		b = _driver(variables=[_var("x")])
		result = diff_drivers("Cube", [a], [b])
		assert any("variables" in c.property_path for c in result.changes)

	def test_variable_renamed(self):
		a = _driver(variables=[_var("x")])
		b = _driver(variables=[_var("renamed")])
		result = diff_drivers("Cube", [a], [b])
		assert any("variables" in c.property_path for c in result.changes)

	def test_variable_unchanged_no_diff(self):
		a = _driver(variables=[_var("x")])
		b = _driver(variables=[_var("x")])
		assert diff_drivers("Cube", [a], [b]).changes == []

	def test_variable_values_show_names(self):
		a = _driver(variables=[_var("x")])
		b = _driver(variables=[_var("x"), _var("y")])
		result = diff_drivers("Cube", [a], [b])
		c = next(x for x in result.changes if "variables" in x.property_path)
		assert c.old_value == ["x"]
		assert c.new_value == ["x", "y"]


# Multiple drivers 

class TestMultipleDrivers:
	def test_only_changed_driver_reported(self):
		a = [_driver("location", 0), _driver("rotation_euler", 0)]
		b = [_driver("location", 0), _driver("rotation_euler", 0, driver_type="SUM")]
		result = diff_drivers("Cube", a, b)
		paths = [c.property_path for c in result.changes]
		assert not any("location" in p for p in paths)
		assert any("rotation_euler" in p for p in paths)

	def test_unchanged_drivers_silent(self):
		drivers = [_driver("location", 0), _driver("location", 1)]
		assert diff_drivers("Cube", drivers, drivers).changes == []


# Custom prefix 

class TestCustomPrefix:
	def test_custom_prefix_applied(self):
		result = diff_drivers(
			"Cube", [], [_driver()], prefix="objects.Cube.drivers"
		)
		assert all(
			p.startswith("objects.Cube.drivers")
			for p in [c.property_path for c in result.changes]
		)


# None / empty handling 

class TestNoneHandling:
	def test_changes_are_property_change_instances(self):
		result = diff_drivers("Cube", [], [_driver()])
		for c in result.changes:
			assert isinstance(c, PropertyChange)


# diff_all_drivers 

class TestDiffAllDrivers:
	def _wrap(self, drivers: list) -> dict:
		return {"drivers": drivers}

	def test_no_changes_empty(self):
		objs = {"Cube": self._wrap([])}
		assert diff_all_drivers(objs, objs) == []

	def test_detects_change(self):
		a = {"Cube": self._wrap([])}
		b = {"Cube": self._wrap([_driver()])}
		result = diff_all_drivers(a, b)
		assert len(result) == 1
		assert result[0].object_name == "Cube"

	def test_skips_objects_only_in_a(self):
		a = {"Cube": self._wrap([]), "Sphere": self._wrap([])}
		b = {"Cube": self._wrap([_driver()])}
		names = [r.object_name for r in diff_all_drivers(a, b)]
		assert "Sphere" not in names

	def test_skips_objects_only_in_b(self):
		a = {"Cube": self._wrap([])}
		b = {"Cube": self._wrap([_driver()]), "Sphere": self._wrap([])}
		names = [r.object_name for r in diff_all_drivers(a, b)]
		assert "Sphere" not in names

	def test_missing_key_treated_as_empty(self):
		a = {"Cube": {}}
		b = {"Cube": {}}
		assert diff_all_drivers(a, b) == []

	def test_empty_dicts(self):
		assert diff_all_drivers({}, {}) == []

	def test_result_sorted_by_name(self):
		a = {"Zebra": self._wrap([]), "Apple": self._wrap([])}
		b = {"Zebra": self._wrap([_driver()]), "Apple": self._wrap([_driver()])}
		result = diff_all_drivers(a, b)
		assert [r.object_name for r in result] == ["Apple", "Zebra"]

	def test_only_changed_objects_included(self):
		a = {"Cube": self._wrap([_driver(driver_type="AVERAGE")]), "Sphere": self._wrap([])}
		b = {"Cube": self._wrap([_driver(driver_type="SUM")]), "Sphere": self._wrap([])}
		result = diff_all_drivers(a, b)
		assert len(result) == 1
		assert result[0].object_name == "Cube"

	def test_returns_driver_diff_instances(self):
		a = {"Cube": self._wrap([])}
		b = {"Cube": self._wrap([_driver()])}
		assert all(isinstance(r, DriverDiff) for r in diff_all_drivers(a, b))


# DriverDiff.summary 

class TestDriverDiffSummary:
	def test_no_changes(self):
		assert "no driver changes" in DriverDiff("Cube", []).summary()

	def test_contains_object_name(self):
		assert "Cube" in DriverDiff("Cube", []).summary()

	def test_shows_property_path(self):
		c = PropertyChange("drivers[location][0].driver_type", "AVERAGE", "SUM")
		assert "drivers[location][0].driver_type" in DriverDiff("Cube", [c]).summary()

	def test_shows_values(self):
		c = PropertyChange("drivers[location][0].expression", "var * 2", "var * 3")
		summary = DriverDiff("Cube", [c]).summary()
		assert "var * 2" in summary
		assert "var * 3" in summary


# SceneDiff integration 

class TestSceneDiffIntegration:
	def test_driver_diffs_in_has_changes(self):
		from blendiff.data_model.diff import SceneDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		assert not diff.has_changes
		diff.driver_diffs = [DriverDiff("Cube", [
			PropertyChange("drivers[location][0].driver_type", "AVERAGE", "SUM")
		])]
		assert diff.has_changes

	def test_driver_changes_in_summary(self):
		from blendiff.data_model.diff import SceneDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		diff.driver_diffs = [DriverDiff("Cube", [
			PropertyChange("drivers[location][0].driver_type", "AVERAGE", "SUM")
		])]
		assert diff.summary()["driver_changes"] == 1