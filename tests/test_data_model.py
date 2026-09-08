import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.data_model import (
	ChangeKind,
	PropertyChange,
	ObjectDiff,
	CollectionDiff,
	SceneDiff,
)


class TestSceneDiff:

	def _make_diff(self):
		return SceneDiff(scene_name_a="A", scene_name_b="B")

	def test_empty_diff_has_no_changes(self):
		diff = self._make_diff()
		assert not diff.has_changes
		assert diff.summary() == {
			"added": 0, "removed": 0, "modified": 0, "renamed": 0,
			"collection_changes": 0,
			"render_changes": 0, "world_changes": 0, "parent_changes": 0,
			"constraint_changes": 0, "custom_prop_changes": 0,
			"fcurve_changes" : 0, "driver_changes": 0, "nla_changes": 0,
			"scene_custom_prop_changes": 0, "skipped_domains": 0,
		}

	def test_added_objects_property(self):
		diff = self._make_diff()
		diff.object_diffs = [
			ObjectDiff(name="Cube", kind=ChangeKind.ADDED),
			ObjectDiff(name="Sphere", kind=ChangeKind.REMOVED),
		]
		assert len(diff.added_objects)   == 1
		assert len(diff.removed_objects) == 1
		assert len(diff.modified_objects) == 0

	def test_is_structural_true_for_add_remove(self):
		added   = ObjectDiff(name="X", kind=ChangeKind.ADDED)
		removed = ObjectDiff(name="Y", kind=ChangeKind.REMOVED)
		assert added.is_structural
		assert removed.is_structural

	def test_is_structural_false_for_modified(self):
		modified = ObjectDiff(name="Z", kind=ChangeKind.MODIFIED)
		assert not modified.is_structural

	def test_change_kind_values(self):
		assert ChangeKind.ADDED.value    == "added"
		assert ChangeKind.REMOVED.value  == "removed"
		assert ChangeKind.MODIFIED.value == "modified"

	def test_has_changes_with_object_diffs(self):
		diff = self._make_diff()
		diff.object_diffs = [ObjectDiff(name="X", kind=ChangeKind.ADDED)]
		assert diff.has_changes

	def test_has_changes_with_collection_diffs(self):
		diff = self._make_diff()
		diff.collection_diffs = [CollectionDiff(path="Props", kind=ChangeKind.ADDED)]
		assert diff.has_changes


class TestObjectDiffRename:
	"""
	A rename must stay a single modified object. Matching on name alone turned
	it into a delete plus an unrelated add, discarding every other change.
	"""

	def test_no_previous_name_is_not_a_rename(self):
		diff = ObjectDiff(name="Cube", kind=ChangeKind.MODIFIED)
		assert not diff.was_renamed
		assert diff.display_name == "Cube"

	def test_same_previous_name_is_not_a_rename(self):
		diff = ObjectDiff(name="Cube", kind=ChangeKind.MODIFIED, previous_name="Cube")
		assert not diff.was_renamed

	def test_different_previous_name_is_a_rename(self):
		diff = ObjectDiff(
			name="Body_LOW", kind=ChangeKind.MODIFIED, previous_name="Cube"
		)
		assert diff.was_renamed
		assert diff.display_name == "Cube \u2192 Body_LOW"

	def test_renamed_objects_collected_on_scene_diff(self):
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		diff.object_diffs = [
			ObjectDiff(name="Body_LOW", kind=ChangeKind.MODIFIED, previous_name="Cube"),
			ObjectDiff(name="Lamp", kind=ChangeKind.MODIFIED),
		]
		assert [d.name for d in diff.renamed_objects] == ["Body_LOW"]
		assert diff.summary()["renamed"] == 1


class TestSkippedDomains:
	def test_no_skipped_domains_by_default(self):
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		assert not diff.has_skipped_domains

	def test_skipped_domains_reported(self):
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		diff.skipped_domains = ["fcurves"]
		assert diff.has_skipped_domains
		assert diff.summary()["skipped_domains"] == 1

	def test_skipped_domains_are_not_changes(self):
		"""A skipped domain is missing information, not a detected change."""
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		diff.skipped_domains = ["fcurves", "drivers"]
		assert not diff.has_changes


class TestPackageExports:
	"""
	__all__ must name only things the package actually imports.

	RenderDiff was listed without being imported, so `from blendiff.data_model
	import RenderDiff` raised ImportError and a star-import raised
	AttributeError — a public API that had never worked.
	"""

	def test_every_exported_name_resolves(self):
		import blendiff.data_model as dm

		missing = [name for name in dm.__all__ if not hasattr(dm, name)]
		assert missing == [], f"declared in __all__ but not importable: {missing}"

	def test_star_import_succeeds(self):
		namespace = {}
		exec("from blendiff.data_model import *", namespace)
		assert "RenderDiff" in namespace

	def test_render_diff_is_importable_by_name(self):
		from blendiff.data_model import RenderDiff
		assert RenderDiff().changes == []

	def test_world_diff_is_importable_by_name(self):
		from blendiff.data_model import WorldDiff
		assert WorldDiff().changes == []
