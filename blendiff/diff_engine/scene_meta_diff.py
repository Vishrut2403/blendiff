"""
blendiff.diff_engine.scene_meta_diff
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Comparing timeline markers and unit settings.

Markers are matched by name rather than by position, for the same reason
shape keys are: inserting one shifts every marker after it, and pairing by
index would report all of them as changed when only one moved.
"""

from __future__ import annotations

from ..data_model.diff import PropertyChange
from ..data_model.paths import escape_name


def diff_timeline_markers(
	markers_a: list | None,
	markers_b: list | None,
	prefix: str = "markers",
) -> list[PropertyChange]:
	"""Compare two marker lists, one marker at a time."""
	first = {m.get("name"): m for m in (markers_a or []) if isinstance(m, dict)}
	second = {m.get("name"): m for m in (markers_b or []) if isinstance(m, dict)}

	changes: list[PropertyChange] = []

	for name in sorted(set(second) - set(first)):
		changes.append(PropertyChange(
			property_path=f'{prefix}["{escape_name(name)}"]',
			old_value=None,
			new_value=second[name].get("frame"),
		))

	for name in sorted(set(first) - set(second)):
		changes.append(PropertyChange(
			property_path=f'{prefix}["{escape_name(name)}"]',
			old_value=first[name].get("frame"),
			new_value=None,
		))

	for name in sorted(set(first) & set(second)):
		path = f'{prefix}["{escape_name(name)}"]'
		for field in ("frame", "camera"):
			# Only when both sides recorded it, the rule every optional field
			# in a snapshot follows.
			if field not in first[name] or field not in second[name]:
				continue
			if first[name][field] != second[name][field]:
				changes.append(PropertyChange(
					property_path=f"{path}.{field}",
					old_value=first[name][field],
					new_value=second[name][field],
				))

	return changes


def diff_unit_settings(
	units_a: dict | None,
	units_b: dict | None,
	prefix: str = "units",
) -> list[PropertyChange]:
	"""Compare unit settings, field by field."""
	first = units_a if isinstance(units_a, dict) else {}
	second = units_b if isinstance(units_b, dict) else {}

	changes: list[PropertyChange] = []
	for key in sorted(set(first) & set(second)):
		if first[key] != second[key]:
			changes.append(PropertyChange(
				property_path=f"{prefix}.{key}",
				old_value=first[key],
				new_value=second[key],
			))
	return changes
