"""
tests/test_object_data.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Type-specific data for the nine object types that had none.

Four of Blender's thirteen object types had their data captured: meshes,
armatures, cameras and lights. The rest had a transform, modifiers and
constraints recorded and nothing else, so changing a text object's contents or
a curve's bevel depth produced no diff and BlenDiff called the scene clean.

The extractor reads by attribute name, so it tests against stand-ins without
needing Blender. What needs real bpy is whether the attribute names are right,
and that is covered by the in-Blender suite.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.diff_engine.diff_engine import DiffEngine
from blendiff.extractor.object_data_extractor import (
	SUPPORTED_TYPES,
	extract_object_data,
)
from blendiff.serializer.scene_serializer import SceneSerializer


class Stub:
	def __init__(self, **kwargs):
		self.__dict__.update(kwargs)


class Obj:
	def __init__(self, obj_type, data=None, **own):
		self.type = obj_type
		self.data = data
		self.name = "Thing"
		self.__dict__.update(own)


class TestExtraction:

	def test_a_curve_records_its_shape_settings(self):
		curve = Stub(dimensions="3D", resolution_u=12, render_resolution_u=0,
		             bevel_depth=0.25, bevel_resolution=4, extrude=0.0,
		             offset=0.0, fill_mode="FULL", use_fill_caps=False,
		             twist_mode="MINIMUM", taper_object=None, bevel_object=None)
		data = extract_object_data(Obj("CURVE", curve))

		assert data["bevel_depth"] == 0.25
		assert data["dimensions"] == "3D"

	def test_a_text_object_records_its_contents(self):
		text = Stub(body="Hello", size=1.0, shear=0.0, space_character=1.0,
		            space_word=1.0, space_line=1.0, align_x="LEFT",
		            align_y="TOP", offset_x=0.0, offset_y=0.0, extrude=0.0,
		            bevel_depth=0.0, font=None)
		assert extract_object_data(Obj("FONT", text))["body"] == "Hello"

	def test_an_empty_reads_from_the_object_not_a_datablock(self):
		# Empties have no data block at all, which is the one case that
		# cannot follow the same path as the others.
		empty = Obj("EMPTY", None, empty_display_type="PLAIN_AXES",
		            empty_display_size=3.0, empty_image_depth=False)
		data = extract_object_data(empty)

		assert data == {"display_type": "PLAIN_AXES", "display_size": 3.0,
		                "image_depth": False}

	def test_datablock_references_are_recorded_by_name(self):
		# A pointer means nothing once the file is reopened; the name does.
		curve = Stub(dimensions="2D", resolution_u=12, render_resolution_u=0,
		             bevel_depth=0.0, bevel_resolution=0, extrude=0.0,
		             offset=0.0, fill_mode="BOTH", use_fill_caps=False,
		             twist_mode="MINIMUM",
		             taper_object=Stub(name="TaperCurve"), bevel_object=None)
		data = extract_object_data(Obj("CURVE", curve))

		assert data["taper_object"] == "TaperCurve"
		assert data["bevel_object"] is None

	def test_a_type_with_its_own_extractor_returns_nothing_here(self):
		# Meshes, armatures, cameras and lights are covered elsewhere. None
		# rather than {} keeps "not handled" distinct from "handled, empty".
		assert extract_object_data(Obj("MESH", Stub())) is None
		assert extract_object_data(Obj("CAMERA", Stub())) is None

	def test_an_object_whose_data_is_missing_is_not_fatal(self):
		assert extract_object_data(Obj("CURVE", None)) is None

	def test_a_property_this_blender_lacks_is_left_out_not_recorded_as_none(self):
		"""
		Absent must mean "not captured", never a value.

		Properties come and go between Blender versions. Recording a missing
		one as None would make a snapshot from an older build differ from a
		newer one on every property the older build lacked.
		"""
		class OldBlender:
			resolution = 0.4
			# no render_resolution, no threshold

		data = extract_object_data(Obj("META", OldBlender()))
		assert data == {"resolution": 0.4}

	def test_one_unreadable_property_does_not_cost_the_others(self):
		class Hostile:
			resolution = 0.4
			render_resolution = 0.2

			@property
			def threshold(self):
				raise RuntimeError("this property is broken")

		data = extract_object_data(Obj("META", Hostile()))
		assert data["resolution"] == 0.4
		assert "threshold" not in data

	def test_every_supported_type_is_one_blender_actually_has(self):
		assert SUPPORTED_TYPES == {
			"CURVE", "SURFACE", "FONT", "META", "LATTICE",
			"EMPTY", "VOLUME", "SPEAKER",
			# Grease pencil as rewritten in 4.3. The older GPENCIL type has
			# none of these properties, so it is not claimed here.
			"GREASEPENCIL",
		}


class TestDiffing:

	def _scene(self, object_data):
		return SceneSerializer().serialize({
			"blender_version": "4.1.0",
			"scene_name": "Scene",
			"objects": {"Thing": {
				"name": "Thing", "type": "CURVE",
				"collection_path": "Scene Collection",
				"transform": {"location": [0, 0, 0], "rotation_euler": [0, 0, 0],
				              "scale": [1, 1, 1], "rotation_mode": "XYZ"},
				"visible": True, "object_data": object_data,
			}},
			"collections": {}, "render": {}, "world": None,
			"scene_custom_props": {},
		})

	def test_a_changed_setting_is_reported(self):
		before = self._scene({"bevel_depth": 0.0})
		after = self._scene({"bevel_depth": 0.25})

		diff = DiffEngine().compare(before, after)
		change = diff.modified_objects[0].changes[0]
		assert change.property_path == "data.bevel_depth"
		assert (change.old_value, change.new_value) == (0.0, 0.25)

	def test_float_noise_is_not_a_change(self):
		before = self._scene({"bevel_depth": 0.25})
		after = self._scene({"bevel_depth": 0.2500000001})

		assert DiffEngine().compare(before, after).modified_objects == []

	def test_a_snapshot_from_before_the_feature_invents_nothing(self):
		before = self._scene(None)
		after = self._scene({"bevel_depth": 0.25, "resolution_u": 12})

		assert DiffEngine().compare(before, after).modified_objects == []

	def test_a_key_only_one_side_recorded_is_not_a_change(self):
		before = self._scene({"bevel_depth": 0.0})
		after = self._scene({"bevel_depth": 0.0, "twist_mode": "MINIMUM"})

		assert DiffEngine().compare(before, after).modified_objects == []
