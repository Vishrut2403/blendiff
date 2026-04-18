"""
blendiff.merge_engine.merge_engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Three-way diff and assisted merge engine.

Algorithm
---------
Given: base snapshot, version_a snapshot, version_b snapshot

1. diff_a = DiffEngine.compare(base, version_a)
2. diff_b = DiffEngine.compare(base, version_b)
3. For each object present in either diff:
   - Build a MergeProposal with conflicts and non-conflicting changes
4. Return a ThreeWayDiff

Conflict detection rules
------------------------
  BOTH_MODIFIED:  property changed in both A and B to different values
  MODIFY_DELETE:  A modified object, B deleted it  (or vice versa)
  ADD_ADD:        A and B both added object with same name but different data
  AUTO-RESOLVED:  A and B made the same change → take it, no conflict

Design rules
------------
* No bpy imports — pure Python, fully testable.
* Stateless — three_way_diff() is a pure function.
* Never applies changes — only proposes them.
"""

from __future__ import annotations

import math
from typing import Any

from ..data_model.diff import ChangeKind, PropertyChange, SceneDiff
from ..data_model.conflict import (
	ConflictKind,
	MergeProposal,
	NonConflictingChange,
	PropertyConflict,
	Resolution,
	ThreeWayDiff,
)
from ..diff_engine.diff_engine import DiffEngine

_DEFAULT_EPSILON = 1e-4


class MergeEngine:
	"""Three-way diff and assisted merge proposal engine."""

	def __init__(self, epsilon: float = _DEFAULT_EPSILON) -> None:
		self._eps = epsilon
		self._engine = DiffEngine(epsilon=epsilon)

	# Public API

	def three_way_diff(
		self,
		base: dict,
		version_a: dict,
		version_b: dict,
		base_label:  str = "Base",
		label_a:     str = "Version A",
		label_b:     str = "Version B",
	) -> ThreeWayDiff:
		"""
		Produce a ThreeWayDiff from three serialised scene snapshots.

		Parameters
		----------
		base, version_a, version_b:
			Dicts produced by SceneSerializer.serialize().

		Returns
		-------
		ThreeWayDiff ready for conflict resolution UI.
		"""
		diff_a = self._engine.compare(base, version_a)
		diff_b = self._engine.compare(base, version_b)

		result = ThreeWayDiff(
			base_label=base_label,
			label_a=label_a,
			label_b=label_b,
		)

		proposals, auto_count = self._build_proposals(
			base, version_a, version_b, diff_a, diff_b
		)
		result.proposals = proposals
		result.auto_resolved_count = auto_count

		return result

	# Proposal building

	def _build_proposals(
		self,
		base: dict,
		version_a: dict,
		version_b: dict,
		diff_a: SceneDiff,
		diff_b: SceneDiff,
	) -> tuple[list[MergeProposal], int]:
		proposals: list[MergeProposal] = []
		auto_count = 0

		# Collect all object names touched by either diff
		names_a = {d.name for d in diff_a.object_diffs}
		names_b = {d.name for d in diff_b.object_diffs}
		all_names = sorted(names_a | names_b)

		# Build lookup maps
		diff_a_map = {d.name: d for d in diff_a.object_diffs}
		diff_b_map = {d.name: d for d in diff_b.object_diffs}

		objs_base = base.get("objects", {})
		objs_a    = version_a.get("objects", {})
		objs_b    = version_b.get("objects", {})

		for name in all_names:
			da = diff_a_map.get(name)
			db = diff_b_map.get(name)

			proposal, autos = self._build_object_proposal(
				name, da, db, objs_base, objs_a, objs_b
			)
			auto_count += autos
			if proposal is not None:
				proposals.append(proposal)

		return proposals, auto_count

	def _build_object_proposal(
		self,
		name: str,
		da,   # ObjectDiff | None
		db,   # ObjectDiff | None
		objs_base: dict,
		objs_a: dict,
		objs_b: dict,
	) -> tuple[MergeProposal | None, int]:
		"""
		Build a MergeProposal for one object.
		Returns (proposal, auto_resolved_count).
		Returns (None, 0) if nothing to merge.
		"""
		auto_count = 0

		# Only one side touched this object — no conflict possible
		if da is None:
			# Only B changed it
			proposal = MergeProposal(object_name=name)
			for change in db.changes:
				proposal.non_conflicting_from_b.append(NonConflictingChange(
					property_path=change.property_path,
					base_value=change.old_value,
					new_value=change.new_value,
					source="b",
				))
			# Structural (added/removed)
			if db.kind in (ChangeKind.ADDED, ChangeKind.REMOVED):
				proposal.non_conflicting_from_b.append(NonConflictingChange(
					property_path="__structural__",
					base_value=None,
					new_value=db.kind.value,
					source="b",
				))
			return proposal, 0

		if db is None:
			# Only A changed it
			proposal = MergeProposal(object_name=name)
			for change in da.changes:
				proposal.non_conflicting_from_a.append(NonConflictingChange(
					property_path=change.property_path,
					base_value=change.old_value,
					new_value=change.new_value,
					source="a",
				))
			if da.kind in (ChangeKind.ADDED, ChangeKind.REMOVED):
				proposal.non_conflicting_from_a.append(NonConflictingChange(
					property_path="__structural__",
					base_value=None,
					new_value=da.kind.value,
					source="a",
				))
			return proposal, 0

		# Both sides touched this object — check for conflicts

		# MODIFY_DELETE / DELETE_MODIFY
		if da.kind == ChangeKind.REMOVED and db.kind == ChangeKind.MODIFIED:
			proposal = MergeProposal(object_name=name, structural_conflict=True)
			proposal.conflicts.append(PropertyConflict(
				property_path="__existence__",
				base_value="exists",
				value_a="deleted",
				value_b="modified",
				kind=ConflictKind.DELETE_MODIFY,
			))
			return proposal, 0

		if da.kind == ChangeKind.MODIFIED and db.kind == ChangeKind.REMOVED:
			proposal = MergeProposal(object_name=name, structural_conflict=True)
			proposal.conflicts.append(PropertyConflict(
				property_path="__existence__",
				base_value="exists",
				value_a="modified",
				value_b="deleted",
				kind=ConflictKind.MODIFY_DELETE,
			))
			return proposal, 0

		# ADD_ADD — both added same name with different data
		if da.kind == ChangeKind.ADDED and db.kind == ChangeKind.ADDED:
			obj_a = objs_a.get(name, {})
			obj_b = objs_b.get(name, {})
			if obj_a == obj_b:
				# Identical additions — auto-resolve, nothing to do
				return None, 1  # auto_count=1 so caller increments
			proposal = MergeProposal(object_name=name)
			proposal.conflicts.append(PropertyConflict(
				property_path="__add_add__",
				base_value=None,
				value_a=obj_a,
				value_b=obj_b,
				kind=ConflictKind.ADD_ADD,
			))
			return proposal, 0

		# Both MODIFIED — compare property-by-property
		proposal = MergeProposal(object_name=name)

		changes_a_map: dict[str, PropertyChange] = {c.property_path: c for c in da.changes}
		changes_b_map: dict[str, PropertyChange] = {c.property_path: c for c in db.changes}

		all_paths = sorted(set(changes_a_map) | set(changes_b_map))

		for path in all_paths:
			ca = changes_a_map.get(path)
			cb = changes_b_map.get(path)

			if ca is None:
				# Only B changed this property
				proposal.non_conflicting_from_b.append(NonConflictingChange(
					property_path=path,
					base_value=cb.old_value,
					new_value=cb.new_value,
					source="b",
				))
			elif cb is None:
				# Only A changed this property
				proposal.non_conflicting_from_a.append(NonConflictingChange(
					property_path=path,
					base_value=ca.old_value,
					new_value=ca.new_value,
					source="a",
				))
			else:
				# Both changed this property
				if self._values_equal(ca.new_value, cb.new_value):
					# Same change on both sides — auto-resolve
					proposal.conflicts.append(PropertyConflict(
						property_path=path,
						base_value=ca.old_value,
						value_a=ca.new_value,
						value_b=cb.new_value,
						kind=ConflictKind.BOTH_MODIFIED,
						resolution=Resolution.AUTO,
					))
					auto_count += 1
				else:
					# True conflict
					proposal.conflicts.append(PropertyConflict(
						property_path=path,
						base_value=ca.old_value,
						value_a=ca.new_value,
						value_b=cb.new_value,
						kind=ConflictKind.BOTH_MODIFIED,
					))

		# Only add proposal if there's actually something in it
		if (proposal.conflicts or
				proposal.non_conflicting_from_a or
				proposal.non_conflicting_from_b):
			return proposal, auto_count

		return None, auto_count

	# Value comparison (same epsilon logic as DiffEngine)

	def _values_equal(self, a: Any, b: Any) -> bool:
		if a is None and b is None:
			return True
		if a is None or b is None:
			return False
		if isinstance(a, float) and isinstance(b, float):
			return math.isclose(a, b, abs_tol=self._eps)
		if isinstance(a, list) and isinstance(b, list):
			if len(a) != len(b):
				return False
			return all(self._values_equal(x, y) for x, y in zip(a, b))
		return a == b
