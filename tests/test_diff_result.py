"""
tests/test_diff_result.py
~~~~~~~~~~~~~~~~~~~~~~~~~~
The shared SceneDiff → dict conversion.

This exists because the Blender operator and the CLI each built this dict by
hand and had drifted: the CLI's version carried only objects and collections,
so `blendiff compare --output report.html` produced reports that silently
omitted eight diffed domains.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.data_model.diff import (
	ChangeKind,
	ObjectDiff,
	PropertyChange,
	RenderDiff,
	SceneDiff,
)
from blendiff.data_model.parent_diff import ParentDiff
from blendiff.export.diff_result import diff_to_dict, summary_line


def _change(path="visible", old=True, new=False):
	return PropertyChange(property_path=path, old_value=old, new_value=new)


class TestSummaryLine:
	def test_empty_summary(self):
		assert summary_line({}) == "No changes detected"

	def test_zero_counts_are_omitted(self):
		assert summary_line({"added": 0, "removed": 0}) == "No changes detected"

	def test_non_zero_counts_are_named(self):
		line = summary_line({"added": 2, "modified": 1})
		assert "Added: 2" in line and "Modified: 1" in line

	def test_every_domain_can_appear(self):
		"""
		The CLI's hand-written summary named only four domains, so a
		render-only change reported as "no changes" on the summary line.
		"""
		line = summary_line({
			"render_changes": 1, "world_changes": 1, "parent_changes": 1,
			"constraint_changes": 1, "custom_prop_changes": 1,
			"fcurve_changes": 1, "driver_changes": 1, "nla_changes": 1,
			"scene_custom_prop_changes": 1, "renamed": 1,
		})
		for label in ("Render", "World", "Parents", "Constraints", "Custom Props",
		              "F-Curves", "Drivers", "NLA", "Scene Props", "Renamed"):
			assert label in line


class TestDiffToDict:
	def _diff(self):
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		diff.object_diffs = [
			ObjectDiff(name="New", kind=ChangeKind.ADDED),
			ObjectDiff(name="Gone", kind=ChangeKind.REMOVED),
			ObjectDiff(
				name="Body", kind=ChangeKind.MODIFIED,
				changes=[_change()], previous_name="Cube",
			),
		]
		diff.render_diff = RenderDiff(changes=[_change("engine", "EEVEE", "CYCLES")])
		diff.parent_diffs = [ParentDiff(object_name="Body", changes=[_change("parent.parent_name", None, "Rig")])]
		diff.skipped_domains = ["fcurves"]
		diff.skip_notes = ["F-curves: not captured in snapshot A"]
		return diff

	def test_structural_lists(self):
		d = diff_to_dict(self._diff())
		assert d["added_objects"] == ["New"]
		assert d["removed_objects"] == ["Gone"]

	def test_renamed_objects_reported(self):
		d = diff_to_dict(self._diff())
		assert d["renamed_objects"] == [{"previous_name": "Cube", "name": "Body"}]

	def test_modified_object_carries_display_name(self):
		d = diff_to_dict(self._diff())
		modified = d["modified_objects"][0]
		assert modified["display_name"] == "Cube → Body"
		assert modified["previous_name"] == "Cube"

	def test_render_changes_included(self):
		d = diff_to_dict(self._diff())
		assert d["render_changes"][0]["property_path"] == "engine"

	def test_per_object_domains_included(self):
		d = diff_to_dict(self._diff())
		assert d["parent_diffs"][0]["object_name"] == "Body"

	def test_every_domain_key_is_present(self):
		"""Consumers use .get, but a missing key would silently drop a domain."""
		d = diff_to_dict(SceneDiff(scene_name_a="A", scene_name_b="B"))
		for key in ("added_objects", "removed_objects", "renamed_objects",
		            "modified_objects", "collection_diffs", "render_changes",
		            "world_changes", "scene_custom_props", "parent_diffs",
		            "constraint_diffs", "custom_prop_diffs", "fcurve_diffs",
		            "driver_diffs", "nla_diffs", "skipped_domains", "skip_notes"):
			assert key in d, f"missing {key}"

	def test_skipped_domains_carried_through(self):
		d = diff_to_dict(self._diff())
		assert d["skipped_domains"] == ["fcurves"]
		assert d["skip_notes"]

	def test_summary_counts_included(self):
		d = diff_to_dict(self._diff())
		assert d["summary_counts"]["added"] == 1
		assert d["summary_counts"]["renamed"] == 1

	def test_has_changes_flag(self):
		assert diff_to_dict(self._diff())["has_changes"] is True
		empty = SceneDiff(scene_name_a="A", scene_name_b="B")
		assert diff_to_dict(empty)["has_changes"] is False

	def test_summary_mentions_render(self):
		assert "Render: 1" in diff_to_dict(self._diff())["summary"]
