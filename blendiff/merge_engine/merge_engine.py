"""
blendiff.merge_engine.merge_engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Three-way diff and assisted merge engine.

Algorithm
---------
Given base, version A and version B snapshots:

1. ``diff_a = DiffEngine.compare(base, version_a)``
2. ``diff_b = DiffEngine.compare(base, version_b)``
3. Fold *every* diff domain into per-target change sets
4. Compare those change sets property by property to build MergeProposals

Conflict detection rules
------------------------
  BOTH_MODIFIED:  property changed on both sides to different values
  MODIFY_DELETE:  one side modified the target, the other deleted it
  ADD_ADD:        both sides added a target with the same name, differently
  AUTO-RESOLVED:  both sides made the same change — take it, no conflict

Two properties of this implementation are worth stating explicitly.

**Every domain participates.** Earlier versions folded in only ``object_diffs``,
so two artists editing the same rig's constraints, parenting, drivers or custom
properties merged "cleanly" with no conflict reported — a silent wrong answer.
Collections and scene-level settings are covered too.

**Targets are keyed by their name in the base snapshot.** A and B are diffed
against the same ancestor but may rename an object differently; keying on each
diff's own output name would split one object into two unrelated proposals.

Design rules
------------
* No bpy imports — pure Python, fully testable.
* Stateless — three_way_diff() is a pure function.
* Never applies changes — only proposes them.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from ..data_model.conflict import (
	ConflictKind,
	MergeProposal,
	NonConflictingChange,
	PropertyConflict,
	Resolution,
	TargetKind,
	ThreeWayDiff,
)
from ..data_model.diff import ChangeKind, PropertyChange, SceneDiff
from ..diff_engine.diff_engine import DiffEngine
from .property_appliers import can_apply, unsupported_reason

_DEFAULT_EPSILON = 1e-4

#: Per-object diff domains folded into each object's change set.
_OBJECT_DOMAIN_FIELDS = (
	"parent_diffs",
	"constraint_diffs",
	"custom_prop_diffs",
	"fcurve_diffs",
	"driver_diffs",
	"nla_diffs",
)

#: Name of the synthetic proposal collecting scene-wide settings.
SCENE_TARGET = "Scene"


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

		proposals: list[MergeProposal] = []
		auto_count = 0

		obj_proposals, obj_autos = self._build_object_proposals(
			base, version_a, version_b, diff_a, diff_b,
		)
		proposals.extend(obj_proposals)
		auto_count += obj_autos

		col_proposals, col_autos = self._build_collection_proposals(diff_a, diff_b)
		proposals.extend(col_proposals)
		auto_count += col_autos

		scene_proposal, scene_autos = self._build_scene_proposal(diff_a, diff_b)
		if scene_proposal is not None:
			proposals.append(scene_proposal)
		auto_count += scene_autos

		result.proposals = proposals
		result.auto_resolved_count = auto_count
		return result

	# Object proposals

	def _build_object_proposals(
		self,
		base: dict,
		version_a: dict,
		version_b: dict,
		diff_a: SceneDiff,
		diff_b: SceneDiff,
	) -> tuple[list[MergeProposal], int]:
		proposals: list[MergeProposal] = []
		auto_count = 0

		changes_a, kinds_a, names_a = self._collect_object_changes(diff_a)
		changes_b, kinds_b, names_b = self._collect_object_changes(diff_b)

		objs_a = version_a.get("objects", {})
		objs_b = version_b.get("objects", {})

		for key in sorted(set(changes_a) | set(changes_b) | set(kinds_a) | set(kinds_b)):
			proposal, autos = self._build_object_proposal(
				key,
				kinds_a.get(key), kinds_b.get(key),
				changes_a.get(key, []), changes_b.get(key, []),
				names_a.get(key, key), names_b.get(key, key),
				objs_a, objs_b,
			)
			auto_count += autos
			if proposal is not None:
				proposals.append(proposal)

		return proposals, auto_count

	def _collect_object_changes(
		self,
		diff: SceneDiff,
	) -> tuple[dict[str, list[PropertyChange]], dict[str, ChangeKind], dict[str, str]]:
		"""
		Fold every per-object domain into one change set per object.

		Returns three maps keyed by the object's **base-snapshot** name:
		its combined property changes, its structural change kind, and the
		name it carries in this diff's newer snapshot.
		"""
		# The newer snapshot's name → the base snapshot's name.
		to_base = {new: old for old, new in diff.object_pairs}

		changes: dict[str, list[PropertyChange]] = {}
		kinds: dict[str, ChangeKind] = {}
		current_names: dict[str, str] = {}

		for obj_diff in diff.object_diffs:
			# An added object has no ancestor, so it is keyed by its own name.
			key = (
				obj_diff.name if obj_diff.kind == ChangeKind.ADDED
				else (obj_diff.previous_name or obj_diff.name)
			)
			kinds[key] = obj_diff.kind
			current_names[key] = obj_diff.name
			if obj_diff.changes:
				changes.setdefault(key, []).extend(obj_diff.changes)

		for field_name in _OBJECT_DOMAIN_FIELDS:
			for domain_diff in getattr(diff, field_name, []) or []:
				name = domain_diff.object_name
				key = to_base.get(name, name)
				current_names.setdefault(key, name)
				if domain_diff.changes:
					changes.setdefault(key, []).extend(domain_diff.changes)

		return changes, kinds, current_names

	def _build_object_proposal(
		self,
		key: str,
		kind_a: ChangeKind | None,
		kind_b: ChangeKind | None,
		changes_a: list[PropertyChange],
		changes_b: list[PropertyChange],
		name_a: str,
		name_b: str,
		objs_a: dict,
		objs_b: dict,
	) -> tuple[MergeProposal | None, int]:
		"""
		Build a MergeProposal for one object.

		Returns ``(proposal, auto_resolved_count)``; the proposal is None when
		there is nothing to merge.
		"""
		touched_a = bool(changes_a) or kind_a is not None
		touched_b = bool(changes_b) or kind_b is not None

		# The name to look up in the live scene, and the one to display.
		display_name = name_b if touched_b else name_a

		# Only one side touched this object — nothing can conflict.
		if not touched_a:
			return self._one_sided_proposal(
				display_name, key, changes_b, kind_b, source="b",
			), 0
		if not touched_b:
			return self._one_sided_proposal(
				display_name, key, changes_a, kind_a, source="a",
			), 0

		# Both sides touched it.
		structural = self._structural_conflict(key, display_name, kind_a, kind_b, objs_a, objs_b)
		if structural is not None:
			return structural

		proposal = MergeProposal(
			object_name=display_name,
			target_kind=TargetKind.OBJECT,
			previous_name=key if key != display_name else None,
		)
		auto_count = self._merge_change_sets(proposal, changes_a, changes_b)

		if proposal.conflicts or proposal.non_conflicting_from_a or proposal.non_conflicting_from_b:
			return proposal, auto_count
		return None, auto_count

	def _structural_conflict(
		self,
		key: str,
		display_name: str,
		kind_a: ChangeKind | None,
		kind_b: ChangeKind | None,
		objs_a: dict,
		objs_b: dict,
	) -> tuple[MergeProposal | None, int] | None:
		"""
		Detect delete/modify and add/add situations.

		Returns None when the situation is not structural, so the caller falls
		through to property-level merging.
		"""
		if kind_a == ChangeKind.REMOVED and kind_b != ChangeKind.REMOVED:
			return self._existence_conflict(
				display_name, "deleted", "modified", ConflictKind.DELETE_MODIFY,
			), 0

		if kind_b == ChangeKind.REMOVED and kind_a != ChangeKind.REMOVED:
			return self._existence_conflict(
				display_name, "modified", "deleted", ConflictKind.MODIFY_DELETE,
			), 0

		if kind_a == ChangeKind.REMOVED and kind_b == ChangeKind.REMOVED:
			# Both deleted it — agreement, not conflict.
			proposal = MergeProposal(object_name=display_name, target_kind=TargetKind.OBJECT)
			proposal.conflicts.append(self._mark(PropertyConflict(
				property_path="__existence__",
				base_value="exists",
				value_a="deleted",
				value_b="deleted",
				kind=ConflictKind.BOTH_MODIFIED,
				resolution=Resolution.AUTO,
			)))
			return proposal, 1

		if kind_a == ChangeKind.ADDED and kind_b == ChangeKind.ADDED:
			obj_a = objs_a.get(key, {})
			obj_b = objs_b.get(key, {})
			if obj_a == obj_b:
				# Identical additions — agreement, nothing to resolve.
				return None, 1
			proposal = MergeProposal(object_name=display_name, target_kind=TargetKind.OBJECT)
			proposal.conflicts.append(self._mark(PropertyConflict(
				property_path="__add_add__",
				base_value=None,
				value_a=obj_a,
				value_b=obj_b,
				kind=ConflictKind.ADD_ADD,
			)))
			return proposal, 0

		return None

	def _existence_conflict(
		self,
		name: str,
		value_a: str,
		value_b: str,
		kind: ConflictKind,
	) -> MergeProposal:
		proposal = MergeProposal(
			object_name=name,
			structural_conflict=True,
			target_kind=TargetKind.OBJECT,
		)
		proposal.conflicts.append(self._mark(PropertyConflict(
			property_path="__existence__",
			base_value="exists",
			value_a=value_a,
			value_b=value_b,
			kind=kind,
		)))
		return proposal

	def _one_sided_proposal(
		self,
		display_name: str,
		key: str,
		changes: list[PropertyChange],
		kind: ChangeKind | None,
		source: str,
	) -> MergeProposal | None:
		"""Build a proposal for a target only one side touched."""
		proposal = MergeProposal(
			object_name=display_name,
			target_kind=TargetKind.OBJECT,
			previous_name=key if key != display_name else None,
		)
		bucket = (
			proposal.non_conflicting_from_a if source == "a"
			else proposal.non_conflicting_from_b
		)

		for change in changes:
			bucket.append(self._mark(NonConflictingChange(
				property_path=change.property_path,
				base_value=change.old_value,
				new_value=change.new_value,
				source=source,
			)))

		if kind in (ChangeKind.ADDED, ChangeKind.REMOVED):
			bucket.append(self._mark(NonConflictingChange(
				property_path="__structural__",
				base_value=None,
				new_value=kind.value,
				source=source,
			)))

		if not bucket:
			return None
		return proposal

	# Collection and scene proposals

	def _build_collection_proposals(
		self,
		diff_a: SceneDiff,
		diff_b: SceneDiff,
	) -> tuple[list[MergeProposal], int]:
		"""
		Merge collection hierarchy changes.

		Previously ignored entirely, so two artists reorganising the same
		collection merged "cleanly" while one reorganisation was lost.
		"""
		changes_a = {d.path: d for d in diff_a.collection_diffs}
		changes_b = {d.path: d for d in diff_b.collection_diffs}

		proposals: list[MergeProposal] = []
		auto_count = 0

		for path in sorted(set(changes_a) | set(changes_b)):
			da = changes_a.get(path)
			db = changes_b.get(path)

			proposal = MergeProposal(
				object_name=path,
				target_kind=TargetKind.COLLECTION,
			)

			if da is None or db is None:
				side = "b" if da is None else "a"
				only = db if da is None else da
				bucket = (
					proposal.non_conflicting_from_a if side == "a"
					else proposal.non_conflicting_from_b
				)
				for change in only.changes:
					bucket.append(self._mark(NonConflictingChange(
						property_path=change.property_path,
						base_value=change.old_value,
						new_value=change.new_value,
						source=side,
					), prefix="collection"))
				if only.kind in (ChangeKind.ADDED, ChangeKind.REMOVED):
					bucket.append(self._mark(NonConflictingChange(
						property_path="__structural__",
						base_value=None,
						new_value=only.kind.value,
						source=side,
					), prefix="collection"))
				if bucket:
					proposals.append(proposal)
				continue

			autos = self._merge_change_sets(
				proposal, da.changes, db.changes, prefix="collection",
			)
			auto_count += autos
			if proposal.conflicts or proposal.non_conflicting_from_a or proposal.non_conflicting_from_b:
				proposals.append(proposal)

		return proposals, auto_count

	def _build_scene_proposal(
		self,
		diff_a: SceneDiff,
		diff_b: SceneDiff,
	) -> tuple[MergeProposal | None, int]:
		"""
		Merge scene-wide settings: render, world and scene custom properties.

		These conflict as readily as object properties — two people changing
		the sample count or output path is a real collision — and were
		previously invisible to the merge entirely.
		"""
		changes_a = self._scene_changes(diff_a)
		changes_b = self._scene_changes(diff_b)

		if not changes_a and not changes_b:
			return None, 0

		proposal = MergeProposal(
			object_name=SCENE_TARGET,
			target_kind=TargetKind.SCENE,
		)
		auto_count = self._merge_change_sets(
			proposal, changes_a, changes_b, prefix="scene",
		)

		if proposal.conflicts or proposal.non_conflicting_from_a or proposal.non_conflicting_from_b:
			return proposal, auto_count
		return None, auto_count

	@staticmethod
	def _scene_changes(diff: SceneDiff) -> list[PropertyChange]:
		changes: list[PropertyChange] = []
		changes.extend(diff.render_diff.changes)
		changes.extend(diff.world_diff.changes)
		if diff.scene_custom_prop_diff is not None:
			changes.extend(diff.scene_custom_prop_diff.changes)
		return changes

	# Shared change-set merging

	def _merge_change_sets(
		self,
		proposal: MergeProposal,
		changes_a: Iterable[PropertyChange],
		changes_b: Iterable[PropertyChange],
		prefix: str = "",
	) -> int:
		"""
		Compare two property change sets, filling in the proposal.

		Returns the number of changes auto-resolved because both sides made
		the identical edit.
		"""
		auto_count = 0

		map_a = {c.property_path: c for c in changes_a}
		map_b = {c.property_path: c for c in changes_b}

		for path in sorted(set(map_a) | set(map_b)):
			ca = map_a.get(path)
			cb = map_b.get(path)

			if ca is None:
				proposal.non_conflicting_from_b.append(self._mark(NonConflictingChange(
					property_path=path,
					base_value=cb.old_value,
					new_value=cb.new_value,
					source="b",
				), prefix=prefix))
			elif cb is None:
				proposal.non_conflicting_from_a.append(self._mark(NonConflictingChange(
					property_path=path,
					base_value=ca.old_value,
					new_value=ca.new_value,
					source="a",
				), prefix=prefix))
			elif self._values_equal(ca.new_value, cb.new_value):
				# Both sides made the same edit — agreement, not a conflict.
				proposal.conflicts.append(self._mark(PropertyConflict(
					property_path=path,
					base_value=ca.old_value,
					value_a=ca.new_value,
					value_b=cb.new_value,
					kind=ConflictKind.BOTH_MODIFIED,
					resolution=Resolution.AUTO,
				), prefix=prefix))
				auto_count += 1
			else:
				proposal.conflicts.append(self._mark(PropertyConflict(
					property_path=path,
					base_value=ca.old_value,
					value_a=ca.new_value,
					value_b=cb.new_value,
					kind=ConflictKind.BOTH_MODIFIED,
				), prefix=prefix))

		return auto_count

	@staticmethod
	def _mark(entry, prefix: str = ""):
		"""
		Record whether BlenDiff can write this property back to the scene.

		Doing this at proposal time is what lets the UI show unappliable
		differences as informational instead of asking the user to resolve
		something that would then be silently dropped.
		"""
		path = entry.property_path
		if not prefix or path.startswith("__") or path.startswith(f"{prefix}."):
			lookup = path
		else:
			lookup = f"{prefix}.{path}"

		entry.applicable = can_apply(lookup)
		if not entry.applicable:
			entry.unsupported_reason = unsupported_reason(lookup)
		return entry

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
