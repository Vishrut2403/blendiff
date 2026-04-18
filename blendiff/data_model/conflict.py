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


# Property-level conflict

@dataclass
class PropertyConflict:
	"""
	One property that conflicts between version A and version B.

	base_value  — value in the common ancestor snapshot
	value_a     — value in version A
	value_b     — value in version B
	resolution  — set by the user or auto-resolved
	"""
	property_path: str
	base_value:    Any
	value_a:       Any
	value_b:       Any
	kind:          ConflictKind
	resolution:    Resolution = Resolution.UNRESOLVED

	@property
	def is_resolved(self) -> bool:
		return self.resolution != Resolution.UNRESOLVED

	@property
	def resolved_value(self) -> Any:
		"""Return the value selected by the resolution."""
		if self.resolution == Resolution.USE_A:
			return self.value_a
		if self.resolution == Resolution.USE_B:
			return self.value_b
		if self.resolution in (Resolution.USE_BASE, Resolution.AUTO):
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

	@property
	def has_conflicts(self) -> bool:
		return bool(self.conflicts)

	@property
	def all_resolved(self) -> bool:
		"""True when every conflict has a resolution set."""
		return all(c.is_resolved for c in self.conflicts)

	@property
	def conflict_count(self) -> int:
		return len(self.conflicts)

	@property
	def unresolved_count(self) -> int:
		return sum(1 for c in self.conflicts if not c.is_resolved)

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
		"""Apply the same resolution to every unresolved conflict."""
		for conflict in self.conflicts:
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
			"ready_to_apply":     self.all_resolved,
		}
