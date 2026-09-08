"""
tests/test_schema.py
~~~~~~~~~~~~~~~~~~~~~
Snapshot schema versioning, domain capture, and migration.

The behaviour these tests protect: diffing an old snapshot against a new one
must never invent changes for a domain the old snapshot could not capture.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.data_model import schema
from blendiff.storage.migrate import migrate_scene, needs_migration


class TestSchemaVersion:
	def test_missing_version_is_v1(self):
		assert schema.schema_version_of({}) == 1

	def test_explicit_version_is_read(self):
		assert schema.schema_version_of({"schema_version": 2}) == 2

	def test_malformed_version_falls_back_to_v1(self):
		assert schema.schema_version_of({"schema_version": "bogus"}) == 1


class TestCapturedDomains:
	def test_declared_domains_are_trusted(self):
		scene = {"captured_domains": ["objects", "fcurves"]}
		assert schema.captured_domains(scene) == {"objects", "fcurves"}

	def test_legacy_scene_infers_scene_domains_from_keys(self):
		scene = {"objects": {}, "collections": {}, "render": {}}
		found = schema.captured_domains(scene)
		assert schema.DOMAIN_RENDER in found
		assert schema.DOMAIN_WORLD not in found

	def test_legacy_scene_infers_object_domains(self):
		scene = {"objects": {"Cube": {"parent": None, "custom_props": {}}}}
		found = schema.captured_domains(scene)
		assert schema.DOMAIN_PARENT in found
		assert schema.DOMAIN_CUSTOM_PROPS in found
		assert schema.DOMAIN_FCURVES not in found

	def test_domain_counts_as_captured_if_any_object_has_it(self):
		scene = {"objects": {"A": {}, "B": {"fcurves": []}}}
		assert schema.DOMAIN_FCURVES in schema.captured_domains(scene)

	def test_non_dict_returns_empty(self):
		assert schema.captured_domains(None) == set()


class TestComparableAndSkipped:
	def test_common_domains_are_comparable(self):
		a = {"captured_domains": ["objects", "parent"]}
		b = {"captured_domains": ["objects", "fcurves"]}
		assert schema.comparable_domains(a, b) == {"objects"}

	def test_one_sided_domains_are_skipped(self):
		a = {"captured_domains": ["objects", "parent"]}
		b = {"captured_domains": ["objects", "fcurves"]}
		assert schema.skipped_domains(a, b) == {"parent", "fcurves"}

	def test_identical_snapshots_skip_nothing(self):
		a = {"captured_domains": ["objects", "parent"]}
		assert schema.skipped_domains(a, dict(a)) == set()

	def test_skip_descriptions_name_the_missing_side(self):
		a = {"captured_domains": ["objects"]}
		b = {"captured_domains": ["objects", "fcurves"]}
		notes = schema.describe_skipped(a, b)
		assert len(notes) == 1
		assert "F-curves" in notes[0]
		assert "snapshot A" in notes[0]


class TestTransformSpace:
	def test_legacy_default_is_world(self):
		assert schema.transform_space({}) == schema.TRANSFORM_SPACE_WORLD

	def test_declared_space_is_read(self):
		scene = {"transform_space": "local"}
		assert schema.transform_space(scene) == schema.TRANSFORM_SPACE_LOCAL

	def test_matching_spaces_are_comparable(self):
		a = {"transform_space": "local"}
		assert schema.transforms_comparable(a, dict(a))

	def test_mixed_spaces_are_not_comparable(self):
		a = {"transform_space": "world"}
		b = {"transform_space": "local"}
		assert not schema.transforms_comparable(a, b)


class TestStamp:
	def test_stamp_sets_version_and_domains(self):
		scene = schema.stamp({}, ["objects", "parent"])
		assert scene["schema_version"] == schema.SCHEMA_VERSION
		assert scene["captured_domains"] == ["objects", "parent"]

	def test_stamp_defaults_to_local_transforms(self):
		scene = schema.stamp({}, [])
		assert scene["transform_space"] == schema.TRANSFORM_SPACE_LOCAL

	def test_stamp_does_not_override_declared_space(self):
		scene = schema.stamp({"transform_space": "world"}, [])
		assert scene["transform_space"] == "world"


class TestMigration:
	def test_legacy_scene_needs_migration(self):
		assert needs_migration({"objects": {}})

	def test_current_scene_does_not(self):
		assert not needs_migration({"schema_version": schema.SCHEMA_VERSION})

	def test_migration_records_inferred_domains(self):
		scene = migrate_scene({"objects": {"Cube": {"parent": None}}})
		assert scene["schema_version"] == 2
		assert schema.DOMAIN_PARENT in scene["captured_domains"]
		assert schema.DOMAIN_FCURVES not in scene["captured_domains"]

	def test_migration_marks_legacy_transforms_as_world_space(self):
		"""
		v1 decomposed matrix_world. Recording that is what stops a v1/v2
		comparison from reporting bogus transform changes on parented objects.
		"""
		scene = migrate_scene({"objects": {}})
		assert scene["transform_space"] == schema.TRANSFORM_SPACE_WORLD

	def test_migration_does_not_invent_object_ids(self):
		"""
		Inventing ids would pair unrelated objects. v1 objects legitimately
		have none and must fall back to name matching.
		"""
		scene = migrate_scene({"objects": {"Cube": {}}})
		assert "blendiff_id" not in scene["objects"]["Cube"]

	def test_migration_copies_by_default(self):
		original = {"objects": {}}
		migrated = migrate_scene(original)
		assert "schema_version" not in original
		assert migrated is not original

	def test_migration_in_place_mutates(self):
		original = {"objects": {}}
		migrated = migrate_scene(original, in_place=True)
		assert migrated is original
		assert original["schema_version"] == 2

	def test_migration_is_idempotent(self):
		once = migrate_scene({"objects": {"Cube": {"parent": None}}})
		twice = migrate_scene(once)
		assert once == twice

	def test_newer_schema_is_left_untouched(self):
		"""A downgrade must not mangle data written by a future release."""
		future = {"schema_version": 999, "objects": {}}
		assert migrate_scene(future) == future

	def test_existing_content_survives_migration(self):
		scene = {"objects": {"Cube": {"type": "MESH"}}, "scene_name": "Scene"}
		migrated = migrate_scene(scene)
		assert migrated["objects"]["Cube"]["type"] == "MESH"
		assert migrated["scene_name"] == "Scene"
