from __future__ import annotations

from dataclasses import dataclass, field

from .diff import PropertyChange


@dataclass
class FCurveInfo:

	data_path: str
	array_index: int
	keyframe_count: int
	frame_start: float
	frame_end: float      
	interpolation: str      
	extrapolation: str


@dataclass
class FCurveDiff:
	"""Diff result for a single object's animation F-curves."""
	object_name: str
	changes: list[PropertyChange] = field(default_factory=list)

	def summary(self) -> str:
		if not self.changes:
			return f"{self.object_name}: no F-curve changes"
		lines = [f"{self.object_name}:"]
		for c in self.changes:
			lines.append(f"  {c.property_path}: {c.old_value!r} → {c.new_value!r}")
		return "\n".join(lines)