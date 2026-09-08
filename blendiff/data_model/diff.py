from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, List


class ChangeKind(str, Enum):
	ADDED = "added"
	REMOVED = "removed"
	MODIFIED = "modified"


@dataclass
class PropertyChange:
	"""A single property that changed on an object."""
	property_path: str
	old_value: Any
	new_value: Any


@dataclass
class ObjectDiff:
	"""
	Diff record for a single scene object.

	``name`` is the object's name in the *newer* snapshot. When the object was
	renamed, ``previous_name`` holds the older name; matching is by persistent
	id, so a rename stays a single modified object instead of collapsing into
	an unrelated add/remove pair that loses every other change.
	"""
	name: str
	kind: ChangeKind
	changes: list[PropertyChange] = field(default_factory=list)
	previous_name: Optional[str] = None

	@property
	def is_structural(self) -> bool:
		"""True when the object was added or removed entirely."""
		return self.kind in (ChangeKind.ADDED, ChangeKind.REMOVED)

	@property
	def was_renamed(self) -> bool:
		"""True when this object carries a different name in each snapshot."""
		return self.previous_name is not None and self.previous_name != self.name

	@property
	def display_name(self) -> str:
		"""Name for reports and panels, showing the rename when there was one."""
		if self.was_renamed:
			return f"{self.previous_name} → {self.name}"
		return self.name


@dataclass
class CollectionDiff:
	"""Diff record for collection hierarchy changes."""
	path: str
	kind: ChangeKind
	changes: list[PropertyChange] = field(default_factory=list)


@dataclass
class RenderDiff:
	"""All changed render-setting properties between two snapshots."""
	changes: List[PropertyChange] = field(default_factory=list)

	@property
	def has_changes(self) -> bool:
		return len(self.changes) > 0

	def summary(self) -> str:
		if not self.has_changes:
			return "Render settings: no changes"
		lines = [f"Render settings: {len(self.changes)} change(s)"]
		for c in self.changes:
			lines.append(f"  {c.property_path}: {c.old_value!r} → {c.new_value!r}")
		return "\n".join(lines)


@dataclass
class WorldDiff:
	"""All changed world/environment properties between two snapshots."""
	changes: List[PropertyChange] = field(default_factory=list)

	@property
	def has_changes(self) -> bool:
		return len(self.changes) > 0

	def summary(self) -> str:
		if not self.has_changes:
			return "World: no changes"
		lines = [f"World: {len(self.changes)} change(s)"]
		for c in self.changes:
			lines.append(f"  {c.property_path}: {c.old_value!r} → {c.new_value!r}")
		return "\n".join(lines)


@dataclass
class SceneDiff:
	"""
	Top-level result returned by DiffEngine.compare().
	"""
	scene_name_a: str
	scene_name_b: str
	object_diffs: list[ObjectDiff] = field(default_factory=list)
	collection_diffs: list[CollectionDiff] = field(default_factory=list)
	render_diff: RenderDiff = field(default_factory=RenderDiff)
	world_diff: WorldDiff = field(default_factory=WorldDiff)
	parent_diffs: list = field(default_factory=list)
	constraint_diffs: list = field(default_factory=list)
	custom_prop_diffs: list = field(default_factory=list)
	fcurve_diffs: list = field(default_factory=list)
	driver_diffs: list = field(default_factory=list)
	nla_diffs: list = field(default_factory=list)
	scene_custom_prop_diff: object = None

	# How objects in A were matched to objects in B, as (name_a, name_b) pairs.
	# The merge engine needs this to key two independent diffs (base→A and
	# base→B) on the common ancestor's names: without it, an object renamed
	# differently on each side would look like two unrelated objects.
	object_pairs: list = field(default_factory=list)

	# Domains captured by only one of the two snapshots. These are deliberately
	# not diffed: an older snapshot predating a feature would otherwise report
	# every value in that domain as newly added. See data_model.schema.
	skipped_domains: list[str] = field(default_factory=list)
	skip_notes: list[str] = field(default_factory=list)

	@property
	def added_objects(self) -> list[ObjectDiff]:
		return [d for d in self.object_diffs if d.kind == ChangeKind.ADDED]

	@property
	def removed_objects(self) -> list[ObjectDiff]:
		return [d for d in self.object_diffs if d.kind == ChangeKind.REMOVED]

	@property
	def modified_objects(self) -> list[ObjectDiff]:
		return [d for d in self.object_diffs if d.kind == ChangeKind.MODIFIED]

	@property
	def renamed_objects(self) -> list[ObjectDiff]:
		"""Objects matched across snapshots by identity but carrying a new name."""
		return [d for d in self.object_diffs if d.was_renamed]

	@property
	def has_skipped_domains(self) -> bool:
		return bool(self.skipped_domains)

	@property
	def has_changes(self) -> bool:
		return bool(
			self.object_diffs
			or self.collection_diffs
			or self.render_diff.has_changes
			or self.world_diff.has_changes
			or self.parent_diffs
			or self.constraint_diffs
			or self.custom_prop_diffs
			or self.fcurve_diffs
			or self.driver_diffs
			or self.nla_diffs
			or (self.scene_custom_prop_diff and self.scene_custom_prop_diff.changes)
		)

	def summary(self) -> dict[str, int]:
		scene_cp_count = (
			len(self.scene_custom_prop_diff.changes)
			if self.scene_custom_prop_diff else 0
		)
		return {
			"added":                    len(self.added_objects),
			"removed":                  len(self.removed_objects),
			"modified":                 len(self.modified_objects),
			"renamed":                  len(self.renamed_objects),
			"collection_changes":       len(self.collection_diffs),
			"render_changes":           len(self.render_diff.changes),
			"world_changes":            len(self.world_diff.changes),
			"parent_changes":           len(self.parent_diffs),
			"constraint_changes":       len(self.constraint_diffs),
			"custom_prop_changes":      len(self.custom_prop_diffs),
			"fcurve_changes":           len(self.fcurve_diffs),
			"driver_changes":           len(self.driver_diffs),
			"nla_changes":              len(self.nla_diffs),
			"scene_custom_prop_changes": scene_cp_count,
			"skipped_domains":          len(self.skipped_domains),
		}