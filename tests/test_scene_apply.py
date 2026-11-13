"""
tests/test_scene_apply.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
Writing scene-wide changes back to a scene.

Render settings, units, markers, the world and the scene's own custom
properties were diffed, built into a merge proposal, and then skipped with
"scene changes must be applied manually". Two people bumping the sample count
were shown the collision and left to fix it by hand, which is the one thing a
merge tool exists to avoid.

The snapshot flattens several structs into one dict, so most of what these
tests check is that a value lands in the right place: file_format belongs to
render.image_settings and exposure to view_settings, and writing either onto
the scene itself would be a silent no-op in real Blender.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import fake_bpy
from fake_bpy import (
	FakeNode,
	FakeNodeSocket,
	FakeObject,
	FakeWorld,
)

from blendiff.data_model.conflict import (
	MergeProposal,
	NonConflictingChange,
	TargetKind,
	ThreeWayDiff,
)
from blendiff.merge_engine.applier import Applier
from blendiff.merge_engine.property_appliers import can_apply, unsupported_reason


@pytest.fixture
def bpy():
	module = fake_bpy.install()
	yield module
	fake_bpy.uninstall()


def _apply(*changes):
	"""Apply a scene proposal carrying these changes, and report the outcome."""
	proposal = MergeProposal(object_name="Scene", target_kind=TargetKind.SCENE)
	for path, value in changes:
		proposal.non_conflicting_from_a.append(NonConflictingChange(
			property_path=path, base_value=None, new_value=value, source="a",
		))
	return Applier().apply_all(
		ThreeWayDiff(base_label="Base", label_a="A", label_b="B",
		             proposals=[proposal]),
		context=None,
	)


class TestRenderSettings:
	def test_a_setting_on_the_render_struct(self, bpy):
		result = _apply(("render.resolution_x", 3840))
		assert result.failed == []
		assert bpy.context.scene.render.resolution_x == 3840

	def test_a_setting_on_the_scene_itself(self, bpy):
		_apply(("render.frame_end", 500))
		assert bpy.context.scene.frame_end == 500

	def test_a_setting_two_structs_down(self, bpy):
		# file_format lives on render.image_settings, not on render.
		_apply(("render.file_format", "OPEN_EXR"))
		assert bpy.context.scene.render.image_settings.file_format == "OPEN_EXR"

	def test_colour_management_settings(self, bpy):
		_apply(("render.view_transform", "AgX"), ("render.exposure", 1.5))
		assert bpy.context.scene.view_settings.view_transform == "AgX"
		assert bpy.context.scene.view_settings.exposure == 1.5

	def test_an_engine_setting(self, bpy):
		_apply(("render.cycles.samples", 4096))
		assert bpy.context.scene.cycles.samples == 4096

	def test_a_setting_this_blender_lacks_is_refused(self, bpy):
		# EEVEE's settings were rewritten in 4.2, so a snapshot from an older
		# file carries keys this Blender has never heard of.
		result = _apply(("render.eevee.use_bloom", True))
		assert result.applied == []
		assert "does not exist in Blender" in result.failed[0].detail

	def test_the_format_is_written_before_the_depth_it_resets(self, bpy):
		# Blender resets color_depth and color_mode when file_format changes:
		# EXR means 32-bit float, JPEG means 8-bit RGB. Written in path order,
		# "color_depth" goes first and the format then throws it away.
		written: list[str] = []

		class Recording:
			file_format = "PNG"
			color_depth = "8"

			def __setattr__(self, name, value):
				written.append(name)
				object.__setattr__(self, name, value)

		bpy.context.scene.render.image_settings = Recording()
		_apply(("render.color_depth", "32"), ("render.file_format", "OPEN_EXR"))
		assert written == ["file_format", "color_depth"]

	def test_a_missing_engine_is_refused(self, bpy):
		del bpy.context.scene.cycles
		result = _apply(("render.cycles.samples", 256))
		assert "no cycles settings" in result.failed[0].detail


class TestUnits:
	def test_the_unit_system(self, bpy):
		_apply(("units.system", "IMPERIAL"))
		assert bpy.context.scene.unit_settings.system == "IMPERIAL"

	def test_the_system_is_written_before_what_depends_on_it(self, bpy):
		# length_unit is only valid within a system, and "units.length_unit"
		# sorts before "units.system". Writing them in path order would set a
		# unit the scene has not switched to yet.
		written: list[tuple[str, object]] = []

		class Recording:
			system = "METRIC"
			length_unit = "METERS"

			def __setattr__(self, name, value):
				written.append((name, value))
				object.__setattr__(self, name, value)

		bpy.context.scene.unit_settings = Recording()
		_apply(("units.length_unit", "FEET"), ("units.system", "IMPERIAL"))
		assert [name for name, _ in written] == ["system", "length_unit"]

	def test_an_unknown_unit_setting_is_refused(self, bpy):
		result = _apply(("units.temperature_unit", "FAHRENHEIT"))
		assert "does not exist in Blender" in result.failed[0].detail


class TestMarkers:
	def test_a_marker_is_moved(self, bpy):
		bpy.context.scene.timeline_markers.new("shot_010", frame=24)
		_apply(('markers["shot_010"].frame', 96))
		assert bpy.context.scene.timeline_markers["shot_010"].frame == 96

	def test_a_marker_is_created(self, bpy):
		# Unlike an object, a marker is fully described by the snapshot, so
		# creating one is a merge rather than a fabrication.
		result = _apply(('markers["shot_020"]', 48))
		assert result.failed == []
		assert bpy.context.scene.timeline_markers["shot_020"].frame == 48

	def test_a_marker_is_removed(self, bpy):
		bpy.context.scene.timeline_markers.new("shot_010", frame=24)
		_apply(('markers["shot_010"]', None))
		assert bpy.context.scene.timeline_markers.get("shot_010") is None

	def test_removing_a_marker_that_is_already_gone_is_not_a_failure(self, bpy):
		result = _apply(('markers["shot_010"]', None))
		assert result.failed == []

	def test_a_camera_binding(self, bpy):
		camera = FakeObject("Camera", "CAMERA")
		bpy.data.objects.add(camera)
		bpy.context.scene.timeline_markers.new("shot_010", frame=24)

		_apply(('markers["shot_010"].camera', "Camera"))
		assert bpy.context.scene.timeline_markers["shot_010"].camera is camera

	def test_a_camera_binding_is_cleared(self, bpy):
		marker = bpy.context.scene.timeline_markers.new("shot_010", frame=24)
		marker.camera = FakeObject("Camera", "CAMERA")

		_apply(('markers["shot_010"].camera', None))
		assert marker.camera is None

	def test_a_camera_outside_the_scene_is_refused(self, bpy):
		bpy.context.scene.timeline_markers.new("shot_010", frame=24)
		result = _apply(('markers["shot_010"].camera', "Elsewhere"))
		assert "not in this" in result.failed[0].detail

	def test_a_field_on_a_marker_that_is_gone_is_refused(self, bpy):
		result = _apply(('markers["shot_010"].frame', 96))
		assert "no marker named" in result.failed[0].detail

	def test_a_quoted_marker_name_round_trips(self, bpy):
		bpy.context.scene.timeline_markers.new('say "hi"', frame=1)
		_apply((r'markers["say \"hi\""].frame', 10))
		assert bpy.context.scene.timeline_markers.get('say "hi"').frame == 10


class TestSceneCustomProps:
	def test_a_property_is_set(self, bpy):
		_apply(("custom_props.shot", "010"))
		assert bpy.context.scene["shot"] == "010"

	def test_a_property_is_deleted(self, bpy):
		bpy.context.scene["shot"] = "010"
		_apply(("custom_props.shot", None))
		assert "shot" not in bpy.context.scene

	def test_deleting_one_that_is_gone_is_not_a_failure(self, bpy):
		result = _apply(("custom_props.shot", None))
		assert result.failed == []


class TestWorld:
	def test_a_flat_colour(self, bpy):
		bpy.context.scene.world = FakeWorld()
		_apply(("world.color", [0.1, 0.2, 0.3]))
		assert bpy.context.scene.world.color == [0.1, 0.2, 0.3]

	def test_ambient_occlusion(self, bpy):
		bpy.context.scene.world = FakeWorld()
		_apply(("world.use_ao", True), ("world.ao_distance", 5.0))
		assert bpy.context.scene.world.light_settings.use_ambient_occlusion is True
		assert bpy.context.scene.world.light_settings.distance == 5.0

	def test_a_scene_without_a_world_is_refused(self, bpy):
		result = _apply(("world.color", [0.1, 0.2, 0.3]))
		assert "no world" in result.failed[0].detail

	def test_the_background_strength(self, bpy):
		socket = FakeNodeSocket("Strength", "VALUE", 1.0)
		bpy.context.scene.world = FakeWorld(
			use_nodes=True,
			nodes=[FakeNode("Background", "BACKGROUND", inputs=[socket])],
		)
		result = _apply(("world.background_strength", 2.5))
		assert result.failed == []
		assert socket.default_value == pytest.approx(2.5)

	def test_the_background_colour(self, bpy):
		socket = FakeNodeSocket("Color", "RGBA", [0.05, 0.05, 0.05, 1.0])
		bpy.context.scene.world = FakeWorld(
			use_nodes=True,
			nodes=[FakeNode("Background", "BACKGROUND", inputs=[socket])],
		)
		_apply(("world.background_color", [1.0, 0.5, 0.0, 1.0]))
		assert socket.default_value == [1.0, 0.5, 0.0, 1.0]

	def test_an_hdri_fed_socket_is_not_written(self, bpy):
		# The colour comes from an Environment Texture, so writing a flat one
		# would report success and change nothing on screen.
		socket = FakeNodeSocket("Color", "RGBA", [0.05, 0.05, 0.05, 1.0],
		                        is_linked=True)
		bpy.context.scene.world = FakeWorld(
			use_nodes=True,
			nodes=[FakeNode("Background", "BACKGROUND", inputs=[socket])],
		)
		result = _apply(("world.background_color", [1.0, 0.5, 0.0, 1.0]))
		assert "comes from another node" in result.failed[0].detail

	def test_a_node_free_world_says_where_to_set_it_instead(self, bpy):
		bpy.context.scene.world = FakeWorld()
		result = _apply(("world.background_strength", 2.5))
		assert "flat colour" in result.failed[0].detail

	def test_a_world_without_a_background_node_is_refused(self, bpy):
		bpy.context.scene.world = FakeWorld(use_nodes=True, nodes=[])
		result = _apply(("world.background_strength", 2.5))
		assert "no Background node" in result.failed[0].detail


class TestUnapplicable:
	@pytest.mark.parametrize("path, expected", [
		("scene.world", "Assigning a different world"),
		("scene.world.name", "Assigning a different world"),
		("scene.world.use_nodes", "replaces the whole graph"),
		("scene.world.hdri_filepath", "image datablock"),
		("scene.world.hdri_strength", "image datablock"),
	])
	def test_reason_is_specific(self, path, expected):
		assert not can_apply(path)
		assert expected in unsupported_reason(path)

	def test_an_unknown_scene_path_still_reads_as_a_scene_limit(self):
		assert "scene setting" in unsupported_reason("scene.render.something_new")

	def test_a_scene_path_is_not_confused_with_an_object_property(self):
		# "filepath" is a render setting on a scene and nothing at all on an
		# object, so only the fully qualified spelling may be applicable.
		assert can_apply("scene.render.filepath")
		assert not can_apply("filepath")


def test_collections_are_still_reported_rather_than_written(bpy):
	proposal = MergeProposal(
		object_name="Scene Collection/Props", target_kind=TargetKind.COLLECTION,
	)
	proposal.non_conflicting_from_a.append(NonConflictingChange(
		property_path="objects", base_value=None, new_value=["Cube"], source="a",
	))
	result = Applier().apply_all(
		ThreeWayDiff(base_label="Base", label_a="A", label_b="B",
		             proposals=[proposal]),
		context=None,
	)
	assert result.applied == []
	assert "manually" in result.skipped[0].detail
