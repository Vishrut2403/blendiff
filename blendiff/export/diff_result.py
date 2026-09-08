"""
blendiff.export.diff_result
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Canonical conversion of a SceneDiff into the plain dict everything downstream
consumes: the Blender panels, the HTML exporter and the CLI.

Why this module exists
----------------------
The Blender operator and the CLI each built this dict by hand, and they had
drifted. The CLI's version carried only objects and collections, so
``blendiff compare --output report.html`` produced a report that silently
omitted render settings, world, parenting, constraints, custom properties,
F-curves, drivers and NLA — and a summary line that counted none of them. A
user reading that report would conclude nothing had changed in eight domains
that BlenDiff had in fact diffed.

One conversion, used by every consumer, is the fix: a new diff domain becomes
visible everywhere at once, and the two front-ends cannot drift apart again.
"""

from __future__ import annotations

from typing import Any

from ..data_model.diff import SceneDiff

#: Per-object domains, as (SceneDiff attribute, output key).
_DOMAIN_KEYS = (
	("parent_diffs", "parent_diffs"),
	("constraint_diffs", "constraint_diffs"),
	("custom_prop_diffs", "custom_prop_diffs"),
	("fcurve_diffs", "fcurve_diffs"),
	("driver_diffs", "driver_diffs"),
	("nla_diffs", "nla_diffs"),
)

#: Summary keys rendered into the one-line summary, in display order.
_SUMMARY_LABELS = (
	("added", "Added"),
	("removed", "Removed"),
	("modified", "Modified"),
	("renamed", "Renamed"),
	("collection_changes", "Collections"),
	("render_changes", "Render"),
	("world_changes", "World"),
	("parent_changes", "Parents"),
	("constraint_changes", "Constraints"),
	("custom_prop_changes", "Custom Props"),
	("fcurve_changes", "F-Curves"),
	("driver_changes", "Drivers"),
	("nla_changes", "NLA"),
	("scene_custom_prop_changes", "Scene Props"),
)


def _changes(items) -> list[dict]:
	return [
		{
			"property_path": c.property_path,
			"old_value": c.old_value,
			"new_value": c.new_value,
		}
		for c in items
	]


def summary_line(summary: dict[str, int]) -> str:
	"""
	Render a diff summary as one human-readable line.

	Only non-zero counts appear, so the line stays short for a typical diff
	while still naming every domain that actually changed.
	"""
	parts = [
		f"{label}: {summary[key]}"
		for key, label in _SUMMARY_LABELS
		if summary.get(key)
	]
	return "  ".join(parts) if parts else "No changes detected"


def diff_to_dict(diff: SceneDiff) -> dict[str, Any]:
	"""Convert a SceneDiff into the plain dict used by every consumer."""
	summary = diff.summary()

	result: dict[str, Any] = {
		"summary": summary_line(summary),
		"summary_counts": summary,
		"has_changes": diff.has_changes,
		"scene_name_a": diff.scene_name_a,
		"scene_name_b": diff.scene_name_b,

		# Domains captured by only one snapshot. Carried through so reports can
		# distinguish "unchanged" from "never recorded".
		"skipped_domains": list(diff.skipped_domains),
		"skip_notes": list(diff.skip_notes),

		"added_objects": [o.name for o in diff.added_objects],
		"removed_objects": [o.name for o in diff.removed_objects],
		"renamed_objects": [
			{"previous_name": o.previous_name, "name": o.name}
			for o in diff.renamed_objects
		],
		"modified_objects": [
			{
				"name": o.name,
				"previous_name": o.previous_name,
				"display_name": o.display_name,
				"changes": _changes(o.changes),
			}
			for o in diff.modified_objects
		],
		"collection_diffs": [
			{
				"path": cd.path,
				"kind": cd.kind.value,
				"changes": _changes(cd.changes),
			}
			for cd in diff.collection_diffs
		],
		"render_changes": _changes(diff.render_diff.changes),
		"world_changes": _changes(diff.world_diff.changes),
		"scene_custom_props": _changes(
			diff.scene_custom_prop_diff.changes
			if diff.scene_custom_prop_diff else []
		),
	}

	for attr, key in _DOMAIN_KEYS:
		result[key] = [
			{"object_name": d.object_name, "changes": _changes(d.changes)}
			for d in getattr(diff, attr, []) or []
		]

	return result
