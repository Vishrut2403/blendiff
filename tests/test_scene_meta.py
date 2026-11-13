"""
tests/test_scene_meta.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Timeline markers and unit settings.

Neither was captured at all, and both cost more than their size suggests.
Markers record shot boundaries and can bind a camera, so moving one changes
where an edit lands and a changed binding changes what renders. Units decide
what every number in the file means: switching metric to imperial leaves the
geometry untouched and every measurement reading differently.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.diff_engine.scene_meta_diff import (
	diff_timeline_markers,
	diff_unit_settings,
)
from blendiff.extractor.scene_meta_extractor import (
	extract_timeline_markers,
	extract_unit_settings,
)


class Marker:
	def __init__(self, name, frame, camera=None):
		self.name = name
		self.frame = frame
		self.camera = camera


class Scene:
	def __init__(self, markers=(), units=None):
		self.timeline_markers = list(markers)
		self.unit_settings = units


class Units:
	def __init__(self, **kwargs):
		self.__dict__.update(kwargs)


class TestExtractingMarkers:

	def test_markers_are_recorded_with_frame_and_camera(self):
		scene = Scene([Marker("shot_010", 24, Marker("Camera", 0))])
		assert extract_timeline_markers(scene) == [
			{"name": "shot_010", "frame": 24, "camera": "Camera"},
		]

	def test_an_unbound_marker_records_no_camera(self):
		scene = Scene([Marker("shot_010", 24)])
		assert extract_timeline_markers(scene)[0]["camera"] is None

	def test_markers_come_back_in_frame_order(self):
		# Two snapshots of the same timeline must compare equal whatever
		# order Blender happens to hold them in.
		scene = Scene([Marker("b", 50), Marker("a", 10), Marker("c", 30)])
		assert [m["name"] for m in extract_timeline_markers(scene)] == ["a", "c", "b"]

	def test_a_scene_with_no_markers_records_an_empty_list(self):
		assert extract_timeline_markers(Scene()) == []


class TestExtractingUnits:

	def test_units_are_recorded(self):
		scene = Scene(units=Units(system="METRIC", scale_length=1.0,
		                          length_unit="METERS", use_separate=False))
		recorded = extract_unit_settings(scene)

		assert recorded["system"] == "METRIC"
		assert recorded["scale_length"] == 1.0
		assert recorded["use_separate"] is False

	def test_an_attribute_this_blender_lacks_is_left_out(self):
		# Absent must mean "not captured", never a value nobody set.
		scene = Scene(units=Units(system="METRIC"))
		recorded = extract_unit_settings(scene)

		assert recorded == {"system": "METRIC"}

	def test_a_scene_with_no_unit_settings_records_nothing(self):
		assert extract_unit_settings(Scene()) == {}


class TestDiffingMarkers:

	def _m(self, name, frame, camera=None):
		return {"name": name, "frame": frame, "camera": camera}

	def test_a_moved_marker_is_reported(self):
		changes = diff_timeline_markers(
			[self._m("shot_010", 24)], [self._m("shot_010", 48)],
		)
		assert [(c.property_path, c.old_value, c.new_value) for c in changes] == [
			('markers["shot_010"].frame', 24, 48),
		]

	def test_a_changed_camera_binding_is_reported(self):
		changes = diff_timeline_markers(
			[self._m("shot_010", 24)], [self._m("shot_010", 24, "CamB")],
		)
		assert [c.property_path for c in changes] == ['markers["shot_010"].camera']

	def test_added_and_removed_markers_are_reported_once(self):
		changes = diff_timeline_markers(
			[self._m("old", 10)], [self._m("new", 20)],
		)
		paths = sorted(c.property_path for c in changes)
		assert paths == ['markers["new"]', 'markers["old"]']

	def test_inserting_a_marker_does_not_disturb_the_others(self):
		# Matched by name, so inserting one does not report every marker
		# after it as changed.
		before = [self._m("a", 10), self._m("c", 30)]
		after = [self._m("a", 10), self._m("b", 20), self._m("c", 30)]

		assert [c.property_path for c in diff_timeline_markers(before, after)] == [
			'markers["b"]',
		]

	def test_an_unchanged_timeline_reports_nothing(self):
		markers = [self._m("a", 10), self._m("b", 20)]
		assert diff_timeline_markers(markers, list(markers)) == []

	def test_a_marker_name_with_a_quote_survives_the_path(self):
		changes = diff_timeline_markers(
			[self._m('say "hi"', 1)], [self._m('say "hi"', 2)],
		)
		assert changes[0].property_path == 'markers["say \\"hi\\""].frame'


class TestDiffingUnits:

	def test_a_changed_system_is_reported(self):
		changes = diff_unit_settings({"system": "METRIC"}, {"system": "IMPERIAL"})
		assert [(c.property_path, c.old_value, c.new_value) for c in changes] == [
			("units.system", "METRIC", "IMPERIAL"),
		]

	def test_unchanged_units_report_nothing(self):
		assert diff_unit_settings({"system": "METRIC"}, {"system": "METRIC"}) == []

	def test_a_field_only_one_side_recorded_is_not_a_change(self):
		before = {"system": "METRIC"}
		after = {"system": "METRIC", "temperature_unit": "KELVIN"}
		assert diff_unit_settings(before, after) == []

	def test_a_snapshot_from_before_units_were_captured_invents_nothing(self):
		assert diff_unit_settings(None, {"system": "METRIC"}) == []
