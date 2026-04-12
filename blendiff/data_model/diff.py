"""
blendiff.data_model.diff
~~~~~~~~~~~~~~~~~~~~~~~~
Dataclasses for the output produced by DiffEngine.

Design decision: diffs are represented as plain dicts inside the
dataclasses (not nested dataclasses) so that they can be trivially
serialised to JSON for reporting or UI display.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ChangeKind(str, Enum):
	ADDED    = "added"
	REMOVED  = "removed"
	MODIFIED = "modified"


@dataclass
class PropertyChange:
	"""A single property that changed on an object."""
	property_path: str      # e.g. "transform.location" or "material_slots[0].name"
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
class SceneDiff:
	"""
	Top-level result returned by DiffEngine.compare().

	Consumers (UI, merge engine, report exporter) should iterate over
	object_diffs and collection_diffs and never inspect the raw scene
	snapshots directly.
	"""
	scene_name_a: str
	scene_name_b: str
	object_diffs: list[ObjectDiff]        = field(default_factory=list)
	collection_diffs: list[CollectionDiff] = field(default_factory=list)
	# Future: animation_diffs, world_diffs, …

	# Convenience aggregators

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
		return bool(self.object_diffs or self.collection_diffs)

	def summary(self) -> dict[str, int]:
		return {
			"added":    len(self.added_objects),
			"removed":  len(self.removed_objects),
			"modified": len(self.modified_objects),
			"collection_changes": len(self.collection_diffs),
		}
