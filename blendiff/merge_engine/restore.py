"""
blendiff.merge_engine.restore
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Putting a scene back the way a snapshot recorded it.

BlenDiff kept history and could say what changed, but offered no way to go
back, which is the thing people install a version control tool for. The
machinery to go back already existed: the merge applier knows how to write
every supported property, with the guards that go with it.

So a restore is not a new way of writing to the scene. It is the ordinary
diff, pointed backwards. Comparing the current scene against the snapshot
makes the snapshot the "after" side, and every change then describes what the
scene would have to become. Those are handed to the same applier a merge uses,
which means a restore inherits the same limits and reports them in the same
words.

What a restore does not do
--------------------------
It does not create or delete objects.

An object in the snapshot but not in the scene was deleted since, and nothing
in a snapshot can rebuild it: geometry is hashed rather than stored. An object
in the scene but not in the snapshot was made since, and removing it is
exactly the kind of thing a tool should not do quietly while claiming to
restore. Both are reported instead, so the user knows the scene is not an
exact match and why.
"""

from __future__ import annotations

import logging
from typing import Any

from ..data_model.conflict import MergeProposal, NonConflictingChange, ThreeWayDiff
from ..data_model.diff import ChangeKind

log = logging.getLogger(__name__)


def build_restore(scene_diff: Any, label: str = "snapshot") -> ThreeWayDiff:
	"""
	Turn a current-scene-to-snapshot diff into something the Applier accepts.

	`scene_diff` must come from comparing the current scene against the
	snapshot, in that order, so that each change's new_value is the value the
	snapshot holds.

	Every change is recorded as non-conflicting: a restore has only one
	source, so there is nothing for the user to decide and nothing that can be
	left unresolved.
	"""
	proposals = []

	for obj_diff in scene_diff.object_diffs:
		if obj_diff.is_structural:
			# Reported by restore_summary rather than acted on.
			continue
		if not obj_diff.changes:
			continue

		proposal = MergeProposal(
			object_name=obj_diff.name,
			previous_name=obj_diff.previous_name,
		)
		for change in obj_diff.changes:
			proposal.non_conflicting_from_a.append(NonConflictingChange(
				property_path=change.property_path,
				base_value=change.old_value,
				new_value=change.new_value,
				source="a",
			))
		proposals.append(proposal)

	return ThreeWayDiff(
		base_label="current scene",
		label_a=label,
		label_b=label,
		proposals=proposals,
	)


def unrestorable_objects(scene_diff: Any) -> dict[str, list[str]]:
	"""
	Objects a restore cannot account for, split by why.

	`missing` exist in the snapshot but not in the scene, so they were deleted
	since and cannot be rebuilt. `extra` exist in the scene but not in the
	snapshot, so they were made since and are deliberately left alone.
	"""
	missing, extra = [], []
	for obj_diff in scene_diff.object_diffs:
		if obj_diff.kind == ChangeKind.ADDED:
			# "Added" relative to the current scene means present in the
			# snapshot and absent now.
			missing.append(obj_diff.name)
		elif obj_diff.kind == ChangeKind.REMOVED:
			extra.append(obj_diff.name)
	return {"missing": sorted(missing), "extra": sorted(extra)}
