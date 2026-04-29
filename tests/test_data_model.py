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
			"added": 0, "removed": 0, "modified": 0, "collection_changes": 0,
			"render_changes": 0, "world_changes": 0, "parent_changes": 0,
			"constraint_changes": 0, "custom_prop_changes": 0,
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
