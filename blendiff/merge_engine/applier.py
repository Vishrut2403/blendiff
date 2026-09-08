"""
blendiff.merge_engine.applier
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Applies a fully-resolved ThreeWayDiff to the active Blender scene.

What changed and why
--------------------
The previous implementation dispatched six property paths through an if/elif
chain and sent everything else to ``log.debug(... skipping)``. It also counted
success per *proposal*, so a merge that wrote nothing at all still reported
"applied 12 proposals". Resolved structural conflicts (``__existence__``) were
filtered out before dispatch and could never take effect at all.

This version:

* dispatches through the shared applier registry, so coverage is data;
* accounts per *property*, distinguishing applied, skipped-unsupported, and
  failed, and names each one;
* actually executes resolved delete/keep decisions;
* orders writes so dependent properties land correctly.

Design rules
------------
* Only called AFTER every conflict in every proposal is resolved.
* Never called automatically — always requires explicit user confirmation.
* One failure never aborts the rest of the merge.
* bpy import is local — module stays importable outside Blender for tests.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from ..data_model.conflict import (
	MergeProposal,
	Resolution,
	TargetKind,
	ThreeWayDiff,
)
from .property_appliers import (
	PATH_ADD_ADD,
	PATH_EXISTENCE,
	PATH_STRUCTURAL,
	apply_property,
	find_applier,
	unsupported_reason,
)

log = logging.getLogger(__name__)

#: Properties applied before all others, lowest number first.
#
# rotation_mode must precede rotation values: Blender reinterprets the rotation
# channels when the mode changes, so writing values first would have them
# converted out from under the merge. The rename goes last so that any error
# raised along the way still names the object the user recognises.
_PRIORITY = {
	"transform.rotation_mode": 0,
	"name": 99,
}
_DEFAULT_PRIORITY = 50


@dataclass
class ChangeOutcome:
	"""One property write and what became of it."""

	target: str
	property_path: str
	detail: str = ""

	def __str__(self) -> str:
		base = f"{self.target}.{self.property_path}"
		return f"{base}: {self.detail}" if self.detail else base


@dataclass
class ApplyResult:
	"""
	Outcome of an ``apply_all`` call, accounted per property.

	Per-property accounting is the point. A summary that counts proposals
	cannot distinguish a merge that wrote everything from one that wrote
	nothing, and the merge UI reported the latter as success.
	"""

	applied: list[ChangeOutcome] = field(default_factory=list)
	skipped: list[ChangeOutcome] = field(default_factory=list)
	failed: list[ChangeOutcome] = field(default_factory=list)
	missing_targets: list[str] = field(default_factory=list)

	@property
	def succeeded(self) -> int:
		return len(self.applied)

	@property
	def failure_count(self) -> int:
		return len(self.failed)

	@property
	def skipped_count(self) -> int:
		return len(self.skipped)

	@property
	def total(self) -> int:
		return len(self.applied) + len(self.skipped) + len(self.failed)

	@property
	def all_succeeded(self) -> bool:
		"""True when nothing failed and nothing was silently left behind."""
		return not self.failed and not self.skipped and not self.missing_targets

	@property
	def errors(self) -> list[str]:
		return [str(outcome) for outcome in self.failed]

	def summary(self) -> dict:
		return {
			"applied": len(self.applied),
			"skipped": len(self.skipped),
			"failed": len(self.failed),
			"missing_targets": len(self.missing_targets),
			"total": self.total,
		}

	def report_line(self) -> str:
		"""One-line summary suitable for an operator report."""
		parts = [f"applied {len(self.applied)}"]
		if self.skipped:
			parts.append(f"{len(self.skipped)} not applicable")
		if self.failed:
			parts.append(f"{len(self.failed)} failed")
		if self.missing_targets:
			parts.append(f"{len(self.missing_targets)} object(s) not found")
		return ", ".join(parts)

	def __repr__(self) -> str:
		return f"ApplyResult({self.report_line()})"


class Applier:
	"""Apply resolved merge proposals to the active Blender scene."""

	def apply_all(self, three_way_diff: ThreeWayDiff, context: Any) -> ApplyResult:
		"""
		Apply every resolved proposal in the ThreeWayDiff.

		Raises
		------
		RuntimeError if any conflict is still unresolved.
		"""
		if not three_way_diff.all_resolved:
			raise RuntimeError(
				f"Cannot apply — {three_way_diff.unresolved_conflicts} "
				f"conflict(s) still unresolved."
			)

		result = ApplyResult()
		for proposal in three_way_diff.proposals:
			try:
				self._apply_proposal(proposal, context, result)
			except Exception as exc:
				# A failure inside one proposal must not abandon the others.
				log.error("Failed to apply proposal for %r: %s", proposal.object_name, exc)
				result.failed.append(ChangeOutcome(proposal.object_name, "*", str(exc)))
		return result

	# Per-proposal application

	def _apply_proposal(
		self,
		proposal: MergeProposal,
		context: Any,
		result: ApplyResult,
	) -> None:
		if proposal.target_kind == TargetKind.OBJECT:
			self._apply_object_proposal(proposal, context, result)
			return

		# Collection and scene targets are reported rather than written:
		# rebuilding a collection hierarchy or rewriting scene settings from a
		# summary risks more than it fixes, and the user is told plainly.
		for path, _ in self._pending_changes(proposal):
			result.skipped.append(ChangeOutcome(
				proposal.object_name,
				path,
				f"{proposal.target_kind.value} changes must be applied manually",
			))

	def _apply_object_proposal(
		self,
		proposal: MergeProposal,
		context: Any,
		result: ApplyResult,
	) -> None:
		name = proposal.object_name
		changes = self._pending_changes(proposal)
		if not changes:
			return

		# Structural decisions come first: deleting the object makes every
		# other write on it meaningless.
		if self._apply_structural(proposal, changes, name, result):
			return

		obj = self._find_object(proposal)
		if obj is None:
			result.missing_targets.append(name)
			log.warning("Object %r not found in scene, skipping %d change(s).",
			            name, len(changes))
			return

		property_changes = [
			(path, value) for path, value in changes
			if path not in (PATH_STRUCTURAL, PATH_EXISTENCE, PATH_ADD_ADD)
		]
		property_changes.sort(key=lambda item: _PRIORITY.get(item[0], _DEFAULT_PRIORITY))

		for path, value in property_changes:
			if find_applier(path) is None:
				result.skipped.append(ChangeOutcome(name, path, unsupported_reason(path)))
				continue
			try:
				apply_property(obj, path, value, context)
				result.applied.append(ChangeOutcome(name, path))
			except Exception as exc:
				log.warning("Failed to apply %r on %r: %s", path, name, exc)
				result.failed.append(ChangeOutcome(name, path, str(exc)))

	def _apply_structural(
		self,
		proposal: MergeProposal,
		changes: list[tuple[str, Any]],
		name: str,
		result: ApplyResult,
	) -> bool:
		"""
		Act on structural decisions. Returns True when the object is gone.

		Both ``__structural__`` (one side added or removed) and
		``__existence__`` (a resolved delete/modify conflict) are handled here.
		The latter used to be filtered out before dispatch, making every
		resolved delete/modify conflict a guaranteed no-op — the single most
		important conflict kind in any merge.
		"""
		for path, value in changes:
			if path not in (PATH_STRUCTURAL, PATH_EXISTENCE):
				continue

			if value in ("removed", "deleted"):
				if self._remove_object(proposal, name):
					result.applied.append(ChangeOutcome(name, path, "removed object"))
				else:
					result.skipped.append(ChangeOutcome(
						name, path, "object already absent",
					))
				return True

			if value == "added":
				# Recreating an object needs its source .blend, which a
				# snapshot does not contain. Say so instead of pretending.
				result.skipped.append(ChangeOutcome(
					name, path,
					"BlenDiff cannot create objects; append it from the source file",
				))
				continue

			if value in ("exists", "modified"):
				# The decision was to keep the object; the property writes that
				# follow carry it out.
				result.applied.append(ChangeOutcome(name, path, "kept object"))

		return False

	def _pending_changes(self, proposal: MergeProposal) -> list[tuple[str, Any]]:
		"""
		Every (path, value) this proposal wants written.

		Resolved conflicts contribute their chosen value; non-conflicting
		changes contribute theirs. AUTO-resolved conflicts are agreements
		between both sides, so their value is applied like any other.
		"""
		changes: list[tuple[str, Any]] = []

		for conflict in proposal.conflicts:
			if conflict.resolution == Resolution.UNRESOLVED:
				# Unapplicable conflicts stay unresolved by design; they are
				# reported, not written.
				continue
			changes.append((conflict.property_path, conflict.resolved_value))

		for nc in proposal.non_conflicting_from_a:
			changes.append((nc.property_path, nc.new_value))
		for nc in proposal.non_conflicting_from_b:
			changes.append((nc.property_path, nc.new_value))

		return changes

	# Object lookup and removal

	def _find_object(self, proposal: MergeProposal) -> Optional[Any]:
		"""
		Locate the live object for a proposal.

		The proposal names the object as it appears in the newer snapshot, but
		the scene being merged into may still use the base-snapshot name when
		the rename came from the other side — so both are tried.
		"""
		import bpy

		obj = bpy.data.objects.get(proposal.object_name)
		if obj is not None:
			return obj
		if proposal.previous_name:
			return bpy.data.objects.get(proposal.previous_name)
		return None

	def _remove_object(self, proposal: MergeProposal, name: str) -> bool:
		import bpy

		obj = self._find_object(proposal)
		if obj is None:
			return False
		bpy.data.objects.remove(obj, do_unlink=True)
		log.info("Removed object %r", name)
		return True
