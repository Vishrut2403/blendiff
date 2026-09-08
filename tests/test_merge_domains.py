"""
tests/test_merge_domains.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Merge coverage across every diff domain.

Previously the merge engine folded in only ``object_diffs``. Two artists
editing the same rig's constraints, parenting, drivers, custom properties,
collections or render settings merged "cleanly" with no conflict reported —
a silent wrong answer on the operation where silence is most costly.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.data_model.conflict import Resolution, TargetKind
from blendiff.merge_engine.merge_engine import MergeEngine


def _obj(name="Cube", obj_id=None, **extra):
	data = {
		"name": name,
		"type": "MESH",
		"collection_path": "Scene Collection",
		"transform": {
			"location": [0.0, 0.0, 0.0],
			"rotation_euler": [0.0, 0.0, 0.0],
			"scale": [1.0, 1.0, 1.0],
		},
		"material_slots": [],
		"visible": True,
		"parent": {"parent_name": None, "parent_type": None, "parent_bone": None},
		"constraint_stack": [],
		"custom_props": {},
	}
	if obj_id is not None:
		data["blendiff_id"] = obj_id
	data.update(extra)
	return data


def _scene(objects=None, collections=None, **extra):
	scene = {
		"blender_version": "4.1.0",
		"scene_name": "Scene",
		"objects": objects if objects is not None else {},
		"collections": collections or {},
		"transform_space": "local",
	}
	scene.update(extra)
	return scene


def _conflicts(tw, name=None):
	out = []
	for p in tw.proposals:
		if name is None or p.object_name == name:
			out.extend(p.conflicts)
	return out


def _paths(entries):
	return {e.property_path for e in entries}


class TestParentDomain:
	def test_conflicting_reparent_is_detected(self):
		base = _scene({"Cube": _obj()})
		a = _scene({"Cube": _obj(parent={"parent_name": "RigA", "parent_type": "OBJECT",
		                                 "parent_bone": None})})
		b = _scene({"Cube": _obj(parent={"parent_name": "RigB", "parent_type": "OBJECT",
		                                 "parent_bone": None})})

		tw = MergeEngine().three_way_diff(base, a, b)
		assert "parent.parent_name" in _paths(_conflicts(tw))
		assert tw.unresolved_conflicts == 1

	def test_matching_reparent_auto_resolves(self):
		parent = {"parent_name": "Rig", "parent_type": "OBJECT", "parent_bone": None}
		base = _scene({"Cube": _obj()})
		side = _scene({"Cube": _obj(parent=parent)})

		tw = MergeEngine().three_way_diff(base, side, side)
		assert tw.unresolved_conflicts == 0
		assert tw.auto_resolved_count >= 1

	def test_one_sided_reparent_is_not_a_conflict(self):
		base = _scene({"Cube": _obj()})
		a = _scene({"Cube": _obj(parent={"parent_name": "Rig", "parent_type": "OBJECT",
		                                 "parent_bone": None})})

		tw = MergeEngine().three_way_diff(base, a, base)
		assert tw.total_conflicts == 0
		assert _paths(tw.proposals[0].non_conflicting_from_a) == {
			"parent.parent_name", "parent.parent_type",
		}

	def test_parent_change_is_applicable(self):
		base = _scene({"Cube": _obj()})
		a = _scene({"Cube": _obj(parent={"parent_name": "Rig", "parent_type": "OBJECT",
		                                 "parent_bone": None})})
		tw = MergeEngine().three_way_diff(base, a, base)
		assert tw.proposals[0].non_conflicting_from_a[0].applicable


class TestCustomPropDomain:
	def test_conflicting_custom_prop_is_detected(self):
		base = _scene({"Cube": _obj(custom_props={"rig_version": 1})})
		a = _scene({"Cube": _obj(custom_props={"rig_version": 2})})
		b = _scene({"Cube": _obj(custom_props={"rig_version": 3})})

		tw = MergeEngine().three_way_diff(base, a, b)
		conflict = _conflicts(tw)[0]
		assert conflict.property_path == "custom_props.rig_version"
		assert conflict.value_a == 2 and conflict.value_b == 3

	def test_custom_prop_conflict_is_applicable(self):
		base = _scene({"Cube": _obj(custom_props={"v": 1})})
		a = _scene({"Cube": _obj(custom_props={"v": 2})})
		b = _scene({"Cube": _obj(custom_props={"v": 3})})
		assert _conflicts(MergeEngine().three_way_diff(base, a, b))[0].applicable


class TestConstraintDomain:
	def _with_constraint(self, influence):
		return _obj(constraint_stack=[{
			"index": 0, "name": "Copy Location", "type": "COPY_LOCATION",
			"influence": influence, "enabled": True,
			"params": {"target": "Rig"},
		}])

	def test_conflicting_constraint_influence_is_detected(self):
		base = _scene({"Cube": self._with_constraint(1.0)})
		a = _scene({"Cube": self._with_constraint(0.5)})
		b = _scene({"Cube": self._with_constraint(0.25)})

		tw = MergeEngine().three_way_diff(base, a, b)
		assert tw.total_conflicts >= 1

	def test_constraint_conflict_is_marked_unapplicable(self):
		"""
		BlenDiff can detect constraint differences but not rebuild them, and
		must say so rather than accept a resolution it would discard.
		"""
		base = _scene({"Cube": self._with_constraint(1.0)})
		a = _scene({"Cube": self._with_constraint(0.5)})
		b = _scene({"Cube": self._with_constraint(0.25)})

		tw = MergeEngine().three_way_diff(base, a, b)
		conflict = _conflicts(tw)[0]
		assert not conflict.applicable
		assert conflict.unsupported_reason


class TestCollectionDomain:
	def _cols(self, objects):
		return {"Scene Collection": {
			"name": "Scene Collection", "path": "Scene Collection",
			"children": [], "objects": objects,
		}}

	def test_conflicting_collection_contents_detected(self):
		base = _scene(collections=self._cols(["Cube"]))
		a = _scene(collections=self._cols(["Cube", "Sphere"]))
		b = _scene(collections=self._cols(["Cube", "Cone"]))

		tw = MergeEngine().three_way_diff(base, a, b)
		assert len(tw.collection_proposals) == 1
		assert tw.total_conflicts == 1

	def test_collection_proposal_is_tagged(self):
		base = _scene(collections=self._cols(["Cube"]))
		a = _scene(collections=self._cols(["Cube", "Sphere"]))
		tw = MergeEngine().three_way_diff(base, a, base)
		assert tw.collection_proposals[0].target_kind == TargetKind.COLLECTION

	def test_identical_collection_edit_auto_resolves(self):
		base = _scene(collections=self._cols(["Cube"]))
		side = _scene(collections=self._cols(["Cube", "Sphere"]))
		tw = MergeEngine().three_way_diff(base, side, side)
		assert tw.unresolved_conflicts == 0

	def test_unchanged_collections_make_no_proposal(self):
		base = _scene(collections=self._cols(["Cube"]))
		assert MergeEngine().three_way_diff(base, base, base).proposals == []


class TestSceneDomain:
	def test_conflicting_render_settings_detected(self):
		base = _scene(render={"engine": "CYCLES", "resolution_x": 1920})
		a = _scene(render={"engine": "CYCLES", "resolution_x": 3840})
		b = _scene(render={"engine": "CYCLES", "resolution_x": 2560})

		tw = MergeEngine().three_way_diff(base, a, b)
		assert len(tw.scene_proposals) == 1
		assert tw.total_conflicts == 1

	def test_scene_custom_prop_conflict_detected(self):
		base = _scene(scene_custom_props={"shot": "010"})
		a = _scene(scene_custom_props={"shot": "020"})
		b = _scene(scene_custom_props={"shot": "030"})

		tw = MergeEngine().three_way_diff(base, a, b)
		assert tw.total_conflicts == 1

	def test_one_sided_render_change_is_not_a_conflict(self):
		base = _scene(render={"engine": "CYCLES", "resolution_x": 1920})
		a = _scene(render={"engine": "CYCLES", "resolution_x": 3840})
		tw = MergeEngine().three_way_diff(base, a, base)
		assert tw.total_conflicts == 0
		assert tw.scene_proposals[0].non_conflicting_from_a


class TestRenameAcrossSides:
	def test_object_renamed_on_one_side_stays_one_proposal(self):
		base = _scene({"Cube": _obj("Cube", "id-1")})
		a = _scene({"Body": _obj("Body", "id-1")})
		b = _scene({"Cube": _obj("Cube", "id-1", visible=False)})

		tw = MergeEngine().three_way_diff(base, a, b)
		assert len(tw.object_proposals) == 1

	def test_divergent_renames_conflict(self):
		"""
		A renamed to Body, B renamed to Torso. Keying on each diff's own output
		name would split this into two unrelated proposals and lose the clash.
		"""
		base = _scene({"Cube": _obj("Cube", "id-1")})
		a = _scene({"Body": _obj("Body", "id-1")})
		b = _scene({"Torso": _obj("Torso", "id-1")})

		tw = MergeEngine().three_way_diff(base, a, b)
		assert len(tw.object_proposals) == 1
		conflict = _conflicts(tw)[0]
		assert conflict.property_path == "name"
		assert conflict.value_a == "Body" and conflict.value_b == "Torso"

	def test_identical_rename_auto_resolves(self):
		base = _scene({"Cube": _obj("Cube", "id-1")})
		side = _scene({"Body": _obj("Body", "id-1")})
		tw = MergeEngine().three_way_diff(base, side, side)
		assert tw.unresolved_conflicts == 0

	def test_rename_and_edit_on_opposite_sides_do_not_conflict(self):
		base = _scene({"Cube": _obj("Cube", "id-1")})
		a = _scene({"Body": _obj("Body", "id-1")})
		b = _scene({"Cube": _obj("Cube", "id-1", visible=False)})

		tw = MergeEngine().three_way_diff(base, a, b)
		proposal = tw.object_proposals[0]
		assert proposal.conflicts == []
		assert _paths(proposal.non_conflicting_from_a) == {"name"}
		assert _paths(proposal.non_conflicting_from_b) == {"visible"}

	def test_proposal_records_previous_name(self):
		base = _scene({"Cube": _obj("Cube", "id-1")})
		a = _scene({"Body": _obj("Body", "id-1")})
		tw = MergeEngine().three_way_diff(base, a, base)
		assert tw.object_proposals[0].previous_name == "Cube"


class TestApplicabilityReporting:
	def test_summary_counts_unapplicable_conflicts(self):
		base = _scene({"Cube": _obj(mesh_data={"vertex_count": 8})})
		a = _scene({"Cube": _obj(mesh_data={"vertex_count": 16})})
		b = _scene({"Cube": _obj(mesh_data={"vertex_count": 32})})

		tw = MergeEngine().three_way_diff(base, a, b)
		assert tw.summary()["unapplicable"] >= 1

	def test_proposal_flags_unapplicable_content(self):
		base = _scene({"Cube": _obj(mesh_data={"vertex_count": 8})})
		a = _scene({"Cube": _obj(mesh_data={"vertex_count": 16})})
		tw = MergeEngine().three_way_diff(base, a, base)
		assert tw.object_proposals[0].has_unapplicable_changes

	def test_applicable_change_is_not_flagged(self):
		base = _scene({"Cube": _obj()})
		a = _scene({"Cube": _obj(visible=False)})
		tw = MergeEngine().three_way_diff(base, a, base)
		assert not tw.object_proposals[0].has_unapplicable_changes


class TestBothDeleted:
	def test_both_sides_deleting_is_agreement_not_conflict(self):
		base = _scene({"Cube": _obj()})
		empty = _scene({})
		tw = MergeEngine().three_way_diff(base, empty, empty)
		assert tw.unresolved_conflicts == 0
		assert tw.all_resolved


class TestUnapplicableConflictsDoNotBlockMerge:
	"""
	A conflict BlenDiff cannot write back must not hold up the ones it can.

	Requiring a resolution there would ask the user to choose between two
	values and then silently discard the choice.
	"""

	def _diff(self):
		base = _scene({"Cube": _obj(mesh_data={"vertex_count": 8})})
		a = _scene({"Cube": _obj(mesh_data={"vertex_count": 16}, visible=False)})
		b = _scene({"Cube": _obj(mesh_data={"vertex_count": 32}, visible=True)})
		return MergeEngine().three_way_diff(base, a, b)

	def test_unapplicable_conflict_is_not_counted_unresolved(self):
		tw = self._diff()
		informational = [c for c in _conflicts(tw) if not c.applicable]
		assert informational
		assert tw.unresolved_conflicts == 0

	def test_merge_is_ready_once_applicable_conflicts_are_resolved(self):
		base = _scene({"Cube": _obj(mesh_data={"vertex_count": 8})})
		a = _scene({"Cube": _obj(mesh_data={"vertex_count": 16}, visible=False)})
		b = _scene({"Cube": _obj(mesh_data={"vertex_count": 32}, visible=True)})
		tw = MergeEngine().three_way_diff(base, a, b)

		for proposal in tw.proposals:
			proposal.resolve_all(Resolution.USE_A)
		assert tw.all_resolved

	def test_resolve_all_leaves_unapplicable_alone(self):
		tw = self._diff()
		for proposal in tw.proposals:
			proposal.resolve_all(Resolution.USE_A)

		informational = [c for c in _conflicts(tw) if not c.applicable]
		assert all(c.resolution == Resolution.UNRESOLVED for c in informational)

	def test_summary_still_reports_them(self):
		"""They must stay visible, just not blocking."""
		assert self._diff().summary()["unapplicable"] >= 1
