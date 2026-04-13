"""
blendiff.diff_engine.material_diff
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pure comparison logic for material node graphs.

Design decisions
----------------
* Stateless — compare_materials() is a pure function.
* No bpy imports — works entirely on plain Python dicts.
* Nodes compared by name (node.name is stable within a session).
* Links compared as sets of (from_node, from_socket, to_node, to_socket)
  tuples — order is irrelevant.
* Float input values use epsilon comparison (same default as DiffEngine).
* Returns a list[PropertyChange] so results slot directly into an ObjectDiff.
"""

from __future__ import annotations

import math
from typing import Any

from ..data_model.diff import PropertyChange

_DEFAULT_EPSILON = 1e-4


def compare_materials(
	mat_a: dict | None,
	mat_b: dict | None,
	material_name: str,
	epsilon: float = _DEFAULT_EPSILON,
) -> list[PropertyChange]:
	"""
	Compare two MaterialSnapshot dicts for one material slot.

	Parameters
	----------
	mat_a, mat_b:
		Dicts matching the MaterialSnapshot schema, or None if the slot
		was empty on that side.
	material_name:
		Used as a prefix in property_path strings, e.g. "Material.001".
	epsilon:
		Tolerance for float comparisons.

	Returns
	-------
	list[PropertyChange]
		Empty list if the materials are identical.
	"""
	prefix = f"material[{material_name}]"

	# Both absent — no diff
	if mat_a is None and mat_b is None:
		return []

	# One side has no node tree
	use_a = (mat_a or {}).get("use_nodes", False)
	use_b = (mat_b or {}).get("use_nodes", False)

	if not use_a and not use_b:
		return []

	if use_a != use_b:
		return [PropertyChange(
			property_path=f"{prefix}.use_nodes",
			old_value=use_a,
			new_value=use_b,
		)]

	# Both have node trees — compare them
	changes: list[PropertyChange] = []

	nodes_a: dict = (mat_a or {}).get("nodes", {})
	nodes_b: dict = (mat_b or {}).get("nodes", {})
	links_a: list = (mat_a or {}).get("links", [])
	links_b: list = (mat_b or {}).get("links", [])

	changes.extend(_diff_nodes(nodes_a, nodes_b, prefix, epsilon))
	changes.extend(_diff_links(links_a, links_b, prefix))

	return changes


# Node diffing

def _diff_nodes(
	nodes_a: dict,
	nodes_b: dict,
	prefix: str,
	epsilon: float,
) -> list[PropertyChange]:
	changes: list[PropertyChange] = []

	keys_a = set(nodes_a)
	keys_b = set(nodes_b)

	# Added nodes
	for name in sorted(keys_b - keys_a):
		node = nodes_b[name]
		changes.append(PropertyChange(
			property_path=f"{prefix}.nodes.{name}",
			old_value=None,
			new_value=node.get("type"),
		))

	# Removed nodes
	for name in sorted(keys_a - keys_b):
		node = nodes_a[name]
		changes.append(PropertyChange(
			property_path=f"{prefix}.nodes.{name}",
			old_value=node.get("type"),
			new_value=None,
		))

	# Modified nodes
	for name in sorted(keys_a & keys_b):
		node_a = nodes_a[name]
		node_b = nodes_b[name]
		changes.extend(_compare_node(node_a, node_b, f"{prefix}.nodes.{name}", epsilon))

	return changes


def _compare_node(
	node_a: dict,
	node_b: dict,
	prefix: str,
	epsilon: float,
) -> list[PropertyChange]:
	changes: list[PropertyChange] = []

	# Node type changed (e.g. someone replaced a Principled BSDF with Emission)
	if node_a.get("type") != node_b.get("type"):
		changes.append(PropertyChange(
			property_path=f"{prefix}.type",
			old_value=node_a.get("type"),
			new_value=node_b.get("type"),
		))
		# If type changed, don't compare inputs — they're meaningless
		return changes

	# Image name changed (TEX_IMAGE nodes)
	if node_a.get("image_name") != node_b.get("image_name"):
		changes.append(PropertyChange(
			property_path=f"{prefix}.image",
			old_value=node_a.get("image_name"),
			new_value=node_b.get("image_name"),
		))

	# Input socket value changes
	inputs_a: dict = node_a.get("inputs", {})
	inputs_b: dict = node_b.get("inputs", {})
	changes.extend(_diff_inputs(inputs_a, inputs_b, prefix, epsilon))

	return changes


def _diff_inputs(
	inputs_a: dict,
	inputs_b: dict,
	prefix: str,
	epsilon: float,
) -> list[PropertyChange]:
	changes: list[PropertyChange] = []

	all_names = sorted(set(inputs_a) | set(inputs_b))

	for name in all_names:
		inp_a = inputs_a.get(name)
		inp_b = inputs_b.get(name)

		if inp_a is None or inp_b is None:
			# Socket added or removed (rare — usually means node type changed)
			if inp_a != inp_b:
				changes.append(PropertyChange(
					property_path=f"{prefix}.inputs.{name}",
					old_value=inp_a.get("value") if inp_a else None,
					new_value=inp_b.get("value") if inp_b else None,
				))
			continue

		val_a = inp_a.get("value")
		val_b = inp_b.get("value")

		if not _values_equal(val_a, val_b, epsilon):
			changes.append(PropertyChange(
				property_path=f"{prefix}.inputs.{name}",
				old_value=val_a,
				new_value=val_b,
			))

	return changes


# Link diffing

def _diff_links(
	links_a: list,
	links_b: list,
	prefix: str,
) -> list[PropertyChange]:
	changes: list[PropertyChange] = []

	def to_tuple(lnk: dict) -> tuple:
		return (
			lnk.get("from_node", ""),
			lnk.get("from_socket", ""),
			lnk.get("to_node", ""),
			lnk.get("to_socket", ""),
		)

	set_a = {to_tuple(lnk) for lnk in links_a}
	set_b = {to_tuple(lnk) for lnk in links_b}

	for lnk in sorted(set_b - set_a):
		changes.append(PropertyChange(
			property_path=f"{prefix}.links",
			old_value=None,
			new_value=f"{lnk[0]}.{lnk[1]} → {lnk[2]}.{lnk[3]}",
		))

	for lnk in sorted(set_a - set_b):
		changes.append(PropertyChange(
			property_path=f"{prefix}.links",
			old_value=f"{lnk[0]}.{lnk[1]} → {lnk[2]}.{lnk[3]}",
			new_value=None,
		))

	return changes


# Value comparison helpers

def _values_equal(a: Any, b: Any, epsilon: float) -> bool:
	"""
	Compare two socket values with epsilon for floats/lists.
	Returns True if values are considered equal.
	"""
	if a is None and b is None:
		return True
	if a is None or b is None:
		return False

	# Both floats
	if isinstance(a, float) and isinstance(b, float):
		return math.isclose(a, b, abs_tol=epsilon)

	# Both lists (RGBA, VECTOR)
	if isinstance(a, list) and isinstance(b, list):
		if len(a) != len(b):
			return False
		return all(_values_equal(x, y, epsilon) for x, y in zip(a, b))

	# Fallback — direct equality
	return a == b
