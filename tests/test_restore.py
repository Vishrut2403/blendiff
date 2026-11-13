"""
tests/test_restore.py
~~~~~~~~~~~~~~~~~~~~~~
Putting a scene back the way a snapshot recorded it.

A restore is the ordinary diff pointed backwards: compare the current scene
against the snapshot, and every change then describes what the scene would
have to become. Those go to the same applier a merge uses, so a restore
inherits its limits rather than inventing a second way to write to a scene.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.data_model.diff import ChangeKind, ObjectDiff, PropertyChange, SceneDiff
from blendiff.merge_engine.restore import build_restore, unrestorable_objects


def _scene_diff(*object_diffs):
	return SceneDiff(
		scene_name_a="Scene", scene_name_b="Scene",
		object_diffs=list(object_diffs),
	)


def _modified(name, changes, previous_name=None):
	return ObjectDiff(
		name=name,
		kind=ChangeKind.MODIFIED,
		changes=[PropertyChange(p, old, new) for p, old, new in changes],
		previous_name=previous_name,
	)


class TestBuildRestore:

	def test_every_change_becomes_something_to_apply(self):
		diff = _scene_diff(_modified("Cube", [
			("transform.location", [9.0, 0.0, 0.0], [1.0, 0.0, 0.0]),
			("hide_render", True, False),
		]))

		three_way = build_restore(diff, "good")

		assert len(three_way.proposals) == 1
		proposal = three_way.proposals[0]
		assert [c.property_path for c in proposal.non_conflicting_from_a] == [
			"transform.location", "hide_render",
		]

	def test_the_snapshot_value_is_the_one_applied(self):
		diff = _scene_diff(_modified("Cube", [
			("transform.location", [9.0, 0.0, 0.0], [1.0, 0.0, 0.0]),
		]))

		change = build_restore(diff).proposals[0].non_conflicting_from_a[0]

		# new_value is what the scene becomes, so it must be the snapshot's.
		assert change.new_value == [1.0, 0.0, 0.0]
		assert change.base_value == [9.0, 0.0, 0.0]

	def test_nothing_is_left_for_the_user_to_resolve(self):
		"""A restore has one source, so it can never be half-decided."""
		diff = _scene_diff(_modified("Cube", [("hide_render", True, False)]))

		three_way = build_restore(diff)

		assert three_way.proposals[0].conflicts == []
		assert three_way.all_resolved

	def test_a_renamed_object_carries_its_current_name(self):
		# The scene still uses the old name, which is how the applier finds it.
		diff = _scene_diff(_modified(
			"zapBook", [("name", "chair_RENAMED", "zapBook")],
			previous_name="chair_RENAMED",
		))

		proposal = build_restore(diff).proposals[0]

		assert proposal.object_name == "zapBook"
		assert proposal.previous_name == "chair_RENAMED"

	def test_objects_with_no_changes_produce_no_proposal(self):
		assert build_restore(_scene_diff(_modified("Cube", []))).proposals == []

	def test_added_and_removed_objects_are_not_acted_on(self):
		diff = _scene_diff(
			ObjectDiff(name="Gone", kind=ChangeKind.ADDED),
			ObjectDiff(name="Made_Later", kind=ChangeKind.REMOVED),
		)

		assert build_restore(diff).proposals == []


class TestUnrestorableObjects:
	"""
	What a restore cannot account for, and why, stated rather than hidden.

	The diff runs current-scene-first, so "added" means present in the
	snapshot and absent now, and "removed" means the opposite.
	"""

	def test_objects_deleted_since_cannot_be_rebuilt(self):
		diff = _scene_diff(ObjectDiff(name="Gone", kind=ChangeKind.ADDED))

		assert unrestorable_objects(diff)["missing"] == ["Gone"]

	def test_objects_made_since_are_left_alone(self):
		diff = _scene_diff(ObjectDiff(name="Made_Later", kind=ChangeKind.REMOVED))

		stranded = unrestorable_objects(diff)
		assert stranded["extra"] == ["Made_Later"]
		assert stranded["missing"] == []

	def test_modified_objects_are_not_reported_as_stranded(self):
		diff = _scene_diff(_modified("Cube", [("hide_render", True, False)]))

		assert unrestorable_objects(diff) == {"missing": [], "extra": []}


class TestFactsImpliedByRestoredGeometry:
	"""
	A restore that did exactly what was asked must not report failures.

	Restoring vertex positions makes the digest of those positions, and the
	bounding box they describe, true again by construction. Leaving them in
	the proposal meant a successful restore reported "applied 1, 2 not
	applicable", which reads as a partial failure and sends the user looking
	for what broke.
	"""

	def test_derived_facts_are_dropped_when_geometry_is_restored(self):
		diff = _scene_diff(_modified("Sphere", [
			("mesh.stored_geometry", "q1:old", "q1:new"),
			("mesh.vertex_positions", "2:aaa", "2:bbb"),
			("mesh.bbox_min", [0, 0, 0], [1, 1, 1]),
			("mesh.bbox_max", [1, 1, 1], [2, 2, 2]),
		]))

		paths = [
			c.property_path
			for c in build_restore(diff).proposals[0].non_conflicting_from_a
		]
		assert paths == ["mesh.stored_geometry"]

	def test_they_are_kept_when_geometry_is_not_being_restored(self):
		# Without stored positions these digests are the only evidence the
		# mesh changed at all, so the user still needs to see them.
		diff = _scene_diff(_modified("Sphere", [
			("mesh.vertex_positions", "2:aaa", "2:bbb"),
			("mesh.bbox_min", [0, 0, 0], [1, 1, 1]),
		]))

		paths = [
			c.property_path
			for c in build_restore(diff).proposals[0].non_conflicting_from_a
		]
		assert paths == ["mesh.vertex_positions", "mesh.bbox_min"]

	def test_other_changes_on_the_same_object_still_apply(self):
		diff = _scene_diff(_modified("Sphere", [
			("mesh.stored_geometry", "q1:old", "q1:new"),
			("mesh.vertex_positions", "2:aaa", "2:bbb"),
			("transform.location", [0, 0, 0], [1, 0, 0]),
			("hide_render", True, False),
		]))

		paths = [
			c.property_path
			for c in build_restore(diff).proposals[0].non_conflicting_from_a
		]
		assert paths == ["mesh.stored_geometry", "transform.location", "hide_render"]

	def test_one_object_restoring_geometry_does_not_affect_another(self):
		diff = _scene_diff(
			_modified("Sphere", [
				("mesh.stored_geometry", "q1:old", "q1:new"),
				("mesh.vertex_positions", "2:aaa", "2:bbb"),
			]),
			_modified("Cube", [("mesh.vertex_positions", "2:ccc", "2:ddd")]),
		)

		by_name = {p.object_name: p for p in build_restore(diff).proposals}
		assert [c.property_path for c in by_name["Sphere"].non_conflicting_from_a] == [
			"mesh.stored_geometry"
		]
		assert [c.property_path for c in by_name["Cube"].non_conflicting_from_a] == [
			"mesh.vertex_positions"
		]
