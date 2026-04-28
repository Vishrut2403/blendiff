from __future__ import annotations

from ..data_model.diff import PropertyChange
from ..data_model.parent_diff import ParentDiff


def diff_parent_info(
	obj_name: str,
	parent_a: dict | None,
	parent_b: dict | None,
	prefix: str = "parent",
) -> ParentDiff:
	
	a = parent_a or {"parent_name": None, "parent_type": None, "parent_bone": None}
	b = parent_b or {"parent_name": None, "parent_type": None, "parent_bone": None}

	changes: list[PropertyChange] = []

	for key in ("parent_name", "parent_type", "parent_bone"):
		val_a = a.get(key)
		val_b = b.get(key)
		if val_a != val_b:
			changes.append(PropertyChange(
				property_path=f"{prefix}.{key}",
				old_value=val_a,
				new_value=val_b,
			))

	return ParentDiff(object_name=obj_name, changes=changes)


def diff_all_parents(
	objs_a: dict[str, dict],
	objs_b: dict[str, dict],
) -> list[ParentDiff]:
	results: list[ParentDiff] = []

	for name in sorted(set(objs_a) & set(objs_b)):
		diff = diff_parent_info(
			obj_name=name,
			parent_a=objs_a[name].get("parent"),
			parent_b=objs_b[name].get("parent"),
		)
		if diff.changes:
			results.append(diff)

	return results