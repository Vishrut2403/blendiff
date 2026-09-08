"""
tests/test_diff_engine_identity.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
End-to-end DiffEngine behaviour for identity, schema gating and transforms.

These cover the three bugs that made cross-version and post-rename diffs
untrustworthy: history lost on rename, phantom changes from domains an older
snapshot never captured, and transform noise from mixed coordinate spaces.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.data_model import schema
from blendiff.diff_engine.diff_engine import DiffEngine


def _obj(name="Cube", obj_id=None, location=None, **extra):
	data = {
		"name": name,
		"type": "MESH",
		"collection_path": "Scene Collection",
		"transform": {
			"location": location or [0.0, 0.0, 0.0],
			"rotation_euler": [0.0, 0.0, 0.0],
			"scale": [1.0, 1.0, 1.0],
		},
		"material_slots": [],
		"visible": True,
	}
	if obj_id is not None:
		data["blendiff_id"] = obj_id
	data.update(extra)
	return data


def _scene(objects, domains=None, transform_space="local", **extra):
	scene = {
		"blender_version": "4.1.0",
		"scene_name": "Scene",
		"objects": objects,
		"collections": {},
		"transform_space": transform_space,
	}
	if domains is not None:
		scene["schema_version"] = schema.SCHEMA_VERSION
		scene["captured_domains"] = list(domains)
	scene.update(extra)
	return scene


def _paths(diff):
	return {c.property_path for d in diff.modified_objects for c in d.changes}


class TestRenameSurvivesDiff:
	def setup_method(self):
		self.engine = DiffEngine()

	def test_rename_is_one_modified_object(self):
		a = _scene({"Cube": _obj("Cube", "id-1")})
		b = _scene({"Body_LOW": _obj("Body_LOW", "id-1")})
		diff = self.engine.compare(a, b)

		assert len(diff.modified_objects) == 1
		assert diff.added_objects == []
		assert diff.removed_objects == []

	def test_rename_is_reported_as_a_change(self):
		a = _scene({"Cube": _obj("Cube", "id-1")})
		b = _scene({"Body_LOW": _obj("Body_LOW", "id-1")})
		diff = self.engine.compare(a, b)

		change = diff.modified_objects[0].changes[0]
		assert change.property_path == "name"
		assert change.old_value == "Cube"
		assert change.new_value == "Body_LOW"

	def test_rename_preserves_other_changes(self):
		"""
		The whole point: a rename used to discard every other edit on the
		object by turning it into an unrelated add/remove pair.
		"""
		a = _scene({"Cube": _obj("Cube", "id-1", location=[0.0, 0.0, 0.0])})
		b = _scene({"Body": _obj("Body", "id-1", location=[5.0, 0.0, 0.0])})
		diff = self.engine.compare(a, b)

		assert "transform.location" in _paths(diff)

	def test_renamed_objects_are_listed(self):
		a = _scene({"Cube": _obj("Cube", "id-1")})
		b = _scene({"Body": _obj("Body", "id-1")})
		diff = self.engine.compare(a, b)

		assert len(diff.renamed_objects) == 1
		assert diff.renamed_objects[0].previous_name == "Cube"
		assert diff.summary()["renamed"] == 1

	def test_diff_reports_current_name(self):
		a = _scene({"Cube": _obj("Cube", "id-1")})
		b = _scene({"Body": _obj("Body", "id-1")})
		diff = self.engine.compare(a, b)
		assert diff.modified_objects[0].name == "Body"

	def test_rename_without_ids_is_still_add_remove(self):
		a = _scene({"Cube": _obj("Cube")})
		b = _scene({"Body": _obj("Body")})
		diff = self.engine.compare(a, b)

		assert [d.name for d in diff.added_objects] == ["Body"]
		assert [d.name for d in diff.removed_objects] == ["Cube"]

	def test_unchanged_renamed_object_still_reports_the_rename(self):
		a = _scene({"Cube": _obj("Cube", "id-1")})
		b = _scene({"Body": _obj("Body", "id-1")})
		assert self.engine.compare(a, b).has_changes

	def test_per_domain_diffs_follow_the_rename(self):
		a = _scene({"Cube": _obj("Cube", "id-1", parent={"parent_name": "Rig"})})
		b = _scene({"Body": _obj("Body", "id-1", parent={"parent_name": "Rig2"})})
		diff = self.engine.compare(a, b)

		assert len(diff.parent_diffs) == 1
		assert diff.parent_diffs[0].object_name == "Body"


class TestDomainGating:
	def setup_method(self):
		self.engine = DiffEngine()

	def test_domain_captured_by_one_side_is_skipped(self):
		"""
		A pre-0.5 snapshot has no F-curve data. Every curve in the newer
		snapshot must not be reported as newly added.
		"""
		a = _scene({"Cube": _obj("Cube")}, domains=["objects"])
		b = _scene(
			{"Cube": _obj("Cube", fcurves=[{"data_path": "location", "array_index": 0,
			                                "keyframe_count": 3, "frame_start": 1,
			                                "frame_end": 10, "interpolation": "BEZIER",
			                                "extrapolation": "CONSTANT"}])},
			domains=["objects", "fcurves"],
		)
		diff = self.engine.compare(a, b)

		assert diff.fcurve_diffs == []
		assert schema.DOMAIN_FCURVES in diff.skipped_domains

	def test_skipped_domain_is_explained(self):
		a = _scene({"Cube": _obj("Cube")}, domains=["objects"])
		b = _scene({"Cube": _obj("Cube")}, domains=["objects", "fcurves"])
		diff = self.engine.compare(a, b)

		assert any("F-curves" in note for note in diff.skip_notes)

	def test_shared_domain_is_still_diffed(self):
		a = _scene(
			{"Cube": _obj("Cube", parent={"parent_name": None})},
			domains=["objects", "parent"],
		)
		b = _scene(
			{"Cube": _obj("Cube", parent={"parent_name": "Rig"})},
			domains=["objects", "parent"],
		)
		diff = self.engine.compare(a, b)

		assert len(diff.parent_diffs) == 1
		assert diff.skipped_domains == []

	def test_render_domain_gated(self):
		a = _scene({}, domains=["objects"])
		b = _scene({}, domains=["objects", "render"], render={"engine": "CYCLES"})
		diff = self.engine.compare(a, b)

		assert not diff.render_diff.has_changes
		assert schema.DOMAIN_RENDER in diff.skipped_domains

	def test_legacy_snapshots_diff_everything_they_share(self):
		"""Two pre-versioning snapshots keep their original behaviour."""
		a = {"scene_name": "S", "objects": {"Cube": _obj("Cube")}, "collections": {}}
		b = {"scene_name": "S", "objects": {"Cube": _obj("Cube", visible=False)},
		     "collections": {}}
		diff = DiffEngine().compare(a, b)

		assert "visible" in _paths(diff)
		assert diff.skipped_domains == []


class TestTransformSpaceGuard:
	def setup_method(self):
		self.engine = DiffEngine()

	def test_mixed_spaces_skip_transform_comparison(self):
		a = _scene({"Cube": _obj("Cube", location=[0.0, 0.0, 0.0])},
		           transform_space="world")
		b = _scene({"Cube": _obj("Cube", location=[5.0, 0.0, 0.0])},
		           transform_space="local")
		diff = self.engine.compare(a, b)

		assert "transform.location" not in _paths(diff)
		assert "transform" in diff.skipped_domains

	def test_mixed_spaces_are_explained(self):
		a = _scene({"Cube": _obj("Cube")}, transform_space="world")
		b = _scene({"Cube": _obj("Cube")}, transform_space="local")
		diff = self.engine.compare(a, b)

		assert any("transform space" in n.lower() for n in diff.skip_notes)

	def test_same_space_compares_transforms(self):
		a = _scene({"Cube": _obj("Cube", location=[0.0, 0.0, 0.0])})
		b = _scene({"Cube": _obj("Cube", location=[5.0, 0.0, 0.0])})
		assert "transform.location" in _paths(self.engine.compare(a, b))

	def test_rotation_mode_change_is_detected(self):
		a = _scene({"Cube": _obj("Cube")})
		b = _scene({"Cube": _obj("Cube")})
		a["objects"]["Cube"]["transform"]["rotation_mode"] = "XYZ"
		b["objects"]["Cube"]["transform"]["rotation_mode"] = "QUATERNION"
		assert "transform.rotation_mode" in _paths(self.engine.compare(a, b))

	def test_missing_rotation_mode_is_not_a_change(self):
		"""Legacy snapshots have no rotation_mode; absent means unknown."""
		a = _scene({"Cube": _obj("Cube")})
		b = _scene({"Cube": _obj("Cube")})
		b["objects"]["Cube"]["transform"]["rotation_mode"] = "XYZ"
		assert "transform.rotation_mode" not in _paths(self.engine.compare(a, b))


class TestOptionalFields:
	def setup_method(self):
		self.engine = DiffEngine()

	def test_hide_render_change_detected(self):
		a = _scene({"Cube": _obj("Cube", hide_render=False)})
		b = _scene({"Cube": _obj("Cube", hide_render=True)})
		assert "hide_render" in _paths(self.engine.compare(a, b))

	def test_hide_render_absent_on_one_side_is_not_a_change(self):
		a = _scene({"Cube": _obj("Cube")})
		b = _scene({"Cube": _obj("Cube", hide_render=False)})
		assert "hide_render" not in _paths(self.engine.compare(a, b))

	def test_collection_membership_change_detected(self):
		a = _scene({"Cube": _obj("Cube", collection_paths=["Scene Collection"])})
		b = _scene({"Cube": _obj("Cube",
		                         collection_paths=["Scene Collection", "Scene Collection/Props"])})
		assert "collection_paths" in _paths(self.engine.compare(a, b))

	def test_collection_membership_order_is_ignored(self):
		a = _scene({"Cube": _obj("Cube", collection_paths=["A", "B"])})
		b = _scene({"Cube": _obj("Cube", collection_paths=["B", "A"])})
		assert "collection_paths" not in _paths(self.engine.compare(a, b))
