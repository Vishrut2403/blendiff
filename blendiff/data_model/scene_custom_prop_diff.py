from __future__ import annotations

from dataclasses import dataclass, field

from .diff import PropertyChange


@dataclass
class SceneCustomPropDiff:
	changes: list[PropertyChange] = field(default_factory=list)

	def summary(self) -> str:
		if not self.changes:
			return "Scene custom properties: no changes"
		lines = ["Scene custom properties:"]
		for c in self.changes:
			lines.append(f"  {c.property_path}: {c.old_value!r} → {c.new_value!r}")
		return "\n".join(lines)