"""
tests/test_visibility_flags.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Display and ray visibility switches, on objects and on collections.

Only hide_viewport and hide_render were captured, so every other way of making
something behave differently was invisible. Switching off an object's
visible_shadow removes its shadow while it stays in frame; switching off a
collection's hide_render removes a whole set of objects from the render. Both
reported a clean scene.

The serializer is why these tests exist in this shape. It rebuilds every dict
from an explicit list of fields, which is deliberate, because it is what keeps
raw bpy values out of the sidecar. It also means a field the extractor starts
recording reaches nothing until it is named there too, and the first attempt
at these flags captured nothing at all for exactly that reason. A unit test
over plain dicts would not have noticed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.data_model import schema
from blendiff.diff_engine.diff_engine import DiffEngine
from blendiff.serializer.scene_serializer import SceneSerializer


def _raw_object(**flags):
	obj = {
		"name": "Cube", "type": "MESH", "collection_path": "Scene Collection",
		"transform": {
			"location": [0, 0, 0], "rotation_euler": [0, 0, 0],
			"scale": [1, 1, 1], "rotation_mode": "XYZ",
		},
		"visible": True, "hide_viewport": False, "hide_render": False,
		"visible_in_viewlayer": True,
	}
	obj.update(flags)
	return obj


def _raw_scene(obj_flags=None, col_flags=None):
	return {
		"blender_version": "4.1.0",
		"scene_name": "Scene",
		"objects": {"Cube": _raw_object(**(obj_flags or {}))},
		"collections": {
			"Scene Collection": dict({
				"name": "Scene Collection", "path": "Scene Collection",
				"children": [], "objects": ["Cube"],
			}, **(col_flags or {})),
		},
		"render": {}, "world": None, "scene_custom_props": {},
	}


class TestTheSerializerCarriesTheFlags:
	"""The gate that silently dropped them the first time."""

	def test_every_object_flag_survives_serialization(self):
		flags = {name: ("WIRE" if name == "display_type" else False)
		         for name in schema.VISIBILITY_FLAGS}
		out = SceneSerializer().serialize(_raw_scene(obj_flags=flags))["objects"]["Cube"]

		missing = [name for name in schema.VISIBILITY_FLAGS if name not in out]
		assert not missing, f"dropped by the serializer: {missing}"

	def test_every_collection_flag_survives_serialization(self):
		names = schema.COLLECTION_FLAGS + schema.COLLECTION_LAYER_FLAGS
		flags = {name: ("COLOR_01" if name == "color_tag" else True) for name in names}
		out = SceneSerializer().serialize(
			_raw_scene(col_flags=flags))["collections"]["Scene Collection"]

		missing = [name for name in names if name not in out]
		assert not missing, f"dropped by the serializer: {missing}"

	def test_a_flag_that_was_not_recorded_stays_absent(self):
		"""Absent must mean "not captured", not "False"."""
		out = SceneSerializer().serialize(_raw_scene())["objects"]["Cube"]

		assert "visible_shadow" not in out
		assert "is_holdout" not in out


class TestObjectFlagsAreDiffed:

	def test_a_changed_ray_visibility_flag_is_reported(self):
		before = SceneSerializer().serialize(_raw_scene(obj_flags={"visible_shadow": True}))
		after = SceneSerializer().serialize(_raw_scene(obj_flags={"visible_shadow": False}))

		diff = DiffEngine().compare(before, after)
		paths = [c.property_path for o in diff.modified_objects for c in o.changes]
		assert paths == ["visible_shadow"]

	def test_display_type_is_reported(self):
		before = SceneSerializer().serialize(_raw_scene(obj_flags={"display_type": "TEXTURED"}))
		after = SceneSerializer().serialize(_raw_scene(obj_flags={"display_type": "WIRE"}))

		diff = DiffEngine().compare(before, after)
		change = diff.modified_objects[0].changes[0]
		assert change.property_path == "display_type"
		assert (change.old_value, change.new_value) == ("TEXTURED", "WIRE")

	def test_an_older_snapshot_without_them_invents_nothing(self):
		before = SceneSerializer().serialize(_raw_scene())
		after = SceneSerializer().serialize(_raw_scene(obj_flags={
			name: ("WIRE" if name == "display_type" else False)
			for name in schema.VISIBILITY_FLAGS
		}))

		assert DiffEngine().compare(before, after).modified_objects == []


class TestCollectionFlagsAreDiffed:

	def test_turning_a_collection_off_for_render_is_reported(self):
		before = SceneSerializer().serialize(_raw_scene(col_flags={"hide_render": False}))
		after = SceneSerializer().serialize(_raw_scene(col_flags={"hide_render": True}))

		diffs = DiffEngine().compare(before, after).collection_diffs
		assert [c.property_path for d in diffs for c in d.changes] == ["hide_render"]

	def test_excluding_a_collection_in_the_view_layer_is_reported(self):
		before = SceneSerializer().serialize(_raw_scene(col_flags={"exclude": False}))
		after = SceneSerializer().serialize(_raw_scene(col_flags={"exclude": True}))

		diffs = DiffEngine().compare(before, after).collection_diffs
		assert [c.property_path for d in diffs for c in d.changes] == ["exclude"]

	def test_an_older_snapshot_without_them_invents_nothing(self):
		before = SceneSerializer().serialize(_raw_scene())
		after = SceneSerializer().serialize(_raw_scene(col_flags={
			"hide_viewport": True, "hide_render": True, "exclude": True,
		}))

		assert DiffEngine().compare(before, after).collection_diffs == []
