from __future__ import annotations

from dataclasses import dataclass, field
from .diff import PropertyChange


@dataclass
class ParentDiff:
	"""Diff record for object parent/parenting changes."""
	object_name: str
	changes: list[PropertyChange] = field(default_factory=list)

	@property
	def has_changes(self) -> bool:
		return len(self.changes) > 0

	def summary(self) -> str:
		if not self.has_changes:
			return f"{self.object_name}: no parent changes"
		lines = [f"{self.object_name}: {len(self.changes)} parent change(s)"]
		for c in self.changes:
			lines.append(f"  {c.property_path}: {c.old_value!r} → {c.new_value!r}")
		return "\n".join(lines)