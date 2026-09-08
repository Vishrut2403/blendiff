"""
blendiff.data_model.conflict
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Dataclasses for the three-way merge system.

Hierarchy
---------
  ThreeWayDiff
	  └── MergeProposal          (one per object or collection)
			  └── PropertyConflict  (one per conflicting property)

Design rules
------------
* No bpy imports — pure Python, fully testable without Blender.
* MergeEngine produces MergeProposals; UI reads them and sets resolutions.
* A MergeProposal with all conflicts resolved is "ready to apply".
* Applier only runs when every conflict in every proposal is resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# Conflict kinds

class ConflictKind(str, Enum):
	BOTH_MODIFIED  = "both_modified"
	MODIFY_DELETE  = "modify_delete"   
	DELETE_MODIFY  = "delete_modify"   
	ADD_ADD        = "add_add"    


# Resolution choices
class Resolution(str, Enum):
	UNRESOLVED = "unresolved"
	USE_A      = "use_a"      
	USE_B      = "use_b" 
	USE_BASE   = "use_base" 
	AUTO       = "auto"


# Merge target kinds
#
# Merging is not only about objects: collection membership, render settings and
# scene custom properties conflict just as readily, and a proposal has to say
# what it is about so the UI can group and the applier can dispatch correctly.

class TargetKind(str, Enum):
	OBJECT     = "object"
	COLLECTION = "collection"
	SCENE      = "scene"


# Property-level conflict

@dataclass
class PropertyConflict:
	"""
	One property that conflicts between version A and version B.

	base_value  — value in the common ancestor snapshot
	value_a     — value in version A
	value_b     — value in version B
	resolution  — set by the user or auto-resolved

	``applicable`` records whether BlenDiff can actually write the chosen value
	back to the scene. Not every property BlenDiff can *detect* is one it can
	*apply* — mesh geometry is summarised rather than stored, for instance. The
	flag is set by MergeEngine from the applier registry so the UI can present
	those conflicts as informational instead of soliciting a resolution it
	would then silently discard.
	"""
	property_path: str
	base_value:    Any
	value_a:       Any
	value_b:       Any
	kind:          ConflictKind
	resolution:    Resolution = Resolution.UNRESOLVED
	applicable:    bool = True
	unsupported_reason: str = ""

	@property
	def is_resolved(self) -> bool:
		return self.resolution != Resolution.UNRESOLVED

	@property
	def resolved_value(self) -> Any:
		"""
		Return the value selected by the resolution.

		AUTO resolves to ``value_a``, not ``base_value``. AUTO means both
		sides made the *identical* change, so the agreed value is that change
		— returning the common ancestor's value instead would silently revert
		an edit both artists had made.
		"""
		if self.resolution == Resolution.USE_A:
			return self.value_a
		if self.resolution == Resolution.USE_B:
			return self.value_b
		if self.resolution == Resolution.AUTO:
			return self.value_a
		if self.resolution == Resolution.USE_BASE:
			return self.base_value
		raise ValueError(f"Conflict on '{self.property_path}' is not resolved yet.")


# Non-conflicting change

@dataclass
class NonConflictingChange:
	"""
	A change that only one side made — safe to auto-apply.

	source: 'a' or 'b'
	"""
	property_path: str
	base_value:    Any
	new_value:     Any
	source:        str
	applicable:    bool = True
	unsupported_reason: str = ""


# Per-object merge proposal

@dataclass
class MergeProposal:
	"""
	All merge information for one object or collection.

	Contains:
	- conflicts:              properties changed differently on A and B
	- non_conflicting_from_a: properties only A changed (safe to take)
	- non_conflicting_from_b: properties only B changed (safe to take)
	- structural_conflict:    True when one side deleted and the other modified
	"""
	object_name:          str
	conflicts:            list[PropertyConflict]       = field(default_factory=list)
	non_conflicting_from_a: list[NonConflictingChange] = field(default_factory=list)
	non_conflicting_from_b: list[NonConflictingChange] = field(default_factory=list)
	structural_conflict:  bool                         = False
	target_kind:          TargetKind                   = TargetKind.OBJECT
	# Name this target carried in the base snapshot, when it was renamed. The
	# applier needs it to find the object in a scene that still uses the old
	# name.
	previous_name:        Optional[str]                = None

	@property
	def has_conflicts(self) -> bool:
		return bool(self.conflicts)

	@property
	def applicable_conflicts(self) -> list[PropertyConflict]:
		"""Conflicts whose resolution BlenDiff can actually write back."""
		return [c for c in self.conflicts if c.applicable]

	@property
	def informational_conflicts(self) -> list[PropertyConflict]:
		"""
		Conflicts BlenDiff can detect but not apply.

		Shown so the user knows the two versions disagree, and knows they must
		reconcile it by hand.
		"""
		return [c for c in self.conflicts if not c.applicable]

	@property
	def all_resolved(self) -> bool:
		"""
		True when every *applicable* conflict has a resolution set.

		Conflicts BlenDiff cannot write back deliberately do not block the
		merge. Requiring a resolution for them would ask the user to choose
		between two values, then discard the choice — and would hold up the
		applicable changes for no benefit. They are surfaced as informational
		instead, so the user knows to reconcile them by hand.
		"""
		return all(c.is_resolved for c in self.applicable_conflicts)

	@property
	def has_unapplicable_changes(self) -> bool:
		"""True when this proposal contains anything BlenDiff cannot write back."""
		return bool(
			self.informational_conflicts
			or [c for c in self.non_conflicting_from_a if not c.applicable]
			or [c for c in self.non_conflicting_from_b if not c.applicable]
		)

	@property
	def conflict_count(self) -> int:
		return len(self.conflicts)

	@property
	def unresolved_count(self) -> int:
		"""Applicable conflicts still awaiting a decision."""
		return sum(1 for c in self.applicable_conflicts if not c.is_resolved)

	def resolve(self, property_path: str, resolution: Resolution) -> bool:
		"""
		Set resolution for a specific property conflict.
		Returns True if found and set, False if not found.
		"""
		for conflict in self.conflicts:
			if conflict.property_path == property_path:
				conflict.resolution = resolution
				return True
		return False

	def resolve_all(self, resolution: Resolution) -> None:
		"""
		Apply the same resolution to every unresolved, applicable conflict.

		Unapplicable conflicts are left alone: marking them resolved would
		imply the merge will act on them.
		"""
		for conflict in self.applicable_conflicts:
			if not conflict.is_resolved:
				conflict.resolution = resolution


# Top-level three-way diff result

@dataclass
class ThreeWayDiff:
	"""
	Result of a three-way comparison: base vs A vs B.

	Produced by MergeEngine.three_way_diff().
	Consumed by the UI for conflict resolution and by Applier for execution.
	"""
	base_label: str
	label_a:    str
	label_b:    str

	proposals:           list[MergeProposal] = field(default_factory=list)
	auto_resolved_count: int                 = 0

	@property
	def conflicting_proposals(self) -> list[MergeProposal]:
		return [p for p in self.proposals if p.has_conflicts]

	@property
	def clean_proposals(self) -> list[MergeProposal]:
		"""Proposals with no conflicts — changes from one side only."""
		return [p for p in self.proposals if not p.has_conflicts]

	@property
	def all_resolved(self) -> bool:
		return all(p.all_resolved for p in self.proposals)

	@property
	def total_conflicts(self) -> int:
		return sum(p.conflict_count for p in self.proposals)

	@property
	def object_proposals(self) -> list[MergeProposal]:
		return [p for p in self.proposals if p.target_kind == TargetKind.OBJECT]

	@property
	def collection_proposals(self) -> list[MergeProposal]:
		return [p for p in self.proposals if p.target_kind == TargetKind.COLLECTION]

	@property
	def scene_proposals(self) -> list[MergeProposal]:
		return [p for p in self.proposals if p.target_kind == TargetKind.SCENE]

	@property
	def unapplicable_conflicts(self) -> int:
		"""
		Conflicts BlenDiff can report but not apply.

		Surfaced in the summary so "ready to apply" is never read as "every
		difference will be reconciled".
		"""
		return sum(len(p.informational_conflicts) for p in self.proposals)

	@property
	def unresolved_conflicts(self) -> int:
		return sum(p.unresolved_count for p in self.proposals)

	def summary(self) -> dict:
		return {
			"total_proposals":    len(self.proposals),
			"conflicting":        len(self.conflicting_proposals),
			"clean":              len(self.clean_proposals),
			"total_conflicts":    self.total_conflicts,
			"unresolved":         self.unresolved_conflicts,
			"auto_resolved":      self.auto_resolved_count,
			"unapplicable":       self.unapplicable_conflicts,
			"ready_to_apply":     self.all_resolved,
		}
