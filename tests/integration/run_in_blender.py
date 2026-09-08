"""
tests/integration/run_in_blender.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Integration tests executed *inside* Blender.

Why these exist
---------------
Every other test in this repo feeds synthetic dicts to pure functions. That is
the right shape for the diff engine, but it left the entire ``extractor``
package — the only code that touches real Blender data, and the only code that
can break when Blender's API changes — with no coverage at all. The layered
action API used for F-curves in Blender 5.x is exactly the kind of thing that
fails silently and is never noticed.

Run with::

    blender --background --factory-startup --python tests/integration/run_in_blender.py

Scenes are built programmatically rather than loaded from committed .blend
fixtures: .blend is a binary format tied to a Blender version, so fixtures rot
and cannot be reviewed in a diff. Building the scene in code keeps the tests
readable and portable across versions.

pytest is not available inside Blender's bundled Python, so this file carries a
minimal harness and reports results as a machine-readable summary line that the
pytest wrapper parses.
"""

import json
import os
import sys
import traceback

import bpy

# The repo root, so `blendiff` imports without installation.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
	sys.path.insert(0, _REPO_ROOT)

from blendiff.data_model import schema
from blendiff.diff_engine.diff_engine import DiffEngine
from blendiff.extractor.identity import ID_KEY, read_id, stamp_scene
from blendiff.extractor.scene_extractor import SceneExtractor
from blendiff.serializer.scene_serializer import SceneSerializer


# Minimal test harness

_RESULTS = []


def test(fn):
	"""Register a test function."""
	_RESULTS.append(fn)
	return fn


def check(condition, message):
	if not condition:
		raise AssertionError(message)


def check_eq(actual, expected, message=""):
	if actual != expected:
		raise AssertionError(f"{message}\n  expected: {expected!r}\n  actual:   {actual!r}")


def check_close(actual, expected, tol=1e-5, message=""):
	if abs(actual - expected) > tol:
		raise AssertionError(f"{message}: {actual!r} != {expected!r} (tol {tol})")


# Scene construction helpers

def reset_scene():
	"""Return to an empty factory scene."""
	bpy.ops.wm.read_factory_settings(use_empty=True)
	return bpy.context.scene


def add_mesh(name, location=(0, 0, 0)):
	mesh = bpy.data.meshes.new(f"{name}_mesh")
	obj = bpy.data.objects.new(name, mesh)
	obj.location = location
	bpy.context.scene.collection.objects.link(obj)

	# A single triangle, so mesh statistics are non-trivial.
	mesh.from_pydata(
		[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
		[],
		[(0, 1, 2)],
	)
	mesh.update()
	return obj


def extract():
	return SceneExtractor.extract(bpy.context)


def extract_and_serialize(stamp=False):
	raw = SceneExtractor.extract(bpy.context, stamp_identity=stamp)
	return SceneSerializer().serialize(raw)


# Schema and structure

@test
def test_extract_stamps_schema_version():
	reset_scene()
	add_mesh("Cube")
	data = extract()
	check_eq(data["schema_version"], schema.SCHEMA_VERSION, "schema version stamped")


@test
def test_extract_declares_captured_domains():
	reset_scene()
	add_mesh("Cube")
	domains = set(extract()["captured_domains"])
	for domain in schema.ALL_DOMAINS:
		check(domain in domains, f"domain {domain} should be declared captured")


@test
def test_extract_declares_local_transform_space():
	reset_scene()
	add_mesh("Cube")
	check_eq(extract()["transform_space"], schema.TRANSFORM_SPACE_LOCAL,
	         "transforms must be recorded as local")


@test
def test_serialized_scene_is_json_round_trippable():
	"""Snapshots are stored as JSON; a stray bpy type would break saving."""
	reset_scene()
	obj = add_mesh("Cube")
	obj["custom_int"] = 3
	obj["custom_vec"] = [1.0, 2.0, 3.0]
	cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
	bpy.context.scene.collection.objects.link(cam)

	scene = extract_and_serialize()
	text = json.dumps(scene)
	check(json.loads(text) == scene, "scene must survive a JSON round trip")


# Local transforms

@test
def test_transform_is_local_not_world():
	"""
	The bug this guards: transforms were decomposed from matrix_world, so
	moving a parent reported a change on every child, and the merge applier
	wrote world-space values into local-space properties.
	"""
	reset_scene()
	parent = add_mesh("Parent", location=(10.0, 0.0, 0.0))
	child = add_mesh("Child", location=(1.0, 0.0, 0.0))
	child.parent = parent
	bpy.context.view_layer.update()

	data = extract()
	loc = data["objects"]["Child"]["transform"]["location"]
	check_close(loc[0], 1.0, message="child location must stay local")


@test
def test_moving_parent_does_not_change_child_transform():
	reset_scene()
	parent = add_mesh("Parent")
	child = add_mesh("Child", location=(1.0, 0.0, 0.0))
	child.parent = parent
	bpy.context.view_layer.update()
	before = extract_and_serialize()

	parent.location = (25.0, 13.0, -4.0)
	bpy.context.view_layer.update()
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	changed = {d.name for d in diff.modified_objects}
	check("Parent" in changed, "the parent's own move must be reported")
	check("Child" not in changed,
	      "moving a parent must not report a change on untouched children")


@test
def test_rotation_mode_is_captured():
	reset_scene()
	obj = add_mesh("Cube")
	obj.rotation_mode = "QUATERNION"
	data = extract()
	transform = data["objects"]["Cube"]["transform"]
	check_eq(transform["rotation_mode"], "QUATERNION", "rotation mode captured")
	check("rotation_quaternion" in transform,
	      "quaternion-mode objects must record their quaternion")


@test
def test_axis_angle_mode_is_captured():
	reset_scene()
	obj = add_mesh("Cube")
	obj.rotation_mode = "AXIS_ANGLE"
	transform = extract()["objects"]["Cube"]["transform"]
	check("rotation_axis_angle" in transform, "axis-angle values recorded")


# Identity

@test
def test_extract_does_not_stamp_by_default():
	"""A read-only diff must not modify the .blend."""
	reset_scene()
	obj = add_mesh("Cube")
	extract()
	check(read_id(obj) is None, "plain extraction must not write an identity")


@test
def test_extract_stamps_when_asked():
	reset_scene()
	obj = add_mesh("Cube")
	SceneExtractor.extract(bpy.context, stamp_identity=True)
	check(read_id(obj) is not None, "capture must stamp an identity")


@test
def test_identity_survives_rename():
	reset_scene()
	obj = add_mesh("Cube")
	before = extract_and_serialize(stamp=True)

	obj.name = "Body_LOW"
	after = extract_and_serialize(stamp=True)

	diff = DiffEngine().compare(before, after)
	check_eq(len(diff.renamed_objects), 1, "rename must be detected as a rename")
	check_eq(diff.renamed_objects[0].previous_name, "Cube")
	check_eq(diff.added_objects, [], "a rename is not an addition")
	check_eq(diff.removed_objects, [], "a rename is not a removal")


@test
def test_rename_preserves_other_changes():
	reset_scene()
	obj = add_mesh("Cube")
	before = extract_and_serialize(stamp=True)

	obj.name = "Body_LOW"
	obj.location = (5.0, 0.0, 0.0)
	after = extract_and_serialize(stamp=True)

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check("transform.location" in paths,
	      "edits made alongside a rename must survive")


@test
def test_identity_is_hidden_from_custom_props():
	"""BlenDiff's bookkeeping must not appear as a user custom property."""
	reset_scene()
	add_mesh("Cube")
	data = SceneExtractor.extract(bpy.context, stamp_identity=True)
	props = data["objects"]["Cube"]["custom_props"]
	check(ID_KEY not in props, "the identity key must not surface as user data")


@test
def test_stamping_is_stable_across_calls():
	reset_scene()
	obj = add_mesh("Cube")
	SceneExtractor.extract(bpy.context, stamp_identity=True)
	first = read_id(obj)
	SceneExtractor.extract(bpy.context, stamp_identity=True)
	check_eq(read_id(obj), first, "an existing identity must never be replaced")


@test
def test_stamp_scene_reports_count():
	reset_scene()
	add_mesh("A")
	add_mesh("B")
	check_eq(stamp_scene(bpy.context.scene), 2, "both objects stamped")
	check_eq(stamp_scene(bpy.context.scene), 0, "already-stamped objects are skipped")


# Collections

@test
def test_collection_path_is_full_path():
	"""
	Previously only the bare collection *name* was recorded, which could not
	be matched against the collection tree keyed by full path.
	"""
	reset_scene()
	scene = bpy.context.scene
	props = bpy.data.collections.new("Props")
	scene.collection.children.link(props)

	obj = add_mesh("Cube")
	scene.collection.objects.unlink(obj)
	props.objects.link(obj)

	data = extract()
	path = data["objects"]["Cube"]["collection_path"]
	check("/" in path, f"expected a full path, got {path!r}")
	check(path in data["collections"],
	      "an object's collection path must exist in the collection tree")


@test
def test_multi_collection_membership_is_recorded():
	"""An object linked into several collections used to lose all but one."""
	reset_scene()
	scene = bpy.context.scene
	props = bpy.data.collections.new("Props")
	renderable = bpy.data.collections.new("Renderable")
	scene.collection.children.link(props)
	scene.collection.children.link(renderable)

	obj = add_mesh("Cube")
	props.objects.link(obj)
	renderable.objects.link(obj)

	paths = extract()["objects"]["Cube"]["collection_paths"]
	check_eq(len(paths), 3, f"expected three memberships, got {paths}")


@test
def test_nested_collection_tree_is_walked():
	reset_scene()
	scene = bpy.context.scene
	outer = bpy.data.collections.new("Outer")
	inner = bpy.data.collections.new("Inner")
	scene.collection.children.link(outer)
	outer.children.link(inner)

	collections = extract()["collections"]
	nested = [p for p in collections if p.endswith("Outer/Inner")]
	check(nested, f"nested collection path missing from {list(collections)}")


# Visibility

@test
def test_viewport_and_render_visibility_are_independent():
	reset_scene()
	obj = add_mesh("Cube")
	obj.hide_viewport = False
	obj.hide_render = True

	data = extract()["objects"]["Cube"]
	check_eq(data["visible"], True, "viewport visibility")
	check_eq(data["hide_render"], True, "render visibility tracked separately")


@test
def test_render_visibility_change_is_detected():
	reset_scene()
	obj = add_mesh("Cube")
	before = extract_and_serialize()
	obj.hide_render = True
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check("hide_render" in paths, "disabling render visibility must be reported")


# Data blocks

@test
def test_camera_data_extracted():
	reset_scene()
	cam_data = bpy.data.cameras.new("Cam")
	cam_data.lens = 85.0
	cam = bpy.data.objects.new("Cam", cam_data)
	bpy.context.scene.collection.objects.link(cam)

	data = extract()["objects"]["Cam"]["camera_data"]
	check_close(data["focal_length"], 85.0, message="focal length")


@test
def test_light_data_extracted():
	reset_scene()
	light_data = bpy.data.lights.new("Lamp", type="POINT")
	light_data.energy = 500.0
	light = bpy.data.objects.new("Lamp", light_data)
	bpy.context.scene.collection.objects.link(light)

	data = extract()["objects"]["Lamp"]["light_data"]
	check_close(data["energy"], 500.0, message="light energy")


@test
def test_mesh_summary_extracted():
	reset_scene()
	add_mesh("Cube")
	data = extract()["objects"]["Cube"]["mesh_data"]
	check_eq(data["vertex_count"], 3, "vertex count")
	check_eq(data["face_count"], 1, "face count")


@test
def test_modifier_stack_extracted():
	reset_scene()
	obj = add_mesh("Cube")
	modifier = obj.modifiers.new("Subdiv", "SUBSURF")
	modifier.levels = 3

	stack = extract()["objects"]["Cube"]["modifier_stack"]
	check_eq(len(stack), 1, "one modifier expected")
	check_eq(stack[0]["type"], "SUBSURF", "modifier type")


@test
def test_constraint_stack_extracted():
	reset_scene()
	target = add_mesh("Target")
	obj = add_mesh("Cube")
	constraint = obj.constraints.new("COPY_LOCATION")
	constraint.target = target

	stack = extract()["objects"]["Cube"]["constraint_stack"]
	check_eq(len(stack), 1, "one constraint expected")
	check_eq(stack[0]["type"], "COPY_LOCATION", "constraint type")
	check("influence" in stack[0], "influence must be captured")
	check("enabled" in stack[0], "enabled must be captured")


@test
def test_parent_info_extracted():
	reset_scene()
	parent = add_mesh("Rig")
	child = add_mesh("Cube")
	child.parent = parent

	info = extract()["objects"]["Cube"]["parent"]
	check_eq(info["parent_name"], "Rig", "parent name")


@test
def test_custom_props_extracted():
	reset_scene()
	obj = add_mesh("Cube")
	obj["rig_version"] = 4
	obj["author"] = "vfx"

	props = extract()["objects"]["Cube"]["custom_props"]
	check_eq(props["rig_version"], 4, "int custom prop")
	check_eq(props["author"], "vfx", "string custom prop")


# Animation — the API most likely to break between Blender versions

@test
def test_fcurves_extracted():
	"""
	Guards the Blender 4.x / 5.x action API split. Blender 5 moved F-curves
	behind layers and channelbags; the legacy path silently yields nothing.
	"""
	reset_scene()
	obj = add_mesh("Cube")
	obj.location = (0.0, 0.0, 0.0)
	obj.keyframe_insert(data_path="location", frame=1)
	obj.location = (5.0, 0.0, 0.0)
	obj.keyframe_insert(data_path="location", frame=24)

	curves = extract()["objects"]["Cube"]["fcurves"]
	check(curves, f"expected F-curves on Blender {bpy.app.version_string}")
	check(any(c["keyframe_count"] == 2 for c in curves),
	      f"expected a 2-keyframe curve, got {curves}")


@test
def test_fcurve_frame_range_extracted():
	reset_scene()
	obj = add_mesh("Cube")
	obj.keyframe_insert(data_path="location", frame=5)
	obj.location = (1.0, 0.0, 0.0)
	obj.keyframe_insert(data_path="location", frame=40)

	curves = extract()["objects"]["Cube"]["fcurves"]
	check(curves, "F-curves expected")
	check_close(curves[0]["frame_start"], 5.0, message="frame start")
	check_close(curves[0]["frame_end"], 40.0, message="frame end")


@test
def test_keyframe_change_is_detected():
	reset_scene()
	obj = add_mesh("Cube")
	obj.keyframe_insert(data_path="location", frame=1)
	before = extract_and_serialize()

	obj.location = (3.0, 0.0, 0.0)
	obj.keyframe_insert(data_path="location", frame=30)
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	check(diff.fcurve_diffs, "adding a keyframe must produce an F-curve diff")


@test
def test_drivers_extracted():
	reset_scene()
	obj = add_mesh("Cube")
	fcurve = obj.driver_add("location", 0)
	fcurve.driver.type = "SCRIPTED"
	fcurve.driver.expression = "frame * 0.5"

	drivers = extract()["objects"]["Cube"]["drivers"]
	check(drivers, "expected a driver")
	check_eq(drivers[0]["expression"], "frame * 0.5", "driver expression")


@test
def test_nla_tracks_extracted():
	reset_scene()
	obj = add_mesh("Cube")
	obj.keyframe_insert(data_path="location", frame=1)
	action = obj.animation_data.action

	track = obj.animation_data.nla_tracks.new()
	track.name = "BaseLayer"
	track.strips.new("Walk", 1, action)

	tracks = extract()["objects"]["Cube"]["nla_tracks"]
	check(tracks, "expected an NLA track")
	check_eq(tracks[0]["name"], "BaseLayer", "track name")


# Scene-level

@test
def test_render_settings_extracted():
	reset_scene()
	scene = bpy.context.scene
	scene.render.resolution_x = 3840
	scene.render.resolution_y = 2160

	render = extract()["render"]
	check_eq(render["resolution_x"], 3840, "resolution x")
	check_eq(render["resolution_y"], 2160, "resolution y")


@test
def test_scene_custom_props_extracted():
	reset_scene()
	bpy.context.scene["shot_id"] = "SH010"
	props = extract()["scene_custom_props"]
	check_eq(props.get("shot_id"), "SH010", "scene custom property")


@test
def test_world_extracted():
	reset_scene()
	scene = bpy.context.scene
	scene.world = bpy.data.worlds.new("World")
	world = extract()["world"]
	check(world is not None, "world data expected")


# Full pipeline

@test
def test_unchanged_scene_produces_no_diff():
	"""
	The strongest end-to-end signal: extracting the same scene twice must be
	byte-identical, or every diff would be full of phantom noise.
	"""
	reset_scene()
	add_mesh("Cube")
	cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
	bpy.context.scene.collection.objects.link(cam)

	first = extract_and_serialize()
	second = extract_and_serialize()

	diff = DiffEngine().compare(first, second)
	check(not diff.has_changes,
	      f"identical scenes must not differ, got {diff.summary()}")


@test
def test_real_edit_is_detected_end_to_end():
	reset_scene()
	obj = add_mesh("Cube")
	before = extract_and_serialize()

	obj.location = (7.0, 2.0, 0.0)
	obj.hide_render = True
	obj["note"] = "reviewed"
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check("transform.location" in paths, "location change")
	check("hide_render" in paths, "render visibility change")
	check(diff.custom_prop_diffs, "custom property change")


@test
def test_added_and_removed_objects_detected():
	reset_scene()
	add_mesh("Keep")
	doomed = add_mesh("Doomed")
	before = extract_and_serialize(stamp=True)

	bpy.data.objects.remove(doomed, do_unlink=True)
	add_mesh("Fresh")
	after = extract_and_serialize(stamp=True)

	diff = DiffEngine().compare(before, after)
	check_eq([d.name for d in diff.added_objects], ["Fresh"], "added")
	check_eq([d.name for d in diff.removed_objects], ["Doomed"], "removed")


@test
def test_no_domains_skipped_between_two_current_snapshots():
	reset_scene()
	add_mesh("Cube")
	before = extract_and_serialize()
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	check_eq(diff.skipped_domains, [],
	         "two current snapshots must compare every domain")


# Runner

def main() -> int:
	passed, failed = 0, []

	for fn in _RESULTS:
		try:
			fn()
			passed += 1
		except Exception as exc:
			failed.append((fn.__name__, exc, traceback.format_exc()))

	print("\n" + "=" * 70)
	print(f"BlenDiff integration tests — Blender {bpy.app.version_string}")
	print("=" * 70)

	for name, exc, tb in failed:
		print(f"\nFAILED {name}: {exc}")
		print(tb)

	print(f"\nBLENDIFF_RESULT {json.dumps({'passed': passed, 'failed': len(failed), 'failures': [f[0] for f in failed]})}")
	return 1 if failed else 0


if __name__ == "__main__":
	sys.exit(main())
