"""
tests/test_merge_engine.py

Unit tests for the three-way merge engine and conflict data model.
No bpy required — runs with plain pytest.
"""

from __future__ import annotations

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.merge_engine.merge_engine import MergeEngine
from blendiff.data_model.conflict import (
	ConflictKind,
	MergeProposal,
	PropertyConflict,
	Resolution,
	ThreeWayDiff,
)


# Test scene builders

def make_scene(objects: dict, collections: dict = None) -> dict:
	return {
		"blender_version": "5.1.0",
		"scene_name": "Scene",
		"objects": objects,
		"collections": collections or {},
	}


def make_object(
	name="Cube",
	location=(0.0, 0.0, 0.0),
	scale=(1.0, 1.0, 1.0),
	visible=True,
	collection="Collection",
	material_slots=None,
) -> dict:
	return {
		"name": name,
		"type": "MESH",
		"collection_path": collection,
		"transform": {
			"location": list(location),
			"rotation_euler": [0.0, 0.0, 0.0],
			"scale": list(scale),
		},
		"material_slots": material_slots or [],
		"visible": visible,
	}


# ThreeWayDiff data model

class TestThreeWayDiffDataModel:
	def test_summary_empty(self):
		tw = ThreeWayDiff(base_label="B", label_a="A", label_b="B")
		s = tw.summary()
		assert s["total_proposals"] == 0
		assert s["ready_to_apply"] is True

	def test_all_resolved_when_no_proposals(self):
		tw = ThreeWayDiff(base_label="B", label_a="A", label_b="B")
		assert tw.all_resolved is True

	def test_unresolved_count(self):
		conflict = PropertyConflict(
			property_path="transform.location",
			base_value=[0, 0, 0],
			value_a=[1, 0, 0],
			value_b=[0, 1, 0],
			kind=ConflictKind.BOTH_MODIFIED,
		)
		proposal = MergeProposal(object_name="Cube", conflicts=[conflict])
		tw = ThreeWayDiff(base_label="B", label_a="A", label_b="B",
						  proposals=[proposal])
		assert tw.unresolved_conflicts == 1
		assert tw.all_resolved is False


class TestMergeProposal:
	def test_resolve_sets_resolution(self):
		conflict = PropertyConflict(
			property_path="transform.location",
			base_value=[0, 0, 0],
			value_a=[1, 0, 0],
			value_b=[0, 1, 0],
			kind=ConflictKind.BOTH_MODIFIED,
		)
		proposal = MergeProposal(object_name="Cube", conflicts=[conflict])
		result = proposal.resolve("transform.location", Resolution.USE_A)
		assert result is True
		assert conflict.resolution == Resolution.USE_A
		assert proposal.all_resolved is True

	def test_resolve_nonexistent_returns_false(self):
		proposal = MergeProposal(object_name="Cube")
		assert proposal.resolve("nonexistent", Resolution.USE_A) is False

	def test_resolve_all(self):
		c1 = PropertyConflict("p1", None, 1, 2, ConflictKind.BOTH_MODIFIED)
		c2 = PropertyConflict("p2", None, 3, 4, ConflictKind.BOTH_MODIFIED)
		proposal = MergeProposal(object_name="Cube", conflicts=[c1, c2])
		proposal.resolve_all(Resolution.USE_B)
		assert proposal.all_resolved is True
		assert c1.resolution == Resolution.USE_B
		assert c2.resolution == Resolution.USE_B

	def test_unresolved_count(self):
		c1 = PropertyConflict("p1", None, 1, 2, ConflictKind.BOTH_MODIFIED)
		c2 = PropertyConflict("p2", None, 3, 4, ConflictKind.BOTH_MODIFIED,
							  resolution=Resolution.USE_A)
		proposal = MergeProposal(object_name="Cube", conflicts=[c1, c2])
		assert proposal.unresolved_count == 1


class TestPropertyConflict:
	def test_resolved_value_use_a(self):
		c = PropertyConflict("p", "base", "val_a", "val_b",
							 ConflictKind.BOTH_MODIFIED, Resolution.USE_A)
		assert c.resolved_value == "val_a"

	def test_resolved_value_use_b(self):
		c = PropertyConflict("p", "base", "val_a", "val_b",
							 ConflictKind.BOTH_MODIFIED, Resolution.USE_B)
		assert c.resolved_value == "val_b"

	def test_resolved_value_use_base(self):
		c = PropertyConflict("p", "base", "val_a", "val_b",
							 ConflictKind.BOTH_MODIFIED, Resolution.USE_BASE)
		assert c.resolved_value == "base"

	def test_resolved_value_raises_when_unresolved(self):
		c = PropertyConflict("p", "base", "val_a", "val_b",
							 ConflictKind.BOTH_MODIFIED)
		with pytest.raises(ValueError):
			_ = c.resolved_value

	def test_auto_resolved_is_resolved(self):
		c = PropertyConflict("p", "base", "val_a", "val_a",
							 ConflictKind.BOTH_MODIFIED, Resolution.AUTO)
		assert c.is_resolved is True


# MergeEngine.three_way_diff — no changes

class TestNoChanges:
	def test_identical_scenes_no_proposals(self):
		engine = MergeEngine()
		scene = make_scene({"Cube": make_object()})
		tw = engine.three_way_diff(scene, scene, scene)
		assert tw.proposals == []
		assert tw.all_resolved is True

	def test_labels_stored(self):
		engine = MergeEngine()
		scene = make_scene({"Cube": make_object()})
		tw = engine.three_way_diff(scene, scene, scene,
								   base_label="Base",
								   label_a="A", label_b="B")
		assert tw.base_label == "Base"
		assert tw.label_a == "A"
		assert tw.label_b == "B"


# MergeEngine — one side only changed (no conflict)

class TestOneSideOnly:
	def test_only_a_changed_no_conflict(self):
		engine = MergeEngine()
		base = make_scene({"Cube": make_object(location=(0, 0, 0))})
		ver_a = make_scene({"Cube": make_object(location=(1, 0, 0))})
		ver_b = make_scene({"Cube": make_object(location=(0, 0, 0))})  # unchanged

		tw = engine.three_way_diff(base, ver_a, ver_b)
		assert len(tw.proposals) == 1
		assert not tw.proposals[0].has_conflicts
		assert len(tw.proposals[0].non_conflicting_from_a) == 1

	def test_only_b_changed_no_conflict(self):
		engine = MergeEngine()
		base = make_scene({"Cube": make_object(location=(0, 0, 0))})
		ver_a = make_scene({"Cube": make_object(location=(0, 0, 0))})  # unchanged
		ver_b = make_scene({"Cube": make_object(location=(5, 0, 0))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		assert len(tw.proposals) == 1
		assert not tw.proposals[0].has_conflicts
		assert len(tw.proposals[0].non_conflicting_from_b) == 1

	def test_only_a_changed_auto_resolved(self):
		engine = MergeEngine()
		base = make_scene({"Cube": make_object(location=(0, 0, 0))})
		ver_a = make_scene({"Cube": make_object(location=(1, 0, 0))})
		ver_b = make_scene({"Cube": make_object(location=(0, 0, 0))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		assert tw.all_resolved is True


# MergeEngine — BOTH_MODIFIED conflict

class TestBothModified:
	def test_both_modified_different_values_is_conflict(self):
		engine = MergeEngine()
		base  = make_scene({"Cube": make_object(location=(0, 0, 0))})
		ver_a = make_scene({"Cube": make_object(location=(1, 0, 0))})
		ver_b = make_scene({"Cube": make_object(location=(0, 5, 0))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		assert len(tw.proposals) == 1
		proposal = tw.proposals[0]
		assert proposal.has_conflicts
		assert len(proposal.conflicts) == 1
		assert proposal.conflicts[0].kind == ConflictKind.BOTH_MODIFIED
		assert proposal.conflicts[0].resolution == Resolution.UNRESOLVED

	def test_both_modified_same_value_auto_resolved(self):
		engine = MergeEngine()
		base  = make_scene({"Cube": make_object(location=(0, 0, 0))})
		ver_a = make_scene({"Cube": make_object(location=(3, 0, 0))})
		ver_b = make_scene({"Cube": make_object(location=(3, 0, 0))})  # same as A

		tw = engine.three_way_diff(base, ver_a, ver_b)
		proposal = tw.proposals[0]
		auto = [c for c in proposal.conflicts if c.resolution == Resolution.AUTO]
		assert len(auto) == 1
		assert tw.auto_resolved_count == 1

	def test_both_modified_epsilon_same_value_auto_resolved(self):
		engine = MergeEngine(epsilon=1e-4)
		base  = make_scene({"Cube": make_object(location=(0, 0, 0))})
		ver_a = make_scene({"Cube": make_object(location=(1.0, 0, 0))})
		ver_b = make_scene({"Cube": make_object(location=(1.0 + 1e-5, 0, 0))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		assert tw.auto_resolved_count >= 1

	def test_conflict_stores_all_three_values(self):
		engine = MergeEngine()
		base  = make_scene({"Cube": make_object(location=(0, 0, 0))})
		ver_a = make_scene({"Cube": make_object(location=(1, 0, 0))})
		ver_b = make_scene({"Cube": make_object(location=(0, 5, 0))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		conflict = tw.proposals[0].conflicts[0]
		assert conflict.base_value == [0.0, 0.0, 0.0]
		assert conflict.value_a    == [1.0, 0.0, 0.0]
		assert conflict.value_b    == [0.0, 5.0, 0.0]

	def test_multiple_properties_conflicting(self):
		engine = MergeEngine()
		base  = make_scene({"Cube": make_object(location=(0, 0, 0), scale=(1, 1, 1))})
		ver_a = make_scene({"Cube": make_object(location=(1, 0, 0), scale=(2, 2, 2))})
		ver_b = make_scene({"Cube": make_object(location=(0, 5, 0), scale=(3, 3, 3))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		proposal = tw.proposals[0]
		conflict_paths = {c.property_path for c in proposal.conflicts}
		assert "transform.location" in conflict_paths
		assert "transform.scale" in conflict_paths

	def test_mixed_conflict_and_non_conflicting(self):
		engine = MergeEngine()
		base  = make_scene({"Cube": make_object(location=(0, 0, 0), visible=True)})
		ver_a = make_scene({"Cube": make_object(location=(1, 0, 0), visible=True)})
		ver_b = make_scene({"Cube": make_object(location=(0, 0, 0), visible=False)})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		proposal = tw.proposals[0]
		assert not proposal.has_conflicts
		assert len(proposal.non_conflicting_from_a) == 1
		assert len(proposal.non_conflicting_from_b) == 1



# MergeEngine — structural conflicts

class TestStructuralConflicts:
	def test_modify_delete_conflict(self):
		engine = MergeEngine()
		base  = make_scene({"Cube": make_object()})
		ver_a = make_scene({"Cube": make_object(location=(1, 0, 0))}) 
		ver_b = make_scene({}) 

		tw = engine.three_way_diff(base, ver_a, ver_b)
		proposal = tw.proposals[0]
		assert proposal.structural_conflict is True
		assert proposal.conflicts[0].kind == ConflictKind.MODIFY_DELETE

	def test_delete_modify_conflict(self):
		engine = MergeEngine()
		base  = make_scene({"Cube": make_object()})
		ver_a = make_scene({})
		ver_b = make_scene({"Cube": make_object(location=(1, 0, 0))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		proposal = tw.proposals[0]
		assert proposal.structural_conflict is True
		assert proposal.conflicts[0].kind == ConflictKind.DELETE_MODIFY

	def test_add_add_identical_auto_resolved(self):
		engine = MergeEngine()
		base  = make_scene({})
		ver_a = make_scene({"NewObj": make_object("NewObj")})
		ver_b = make_scene({"NewObj": make_object("NewObj")})  # identical

		tw = engine.three_way_diff(base, ver_a, ver_b)
		# Identical additions — auto-resolved, no proposal
		assert len(tw.proposals) == 0
		assert tw.auto_resolved_count == 1

	def test_add_add_different_is_conflict(self):
		engine = MergeEngine()
		base  = make_scene({})
		ver_a = make_scene({"NewObj": make_object("NewObj", location=(1, 0, 0))})
		ver_b = make_scene({"NewObj": make_object("NewObj", location=(0, 5, 0))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		assert len(tw.proposals) == 1
		assert tw.proposals[0].conflicts[0].kind == ConflictKind.ADD_ADD


# Resolution workflow

class TestResolutionWorkflow:
	def test_resolve_makes_all_resolved(self):
		engine = MergeEngine()
		base  = make_scene({"Cube": make_object(location=(0, 0, 0))})
		ver_a = make_scene({"Cube": make_object(location=(1, 0, 0))})
		ver_b = make_scene({"Cube": make_object(location=(0, 5, 0))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		assert not tw.all_resolved

		tw.proposals[0].resolve("transform.location", Resolution.USE_A)
		assert tw.all_resolved

	def test_resolved_value_use_a(self):
		engine = MergeEngine()
		base  = make_scene({"Cube": make_object(location=(0, 0, 0))})
		ver_a = make_scene({"Cube": make_object(location=(1, 0, 0))})
		ver_b = make_scene({"Cube": make_object(location=(0, 5, 0))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		tw.proposals[0].resolve("transform.location", Resolution.USE_A)
		conflict = tw.proposals[0].conflicts[0]
		assert conflict.resolved_value == [1.0, 0.0, 0.0]

	def test_resolved_value_use_b(self):
		engine = MergeEngine()
		base  = make_scene({"Cube": make_object(location=(0, 0, 0))})
		ver_a = make_scene({"Cube": make_object(location=(1, 0, 0))})
		ver_b = make_scene({"Cube": make_object(location=(0, 5, 0))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		tw.proposals[0].resolve("transform.location", Resolution.USE_B)
		conflict = tw.proposals[0].conflicts[0]
		assert conflict.resolved_value == [0.0, 5.0, 0.0]

	def test_summary_reflects_resolution_state(self):
		engine = MergeEngine()
		base  = make_scene({"Cube": make_object(location=(0, 0, 0))})
		ver_a = make_scene({"Cube": make_object(location=(1, 0, 0))})
		ver_b = make_scene({"Cube": make_object(location=(0, 5, 0))})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		assert tw.summary()["unresolved"] == 1
		assert tw.summary()["ready_to_apply"] is False

		tw.proposals[0].resolve("transform.location", Resolution.USE_A)
		assert tw.summary()["unresolved"] == 0
		assert tw.summary()["ready_to_apply"] is True


# Multiple objects

class TestMultipleObjects:
	def test_multiple_objects_independent_conflicts(self):
		engine = MergeEngine()
		base = make_scene({
			"Cube":   make_object("Cube",   location=(0, 0, 0)),
			"Sphere": make_object("Sphere", location=(5, 0, 0)),
		})
		ver_a = make_scene({
			"Cube":   make_object("Cube",   location=(1, 0, 0)),
			"Sphere": make_object("Sphere", location=(5, 0, 0)),
		})
		ver_b = make_scene({
			"Cube":   make_object("Cube",   location=(0, 3, 0)),
			"Sphere": make_object("Sphere", location=(9, 0, 0)),
		})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		# Cube has a conflict, Sphere only B changed it
		cube_proposal = next(p for p in tw.proposals if p.object_name == "Cube")
		sphere_proposal = next(p for p in tw.proposals if p.object_name == "Sphere")

		assert cube_proposal.has_conflicts
		assert not sphere_proposal.has_conflicts

	def test_all_resolved_requires_all_proposals(self):
		engine = MergeEngine()
		base = make_scene({
			"A": make_object("A", location=(0, 0, 0)),
			"B": make_object("B", location=(0, 0, 0)),
		})
		ver_a = make_scene({
			"A": make_object("A", location=(1, 0, 0)),
			"B": make_object("B", location=(1, 0, 0)),
		})
		ver_b = make_scene({
			"A": make_object("A", location=(0, 5, 0)),
			"B": make_object("B", location=(0, 5, 0)),
		})

		tw = engine.three_way_diff(base, ver_a, ver_b)
		assert not tw.all_resolved

		# Resolve only one
		tw.proposals[0].resolve_all(Resolution.USE_A)
		assert not tw.all_resolved

		# Resolve the second
		tw.proposals[1].resolve_all(Resolution.USE_B)
		assert tw.all_resolved
