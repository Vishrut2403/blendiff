"""
tests/test_driver_apply.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Writing driver changes back to a scene.

Drivers were diffed field by field and could not be applied at all, so every
driver conflict was read-only. The expression, the driver type and use_self
are each one assignment on an existing driver; its variables are not, because
the diff only carries their names. These tests pin both halves down, and in
particular that an empty expression is never written over a working one.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import fake_bpy
from fake_bpy import FakeAnimData, FakeDriver, FakeDrivenCurve, FakeObject

from blendiff.data_model.paths import escape_name
from blendiff.diff_engine.driver_diff import diff_drivers
from blendiff.merge_engine.property_appliers import (
	apply_property,
	can_apply,
	unsupported_reason,
)


@pytest.fixture
def bpy():
	module = fake_bpy.install()
	yield module
	fake_bpy.uninstall()


def _rig(bpy, *curves):
	obj = FakeObject("Rig")
	obj.animation_data = FakeAnimData(curves)
	bpy.data.objects.add(obj)
	return obj


def _path(data_path, index=0, field="expression"):
	return f'drivers["{escape_name(data_path)}"][{index}].{field}'


class TestDriverFields:
	def test_writes_an_expression(self, bpy):
		curve = FakeDrivenCurve("location", 0, FakeDriver("SCRIPTED", "var * 2"))
		obj = _rig(bpy, curve)

		assert apply_property(obj, _path("location"), "var * 3", bpy.context)
		assert curve.driver.expression == "var * 3"

	def test_writes_the_driver_type(self, bpy):
		curve = FakeDrivenCurve("location", 0, FakeDriver("AVERAGE"))
		obj = _rig(bpy, curve)

		apply_property(obj, _path("location", field="driver_type"), "SUM", bpy.context)
		assert curve.driver.type == "SUM"

	def test_writes_use_self(self, bpy):
		curve = FakeDrivenCurve("location", 0, FakeDriver("SCRIPTED", "self.x"))
		obj = _rig(bpy, curve)

		apply_property(obj, _path("location", field="use_self"), True, bpy.context)
		assert curve.driver.use_self is True

	def test_the_array_index_picks_the_right_channel(self, bpy):
		x = FakeDrivenCurve("location", 0, FakeDriver("SCRIPTED", "x"))
		z = FakeDrivenCurve("location", 2, FakeDriver("SCRIPTED", "z"))
		obj = _rig(bpy, x, z)

		apply_property(obj, _path("location", 2), "z * 2", bpy.context)
		assert z.driver.expression == "z * 2"
		assert x.driver.expression == "x"

	def test_a_bone_data_path_round_trips(self, bpy):
		# The driven path has brackets and quotes of its own, which is why
		# driver paths quote and escape it.
		data_path = 'pose.bones["Head"].location'
		curve = FakeDrivenCurve(data_path, 1, FakeDriver("SCRIPTED", "old"))
		obj = _rig(bpy, curve)

		path = _path(data_path, 1)
		assert can_apply(path)
		apply_property(obj, path, "new", bpy.context)
		assert curve.driver.expression == "new"

	def test_an_empty_expression_is_not_written_over_a_working_one(self, bpy):
		# The extractor records "" for every non-SCRIPTED driver. Taking that
		# side of a merge must not wipe the expression the rig depends on.
		curve = FakeDrivenCurve("location", 0, FakeDriver("AVERAGE", "var * 2"))
		obj = _rig(bpy, curve)

		with pytest.raises(ValueError, match="evaluates no expression"):
			apply_property(obj, _path("location"), "", bpy.context)
		assert curve.driver.expression == "var * 2"

	def test_a_missing_driver_is_refused(self, bpy):
		obj = _rig(bpy, FakeDrivenCurve("location", 0))

		with pytest.raises(ValueError, match="no driver on"):
			apply_property(obj, _path("rotation_euler"), "x", bpy.context)

	def test_an_object_without_animation_data_is_refused(self, bpy):
		obj = FakeObject("Rig")
		bpy.data.objects.add(obj)

		with pytest.raises(ValueError, match="no animation data"):
			apply_property(obj, _path("location"), "x", bpy.context)


class TestUnapplicable:
	@pytest.mark.parametrize("path, expected", [
		('drivers["location"][0].variables', "driver editor"),
		('drivers["location"][0]', "Adding or removing a driver"),
	])
	def test_reason_is_specific(self, path, expected):
		assert not can_apply(path)
		assert expected in unsupported_reason(path)

	def test_no_generic_fallback_for_driver_paths(self):
		assert "driver" in unsupported_reason('drivers["location"][0].something').lower()


def test_the_diff_and_the_applier_agree_on_the_path_shape():
	def driver(expression, driver_type="SCRIPTED", use_self=False):
		return [{
			"data_path": 'pose.bones["Head"].location',
			"array_index": 1,
			"driver_type": driver_type,
			"expression": expression,
			"use_self": use_self,
			"variables": [],
		}]

	changes = diff_drivers("Rig", driver("a"), driver("b", "SUM", True)).changes
	assert len(changes) == 3
	assert all(can_apply(change.property_path) for change in changes)
