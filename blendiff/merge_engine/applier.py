"""
blendiff.merge_engine.applier
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Applies a fully-resolved ThreeWayDiff to the active Blender scene.

Design rules
------------
* Only called AFTER every conflict in every proposal is resolved.
* Never called automatically — always requires explicit user confirmation.
* Each apply_* method is independently catchable so one failure doesn't
  block the rest.
* bpy import is local — module stays importable outside Blender for tests.

Supported operations (from resolved MergeProposals)
----------------------------------------------------
  transform.location      → obj.location
  transform.rotation_euler → obj.rotation_euler
  transform.scale         → obj.scale
  visible                 → obj.hide_viewport
  collection_path         → move object between collections
  material_slots[N].name  → swap material on slot N
  __structural__ added    → not yet implemented (needs source file)
  __structural__ removed  → bpy.data.objects.remove()
"""

from __future__ import annotations

import logging
from typing import Any

from ..data_model.conflict import (
	MergeProposal,
	NonConflictingChange,
	PropertyConflict,
	Resolution,
	ThreeWayDiff,
)

log = logging.getLogger(__name__)


class Applier:
	"""Apply resolved merge proposals to the active Blender scene."""

	def apply_all(
		self,
		three_way_diff: ThreeWayDiff,
		context: Any,
	) -> ApplyResult:
		"""
		Apply every resolved proposal in the ThreeWayDiff.

		Parameters
		----------
		three_way_diff:
			A fully-resolved ThreeWayDiff (all_resolved must be True).
		context:
			bpy.context

		Returns
		-------
		ApplyResult with counts of successes and failures.

		Raises
		------
		RuntimeError if any proposal is still unresolved.
		"""
		if not three_way_diff.all_resolved:
			raise RuntimeError(
				f"Cannot apply — {three_way_diff.unresolved_conflicts} "
				f"conflict(s) still unresolved."
			)

		result = ApplyResult()

		for proposal in three_way_diff.proposals:
			try:
				self._apply_proposal(proposal, context)
				result.succeeded += 1
			except Exception as exc:
				log.error("Failed to apply proposal for %r: %s", proposal.object_name, exc)
				result.failed += 1
				result.errors.append(f"{proposal.object_name}: {exc}")

		return result

	# Per-proposal application

	def _apply_proposal(self, proposal: MergeProposal, context: Any) -> None:
		import bpy

		name = proposal.object_name

		# Gather all changes to apply: resolved conflicts + non-conflicting
		changes_to_apply: list[tuple[str, Any]] = []

		for conflict in proposal.conflicts:
			if conflict.resolution in (Resolution.USE_A, Resolution.USE_B,
									   Resolution.USE_BASE):
				changes_to_apply.append(
					(conflict.property_path, conflict.resolved_value)
				)
			# AUTO-resolved: base value stays, nothing to apply

		for nc in proposal.non_conflicting_from_a:
			changes_to_apply.append((nc.property_path, nc.new_value))

		for nc in proposal.non_conflicting_from_b:
			changes_to_apply.append((nc.property_path, nc.new_value))

		if not changes_to_apply:
			return

		# Handle structural changes first
		structural = [(p, v) for p, v in changes_to_apply if p == "__structural__"]
		property_changes = [(p, v) for p, v in changes_to_apply if p != "__structural__"
							and p != "__existence__" and p != "__add_add__"]

		for _, value in structural:
			if value == "removed":
				self._remove_object(name, context)
				return  # Object is gone, no point applying other changes

		# Get the object for property changes
		obj = bpy.data.objects.get(name)
		if obj is None:
			log.warning("Object %r not found in scene, skipping.", name)
			return

		for prop_path, value in property_changes:
			try:
				self._apply_property(obj, prop_path, value, context)
			except Exception as exc:
				log.warning("Failed to apply %r on %r: %s", prop_path, name, exc)

	# Property application

	def _apply_property(
		self,
		obj: Any,
		prop_path: str,
		value: Any,
		context: Any,
	) -> None:
		"""Dispatch a single property change to the right apply method."""

		if prop_path == "transform.location":
			obj.location = value

		elif prop_path == "transform.rotation_euler":
			obj.rotation_euler = value

		elif prop_path == "transform.scale":
			obj.scale = value

		elif prop_path == "visible":
			obj.hide_viewport = not value

		elif prop_path == "collection_path":
			self._move_to_collection(obj, value, context)

		elif prop_path.startswith("material_slots["):
			self._apply_material_slot(obj, prop_path, value)

		else:
			log.debug("No applier for property %r — skipping.", prop_path)

	# Specific apply helpers

	def _remove_object(self, name: str, context: Any) -> None:
		import bpy
		obj = bpy.data.objects.get(name)
		if obj is not None:
			bpy.data.objects.remove(obj, do_unlink=True)
			log.info("Removed object %r", name)

	def _move_to_collection(
		self,
		obj: Any,
		collection_name: str,
		context: Any,
	) -> None:
		import bpy

		target = bpy.data.collections.get(collection_name)
		if target is None:
			log.warning("Collection %r not found, cannot move %r.", collection_name, obj.name)
			return

		# Unlink from all current collections
		for col in list(obj.users_collection):
			col.objects.unlink(obj)

		# Link to target
		target.objects.link(obj)
		log.info("Moved %r to collection %r", obj.name, collection_name)

	def _apply_material_slot(
		self,
		obj: Any,
		prop_path: str,
		value: Any,
	) -> None:
		import bpy

		# Parse slot index from "material_slots[N].name"
		try:
			idx_start = prop_path.index("[") + 1
			idx_end   = prop_path.index("]")
			slot_idx  = int(prop_path[idx_start:idx_end])
		except (ValueError, IndexError):
			log.warning("Cannot parse slot index from %r", prop_path)
			return

		if slot_idx >= len(obj.material_slots):
			log.warning("Object %r has no slot %d", obj.name, slot_idx)
			return

		if value is None:
			obj.material_slots[slot_idx].material = None
		else:
			mat = bpy.data.materials.get(value)
			if mat is None:
				log.warning("Material %r not found.", value)
				return
			obj.material_slots[slot_idx].material = mat

		log.info("Set material slot %d on %r to %r", slot_idx, obj.name, value)

# Result 

class ApplyResult:
	"""Result of an apply_all() call."""

	def __init__(self):
		self.succeeded: int = 0
		self.failed:    int = 0
		self.errors:    list[str] = []

	@property
	def total(self) -> int:
		return self.succeeded + self.failed

	@property
	def all_succeeded(self) -> bool:
		return self.failed == 0

	def __repr__(self) -> str:
		return (
			f"ApplyResult(succeeded={self.succeeded}, "
			f"failed={self.failed}, errors={self.errors})"
		)
