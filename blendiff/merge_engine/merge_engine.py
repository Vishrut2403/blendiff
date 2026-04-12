"""
blendiff.merge_engine.merge_engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Placeholder for the assisted merge system.

This module defines the *interface* that a real merge engine must
implement.  No business logic is included yet.

Design intent
-------------
The merge engine does NOT apply changes automatically.  It:

1. Accepts a SceneDiff and a set of user-selected ObjectDiff entries.
2. Produces a list of MergeOperation objects describing what would change.
3. The UI presents those operations to the user for confirmation.
4. A separate "apply" step executes the confirmed operations via bpy.

This keeps the system in the "assisted" category — no silent mutations.

Planned MergeOperation types
-----------------------------
- ApplyTransform(object_name, transform)
- ApplyMaterialSlot(object_name, slot_index, material_name)
- AddObject(object_name, source_scene)
- RemoveObject(object_name)
- MoveToCollection(object_name, collection_path)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..data_model.diff import ObjectDiff, SceneDiff


@dataclass
class MergeOperation:
	"""
	A single proposed change.
	Not yet implemented — placeholder only.
	"""
	operation_type: str
	target_name: str
	payload: dict[str, Any]


class MergeEngine:
	"""
	Placeholder.  Interface is defined; implementation is future work.
	"""

	def propose(
		self,
		diff: SceneDiff,
		selected_diffs: list[ObjectDiff],
	) -> list[MergeOperation]:
		"""
		Given a SceneDiff and a user selection, return proposed operations.

		Not implemented yet.
		"""
		raise NotImplementedError(
			"MergeEngine is not yet implemented.  "
			"See docs/architecture.md for the planned design."
		)

	def apply(
		self,
		operations: list[MergeOperation],
		context: Any,
	) -> None:
		"""
		Apply a confirmed list of merge operations to the active scene.

		Not implemented yet.
		"""
		raise NotImplementedError
