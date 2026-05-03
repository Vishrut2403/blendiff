from __future__ import annotations

from dataclasses import dataclass, field

from .diff import PropertyChange


@dataclass
class NLADiff:
	object_name: str
	changes: list[PropertyChange] = field(default_factory=list)

	def summary(self) -> str:
		if not self.changes:
			return f"{self.object_name}: no NLA changes"
		lines = [f"{self.object_name}:"]
		for c in self.changes:
			lines.append(f"  {c.property_path}: {c.old_value!r} → {c.new_value!r}")
		return "\n".join(lines)
