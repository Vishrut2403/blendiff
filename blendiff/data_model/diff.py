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
	property_path: str  # e.g. "transform.location" or "material_slots[0].name"
	old_value: Any
	new_value: Any


@dataclass
class ObjectDiff:
	"""Diff record for a single scene object."""
	name: str
	kind: ChangeKind
	changes: list[PropertyChange] = field(default_factory=list)

	@property
	def is_structural(self) -> bool:
		"""True when the object was added or removed entirely."""
		return self.kind in (ChangeKind.ADDED, ChangeKind.REMOVED)


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
		)

	def summary(self) -> dict[str, int]:
		return {
			"added":               len(self.added_objects),
			"removed":             len(self.removed_objects),
			"modified":            len(self.modified_objects),
			"collection_changes":  len(self.collection_diffs),
			"render_changes":      len(self.render_diff.changes),
			"world_changes":       len(self.world_diff.changes),
			"parent_changes":      len(self.parent_diffs),
			"constraint_changes":  len(self.constraint_diffs),
			"custom_prop_changes": len(self.custom_prop_diffs),
			"fcurve_changes":      len(self.fcurve_diffs),
		}
