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
import math
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


def capture_snapshot(blend_path, label):
	"""
	What the Save Snapshot operator does, without needing the addon registered.

	Identities are recovered from the previous snapshot, which is precisely
	what the tests below are checking.
	"""
	from blendiff.storage.sidecar import SidecarManager

	manager = SidecarManager(blend_path)
	raw = SceneExtractor.extract(
		bpy.context, stamp_identity=True, known_ids=manager.latest_object_ids(),
	)
	scene = SceneSerializer().serialize(raw)
	return manager.save_snapshot(label, bpy.context.scene.name, scene)


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
def test_identity_survives_a_session_closed_without_saving():
	"""
	Stamps live in the .blend, but writing a custom property does not mark the
	file dirty, so a user who snapshots and closes loses them. Identity is
	recovered from the previous snapshot, making the sidecar the durable
	record — without this, rename tracking silently degraded to the name
	matching it exists to replace.
	"""
	import tempfile

	reset_scene()
	add_mesh("Cube")
	path = os.path.join(tempfile.mkdtemp(), "identity.blend")
	bpy.ops.wm.save_as_mainfile(filepath=path)

	capture_snapshot(path, "first")
	first = bpy.data.objects["Cube"].get("_blendiff_id")
	check(first is not None, "capture must stamp an identity")

	# Reopen without saving: the stamp is gone from the file.
	bpy.ops.wm.open_mainfile(filepath=path)
	check(bpy.data.objects["Cube"].get("_blendiff_id") is None,
	      "stamp should not have persisted without a save")

	capture_snapshot(path, "second")
	second = bpy.data.objects["Cube"].get("_blendiff_id")
	check_eq(second, first, "identity must be recovered from the last snapshot")


@test
def test_rename_survives_a_session_boundary():
	"""
	The normal path now that stamping marks the file dirty: the user is
	prompted, saves, and identity persists in the .blend across sessions.
	"""
	import tempfile

	reset_scene()
	add_mesh("Cube")
	path = os.path.join(tempfile.mkdtemp(), "rename.blend")
	bpy.ops.wm.save_as_mainfile(filepath=path)
	capture_snapshot(path, "before")

	# Saving is what the dirty flag now prompts for.
	bpy.ops.wm.save_mainfile()
	bpy.ops.wm.open_mainfile(filepath=path)

	bpy.data.objects["Cube"].name = "Body_LOW"
	capture_snapshot(path, "after")

	from blendiff.storage.sidecar import SidecarManager
	snaps = {s.label: s for s in SidecarManager(path).list_snapshots()}
	diff = DiffEngine().compare(snaps["before"].data, snaps["after"].data)

	check_eq(len(diff.renamed_objects), 1,
	         f"rename must survive the session, got {diff.summary()}")


@test
def test_rename_inside_an_unsaved_session_is_a_known_limit():
	"""
	Recovery matches the previous snapshot by name, so an object both renamed
	*and* left unsaved has nothing linking it to its old identity — it reads
	as an add plus a remove.

	This is the honest floor of the approach, asserted so the limit stays
	visible rather than being discovered later as a surprise.
	"""
	import tempfile

	reset_scene()
	add_mesh("Cube")
	path = os.path.join(tempfile.mkdtemp(), "unsaved_rename.blend")
	bpy.ops.wm.save_as_mainfile(filepath=path)
	capture_snapshot(path, "before")

	bpy.ops.wm.open_mainfile(filepath=path)      # stamps discarded
	bpy.data.objects["Cube"].name = "Body_LOW"
	capture_snapshot(path, "after")

	from blendiff.storage.sidecar import SidecarManager
	snaps = {s.label: s for s in SidecarManager(path).list_snapshots()}
	diff = DiffEngine().compare(snaps["before"].data, snaps["after"].data)

	check_eq(len(diff.renamed_objects), 0,
	         "a rename with no stamp and no matching name cannot be recovered")
	check_eq(len(diff.added_objects), 1, "reads as an addition")
	check_eq(len(diff.removed_objects), 1, "and a removal")


@test
def test_stamping_triggers_the_modified_marker():
	"""
	Stamping must flag the file as changed, or the user is never prompted to
	save and the stamps evaporate on close.

	This asserts the *call*, not bpy.data.is_dirty, because that flag's state
	straight after save_as_mainfile differs between Blender versions — it is
	False on 5.1 and True on 4.2 in background mode — which made an earlier
	version of this test fail on its own precondition rather than on the
	behaviour it exists to check.
	"""
	import tempfile

	from blendiff.extractor import identity

	reset_scene()
	add_mesh("Cube")
	path = os.path.join(tempfile.mkdtemp(), "dirty.blend")
	bpy.ops.wm.save_as_mainfile(filepath=path)

	calls = []
	original = identity._mark_file_modified
	identity._mark_file_modified = lambda: calls.append(True)
	try:
		stamped = identity.stamp_scene(bpy.context.scene)
	finally:
		identity._mark_file_modified = original

	check(stamped >= 1, "a fresh object should be stamped")
	check_eq(len(calls), 1, "stamping must mark the file modified exactly once")


@test
def test_no_marker_when_nothing_needed_stamping():
	"""An unchanged file must not be flagged modified for no reason."""
	from blendiff.extractor import identity

	reset_scene()
	add_mesh("Cube")
	identity.stamp_scene(bpy.context.scene)     # everything now stamped

	calls = []
	original = identity._mark_file_modified
	identity._mark_file_modified = lambda: calls.append(True)
	try:
		stamped = identity.stamp_scene(bpy.context.scene)
	finally:
		identity._mark_file_modified = original

	check_eq(stamped, 0, "nothing left to stamp")
	check_eq(calls, [], "must not flag the file modified when nothing changed")


@test
def test_file_is_dirty_after_stamping():
	"""
	The observable consequence, asserted as a postcondition only.

	The starting state of is_dirty is version-dependent, so this checks where
	it ends up rather than that it transitioned.
	"""
	import tempfile

	reset_scene()
	add_mesh("Cube")
	path = os.path.join(tempfile.mkdtemp(), "dirty2.blend")
	bpy.ops.wm.save_as_mainfile(filepath=path)

	capture_snapshot(path, "stamp")
	check(bpy.data.is_dirty, "file must report unsaved changes after stamping")


@test
def test_orphaned_history_is_reported():
	"""
	A .blend moved away from its sidecar keeps its stamps, so their presence
	proves history existed. Without this the user sees an empty snapshot list,
	indistinguishable from never having taken one.
	"""
	import tempfile

	from blendiff.extractor.identity import scene_has_identities
	from blendiff.storage.sidecar import SidecarManager
	import blendiff.ui.operators as operators

	reset_scene()
	add_mesh("Cube")
	original = os.path.join(tempfile.mkdtemp(), "orphan.blend")
	bpy.ops.wm.save_as_mainfile(filepath=original)
	capture_snapshot(original, "v1")

	# Save the stamped file into a new folder, leaving the sidecar behind.
	moved = os.path.join(tempfile.mkdtemp(), "orphan.blend")
	bpy.ops.wm.save_as_mainfile(filepath=moved)
	bpy.ops.wm.open_mainfile(filepath=moved)

	manager = SidecarManager(moved)
	check(scene_has_identities(bpy.context.scene), "moved file keeps its stamps")
	check(not os.path.exists(manager.sidecar_path), "sidecar was left behind")

	warning = operators._orphaned_history_warning(bpy.context, manager)
	check(warning is not None, "an orphaned sidecar must be reported")
	check(".blendiff" in warning, f"warning should name the file: {warning}")


@test
def test_no_warning_for_a_genuinely_new_file():
	"""An unstamped file has no history, so there is nothing to warn about."""
	import tempfile

	from blendiff.storage.sidecar import SidecarManager
	import blendiff.ui.operators as operators

	reset_scene()
	add_mesh("Cube")
	path = os.path.join(tempfile.mkdtemp(), "fresh.blend")
	bpy.ops.wm.save_as_mainfile(filepath=path)

	warning = operators._orphaned_history_warning(bpy.context, SidecarManager(path))
	check(warning is None, f"unexpected warning on a fresh file: {warning}")


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
def test_geometry_hashes_extracted():
	reset_scene()
	add_mesh("Cube")
	data = extract()["objects"]["Cube"]["mesh_data"]
	for key in ("vertex_hash", "topology_hash", "uv_hash"):
		check(key in data, f"{key} must be captured")
	check(data["vertex_hash"] != "empty", "a real mesh must produce a digest")


@test
def test_identical_mesh_produces_identical_hash():
	"""If this drifts, every diff fills with phantom geometry edits."""
	reset_scene()
	add_mesh("Cube")
	first = extract()["objects"]["Cube"]["mesh_data"]
	second = extract()["objects"]["Cube"]["mesh_data"]
	check_eq(first["vertex_hash"], second["vertex_hash"], "vertex digest is stable")
	check_eq(first["topology_hash"], second["topology_hash"], "topology digest is stable")


@test
def test_moved_vertex_is_detected():
	"""
	The gap this feature closes. Moving a vertex inside the existing bounds
	changes no count and no bound, so before geometry hashing BlenDiff reported
	this edit as no change at all.
	"""
	reset_scene()
	obj = add_mesh("Cube")
	before = extract_and_serialize()

	# Nudge one vertex, staying strictly inside the original bounding box so
	# that every previously-recorded number is unchanged.
	obj.data.vertices[0].co = (0.25, 0.25, 0.0)
	obj.data.update()
	after = extract_and_serialize()

	mesh_a = before["objects"]["Cube"]["mesh_data"]
	mesh_b = after["objects"]["Cube"]["mesh_data"]
	check_eq(mesh_a["vertex_count"], mesh_b["vertex_count"], "counts unchanged")
	check_eq(mesh_a["bbox_min"], mesh_b["bbox_min"], "bounds unchanged")

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check("mesh.vertex_positions" in paths,
	      f"a moved vertex must be reported, got {sorted(paths)}")


@test
def test_moved_vertex_leaves_topology_hash_alone():
	reset_scene()
	obj = add_mesh("Cube")
	before = extract()["objects"]["Cube"]["mesh_data"]
	obj.data.vertices[0].co = (0.3, 0.3, 0.0)
	obj.data.update()
	after = extract()["objects"]["Cube"]["mesh_data"]

	check(before["vertex_hash"] != after["vertex_hash"], "positions changed")
	check_eq(before["topology_hash"], after["topology_hash"],
	         "topology is untouched by a position edit")


@test
def test_topology_change_is_detected():
	reset_scene()
	obj = add_mesh("Cube")
	before = extract_and_serialize()

	# Subdivide, which rewrites topology.
	modifier = obj.modifiers.new("Subdiv", "SUBSURF")
	bpy.context.view_layer.objects.active = obj
	bpy.ops.object.modifier_apply(modifier=modifier.name)
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check("mesh.topology" in paths, f"topology change expected, got {sorted(paths)}")


@test
def test_uv_change_is_detected():
	reset_scene()
	obj = add_mesh("Cube")
	obj.data.uv_layers.new(name="UVMap")
	before = extract_and_serialize()

	uv_data = obj.data.uv_layers["UVMap"].data
	uv_data[0].uv = (0.75, 0.75)
	obj.data.update()
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check("mesh.uvs" in paths, f"UV change expected, got {sorted(paths)}")


@test
def test_geometry_hash_survives_a_save_load_round_trip():
	"""
	Digests are compared across sessions, so they must not depend on anything
	transient in the current one.
	"""
	import tempfile
	reset_scene()
	add_mesh("Cube")
	before = extract()["objects"]["Cube"]["mesh_data"]["vertex_hash"]

	path = os.path.join(tempfile.mkdtemp(), "roundtrip.blend")
	bpy.ops.wm.save_as_mainfile(filepath=path)
	bpy.ops.wm.open_mainfile(filepath=path)

	after = extract()["objects"]["Cube"]["mesh_data"]["vertex_hash"]
	check_eq(after, before, "digest must survive save and reload")


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


# Armatures
#
# Rigs were the largest blind spot: an ARMATURE object recorded only its own
# transform, so reparenting a bone, changing the rest pose, re-posing or
# rewiring an IK chain all reported nothing.

def add_rig(name="Rig", bones=(("Spine", (0, 0, 0), (0, 0, 1), None),
                               ("Head", (0, 0, 1), (0, 0, 2), "Spine"))):
	"""Build an armature object with the given bones."""
	arm = bpy.data.armatures.new(name)
	rig = bpy.data.objects.new(name, arm)
	bpy.context.scene.collection.objects.link(rig)
	bpy.context.view_layer.objects.active = rig

	bpy.ops.object.mode_set(mode="EDIT")
	for bone_name, head, tail, _parent in bones:
		bone = arm.edit_bones.new(bone_name)
		bone.head = head
		bone.tail = tail
	for bone_name, _h, _t, parent in bones:
		if parent:
			arm.edit_bones[bone_name].parent = arm.edit_bones[parent]
	bpy.ops.object.mode_set(mode="OBJECT")
	return rig


@test
def test_armature_data_extracted():
	reset_scene()
	add_rig()
	data = extract()["objects"]["Rig"]["armature_data"]
	check(data is not None, "armature data must be captured")
	check_eq(data["bone_count"], 2, "bone count")
	check_eq(sorted(data["bones"]), ["Head", "Spine"], "bone names")


@test
def test_bone_hierarchy_extracted():
	reset_scene()
	add_rig()
	bones = extract()["objects"]["Rig"]["armature_data"]["bones"]
	check_eq(bones["Head"]["parent"], "Spine", "bone parent")
	check(bones["Spine"]["parent"] is None, "root bone has no parent")


@test
def test_rest_positions_extracted():
	reset_scene()
	add_rig()
	spine = extract()["objects"]["Rig"]["armature_data"]["bones"]["Spine"]
	check_close(spine["tail_local"][2], 1.0, message="tail position")
	check_close(spine["length"], 1.0, message="bone length")


@test
def test_bone_roll_extracted_without_edit_mode():
	"""
	roll lives only on EditBone. Deriving it from the rest matrix means a roll
	change is detected without switching the user's object into edit mode.
	"""
	reset_scene()
	rig = add_rig()
	bpy.ops.object.mode_set(mode="EDIT")
	rig.data.edit_bones["Spine"].roll = math.radians(30)
	bpy.ops.object.mode_set(mode="OBJECT")

	roll = extract()["objects"]["Rig"]["armature_data"]["bones"]["Spine"]["roll"]
	check(roll is not None, "roll must be derivable outside edit mode")
	check_close(math.degrees(roll), 30.0, tol=1e-3, message="roll in degrees")


@test
def test_reparenting_a_bone_is_detected():
	reset_scene()
	rig = add_rig(bones=(("Spine", (0, 0, 0), (0, 0, 1), None),
	                     ("Chest", (0, 0, 1), (0, 0, 2), "Spine"),
	                     ("Head", (0, 0, 2), (0, 0, 3), "Chest")))
	before = extract_and_serialize()

	bpy.ops.object.mode_set(mode="EDIT")
	rig.data.edit_bones["Head"].parent = rig.data.edit_bones["Spine"]
	bpy.ops.object.mode_set(mode="OBJECT")
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check('armature.bones["Head"].parent' in paths,
	      f"reparenting must be reported, got {sorted(paths)}")


@test
def test_rest_pose_edit_is_detected():
	reset_scene()
	rig = add_rig()
	before = extract_and_serialize()

	bpy.ops.object.mode_set(mode="EDIT")
	rig.data.edit_bones["Head"].tail = (0.0, 0.5, 2.0)
	bpy.ops.object.mode_set(mode="OBJECT")
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check('armature.bones["Head"].tail_local' in paths,
	      f"rest pose edit must be reported, got {sorted(paths)}")


@test
def test_pose_change_is_detected():
	"""The animator's edit, distinct from the rigger's."""
	reset_scene()
	rig = add_rig()
	before = extract_and_serialize()

	rig.pose.bones["Head"].location = (0.5, 0.0, 0.0)
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check('pose.bones["Head"].location' in paths,
	      f"pose change must be reported, got {sorted(paths)}")


@test
def test_pose_change_does_not_touch_rest_data():
	"""Rest and pose stay distinguishable — different edits, different people."""
	reset_scene()
	rig = add_rig()
	before = extract_and_serialize()
	rig.pose.bones["Head"].location = (0.5, 0.0, 0.0)
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check(not any(p.startswith("armature.") for p in paths),
	      f"posing must not report rest changes, got {sorted(paths)}")


@test
def test_added_bone_is_detected():
	reset_scene()
	rig = add_rig()
	before = extract_and_serialize()

	bpy.ops.object.mode_set(mode="EDIT")
	bone = rig.data.edit_bones.new("Jaw")
	bone.head = (0, 0, 2)
	bone.tail = (0, 0.5, 2)
	bpy.ops.object.mode_set(mode="OBJECT")
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check('armature.bones["Jaw"]' in paths, f"new bone expected, got {sorted(paths)}")


@test
def test_bone_constraints_extracted():
	"""IK and Copy Rotation on pose bones are the heart of a rig."""
	reset_scene()
	rig = add_rig()
	con = rig.pose.bones["Head"].constraints.new("COPY_ROTATION")
	con.target = rig

	pose = extract()["objects"]["Rig"]["pose_bones"]
	constraints = pose["Head"]["constraints"]
	check(constraints, "bone constraint must be captured")
	check_eq(constraints[0]["type"], "COPY_ROTATION", "constraint type")


@test
def test_bone_constraint_change_is_detected():
	reset_scene()
	rig = add_rig()
	con = rig.pose.bones["Head"].constraints.new("COPY_ROTATION")
	con.target = rig
	before = extract_and_serialize()

	con.influence = 0.25
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check(any("constraints" in p for p in paths),
	      f"bone constraint change expected, got {sorted(paths)}")


@test
def test_unchanged_rig_produces_no_diff():
	"""Guards against phantom rig churn on every snapshot."""
	reset_scene()
	rig = add_rig()
	rig.pose.bones["Head"].location = (0.25, 0.0, 0.0)

	first = extract_and_serialize()
	second = extract_and_serialize()
	diff = DiffEngine().compare(first, second)
	check(not diff.has_changes, f"identical rigs must not differ: {diff.summary()}")


@test
def test_pose_position_toggle_is_detected():
	reset_scene()
	rig = add_rig()
	before = extract_and_serialize()
	rig.data.pose_position = "REST"
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	paths = {c.property_path for d in diff.modified_objects for c in d.changes}
	check("armature.pose_position" in paths,
	      f"pose position toggle expected, got {sorted(paths)}")


# Rest-bone merging
#
# Rest bones exist only on EditBone, so applying them means entering edit mode.
# Extraction deliberately avoids that; applying is the opposite situation — the
# user asked for it, the scene is already being changed, and it runs from an
# operator where mode switching is legitimate.

def _apply_changes(obj_name, changes):
	"""Run the Applier over one object's changes and return the result."""
	from blendiff.data_model.conflict import MergeProposal, NonConflictingChange, ThreeWayDiff
	from blendiff.merge_engine.applier import Applier

	proposal = MergeProposal(object_name=obj_name)
	for path, value in changes:
		proposal.non_conflicting_from_a.append(NonConflictingChange(
			property_path=path, base_value=None, new_value=value, source="a",
		))
	tw = ThreeWayDiff(base_label="base", label_a="A", label_b="B",
	                  proposals=[proposal])
	return Applier().apply_all(tw, bpy.context)


@test
def test_rest_bone_reparenting_applies():
	reset_scene()
	rig = add_rig(bones=(("Spine", (0, 0, 0), (0, 0, 1), None),
	                     ("Chest", (0, 0, 1), (0, 0, 2), "Spine"),
	                     ("Head", (0, 0, 2), (0, 0, 3), "Chest")))
	bpy.ops.object.mode_set(mode="OBJECT")

	result = _apply_changes("Rig", [('armature.bones["Head"].parent', "Spine")])
	check(not result.failed, f"reparent should not fail: {result.errors}")
	check_eq(rig.data.bones["Head"].parent.name, "Spine", "bone reparented")


@test
def test_rest_position_and_roll_apply():
	reset_scene()
	rig = add_rig()
	bpy.ops.object.mode_set(mode="OBJECT")

	result = _apply_changes("Rig", [
		('armature.bones["Head"].tail_local', [0.0, 0.5, 2.0]),
		('armature.bones["Head"].roll', math.radians(30)),
	])
	check(not result.failed, f"rest edit should not fail: {result.errors}")
	tail = rig.data.bones["Head"].tail_local
	check_close(tail[1], 0.5, message="tail moved")

	from blendiff.extractor.armature_extractor import extract_armature_data
	roll = extract_armature_data(rig)["bones"]["Head"]["roll"]
	check_close(math.degrees(roll), 30.0, tol=1e-3, message="roll applied")


@test
def test_rest_bone_merge_restores_mode_and_selection():
	"""
	The user is mid-task. Leaving them in edit mode on an object they did not
	select would be a genuinely disruptive thing for a merge to do.
	"""
	reset_scene()
	rig = add_rig()
	cube = add_mesh("Cube")
	bpy.ops.object.mode_set(mode="OBJECT")

	bpy.context.view_layer.objects.active = cube
	cube.select_set(True)
	rig.select_set(False)

	_apply_changes("Rig", [('armature.bones["Head"].roll', 0.2)])

	check_eq(bpy.context.view_layer.objects.active.name, "Cube", "active restored")
	check_eq(bpy.context.object.mode, "OBJECT", "mode restored")
	check(cube.select_get(), "the user's selection is intact")
	check(not rig.select_get(), "the rig was not selected before the merge")


@test
def test_rest_bone_changes_round_trip_through_a_diff():
	"""End to end: diff a rig edit, then apply it and get the same rig back."""
	reset_scene()
	rig = add_rig()
	bpy.ops.object.mode_set(mode="OBJECT")
	before = extract_and_serialize()

	bpy.ops.object.mode_set(mode="EDIT")
	rig.data.edit_bones["Head"].parent = None
	rig.data.edit_bones["Head"].tail = (0.0, 0.75, 3.0)
	bpy.ops.object.mode_set(mode="OBJECT")
	after = extract_and_serialize()

	diff = DiffEngine().compare(before, after)
	changes = [
		(c.property_path, c.new_value)
		for d in diff.modified_objects for c in d.changes
		if c.property_path.startswith("armature.bones")
	]
	check(changes, "the rig edit must be detected")

	# Put the rig back to "before", then replay the diff onto it.
	bpy.ops.object.mode_set(mode="EDIT")
	rig.data.edit_bones["Head"].parent = rig.data.edit_bones["Spine"]
	rig.data.edit_bones["Head"].tail = (0, 0, 2)
	bpy.ops.object.mode_set(mode="OBJECT")

	result = _apply_changes("Rig", changes)
	check(not result.failed, f"replay should not fail: {result.errors}")

	replayed = extract_and_serialize()
	final = DiffEngine().compare(after, replayed)
	rest = [c.property_path for d in final.modified_objects for c in d.changes
	        if c.property_path.startswith("armature.bones")]
	check(not rest, f"replaying the diff should reproduce the rig, left: {rest}")


@test
def test_bone_flags_apply_without_entering_edit_mode():
	reset_scene()
	rig = add_rig()
	bpy.ops.object.mode_set(mode="OBJECT")

	result = _apply_changes("Rig", [
		('armature.bones["Head"].use_deform', False),
		("armature.pose_position", "REST"),
	])
	check(not result.failed, f"flags should not fail: {result.errors}")
	check_eq(rig.data.bones["Head"].use_deform, False, "deform flag applied")
	check_eq(rig.data.pose_position, "REST", "armature setting applied")


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
