from __future__ import annotations

from ..data_model.paths import escape_name
from ..data_model.diff import PropertyChange
from ..extractor.geometry_hash import comparable as _hashes_comparable

_EPSILON = 1e-4  # tolerance for bounding box float comparison

# Integer properties 
_INT_PROPS = {"vertex_count", "edge_count", "face_count", "loop_count"}

# Float-list properties
_FLOAT_VEC_PROPS = {"bbox_min", "bbox_max"}

# List-of-string properties
_ORDERED_LIST_PROPS = {"uv_layers", "shape_keys", "vertex_groups"}

#: Shape key settings, compared per key and reported per setting.
_SHAPE_KEY_DATA = "shape_key_data"

#: Settings on one shape key, in the order they read naturally in a report.
_SHAPE_KEY_FIELDS = (
	"value",
	"mute",
	"slider_min",
	"slider_max",
	"interpolation",
	"vertex_group",
	"relative_key",
	"points_hash",
)

# Geometry digests, mapped to the property name reported to the user.
#
# The raw key names say "hash", which is an implementation detail; what an
# artist wants to read is which aspect of the mesh moved. Reporting them
# separately is the point — vertex positions changing while topology holds
# steady means a sculpt or tweak, whereas topology changing means the mesh was
# rebuilt.
_HASH_PROPS = {
	"vertex_hash": "vertex_positions",
	"topology_hash": "topology",
	"uv_hash": "uvs",
}


def _vecs_equal(a: list[float], b: list[float]) -> bool:
	if len(a) != len(b):
		return False
	return all(abs(x - y) < _EPSILON for x, y in zip(a, b))



def _diff_shape_keys(
	list_a: list[dict] | None,
	list_b: list[dict] | None,
	prefix: str,
) -> list[PropertyChange]:
	"""
	Compare shape keys by name, one setting at a time.

	By name rather than by position, because reordering keys in the list does
	not change what any of them does, while pairing by index after an
	insertion would report every key below it as changed.

	Keys added or removed are reported once, as the key itself, rather than as
	a change to each of its settings.
	"""
	changes: list[PropertyChange] = []
	by_name_a = {k.get("name"): k for k in list_a or []}
	by_name_b = {k.get("name"): k for k in list_b or []}

	for name in sorted(set(by_name_a) | set(by_name_b)):
		path = f'{prefix}.shape_keys["{escape_name(name)}"]'
		key_a = by_name_a.get(name)
		key_b = by_name_b.get(name)

		if key_a is None:
			changes.append(PropertyChange(path, None, name))
			continue
		if key_b is None:
			changes.append(PropertyChange(path, name, None))
			continue

		for field in _SHAPE_KEY_FIELDS:
			# A field one side never recorded is not a change, the same rule
			# the geometry digests follow.
			if field not in key_a or field not in key_b:
				continue
			val_a, val_b = key_a[field], key_b[field]
			if field == "points_hash":
				if not _hashes_comparable(val_a, val_b):
					continue
				if val_a != val_b:
					changes.append(PropertyChange(f"{path}.shape", val_a, val_b))
				continue
			if isinstance(val_a, float) or isinstance(val_b, float):
				if abs(float(val_a) - float(val_b)) > _EPSILON:
					changes.append(PropertyChange(f"{path}.{field}", val_a, val_b))
				continue
			if val_a != val_b:
				changes.append(PropertyChange(f"{path}.{field}", val_a, val_b))

	return changes


def diff_mesh_data(
	mesh_a: dict | None,
	mesh_b: dict | None,
	prefix: str = "mesh",
) -> list[PropertyChange]:
	"""
	Compare two mesh summary dicts.

	Parameters
	----------
	mesh_a, mesh_b : dict | None
		Plain dicts as produced by extract_mesh_data().
		None means the object had no mesh data in that snapshot.
	prefix : str
		Property path prefix, e.g. "mesh".

	Returns
	-------
	list[PropertyChange]
	"""
	if mesh_a is None and mesh_b is None:
		return []
	if mesh_a is None:
		return [PropertyChange(property_path=prefix, old_value=None, new_value=mesh_b)]
	if mesh_b is None:
		return [PropertyChange(property_path=prefix, old_value=mesh_a, new_value=None)]

	changes: list[PropertyChange] = []
	all_keys = set(mesh_a) | set(mesh_b)

	for key in sorted(all_keys):
		val_a = mesh_a.get(key)
		val_b = mesh_b.get(key)
		path = f"{prefix}.{key}"

		if key == _SHAPE_KEY_DATA:
			# Absent on one side means that snapshot predates shape key
			# settings being captured, not that every key just appeared.
			if key not in mesh_a or key not in mesh_b:
				continue
			changes.extend(_diff_shape_keys(val_a, val_b, prefix))

		elif key in _HASH_PROPS:
			# Only meaningful when both snapshots recorded it. Snapshots taken
			# before geometry hashing existed have no digest, and comparing a
			# digest against its absence would report an edit nobody made.
			if key not in mesh_a or key not in mesh_b:
				continue
			# Digests are only meaningful against one produced the same way.
			# A snapshot from before the hash format changed would otherwise
			# make every mesh in the scene look edited.
			if not _hashes_comparable(val_a, val_b):
				continue
			if val_a != val_b:
				changes.append(PropertyChange(
					property_path=f"{prefix}.{_HASH_PROPS[key]}",
					old_value=val_a,
					new_value=val_b,
				))

		elif key in _FLOAT_VEC_PROPS:
			if not isinstance(val_a, list) or not isinstance(val_b, list):
				if val_a != val_b:
					changes.append(PropertyChange(path, val_a, val_b))
			elif not _vecs_equal(val_a, val_b):
				changes.append(PropertyChange(path, val_a, val_b))

		elif key in _INT_PROPS:
			if val_a != val_b:
				changes.append(PropertyChange(path, val_a, val_b))

		elif key == "shape_keys" and _SHAPE_KEY_DATA in mesh_a and _SHAPE_KEY_DATA in mesh_b:
			# The name list is redundant once both sides carry the full key
			# data: an added key would otherwise be reported twice, once as
			# the list changing and once as the key itself.
			continue

		elif key in _ORDERED_LIST_PROPS:
			set_a = set(val_a) if isinstance(val_a, list) else set()
			set_b = set(val_b) if isinstance(val_b, list) else set()
			if set_a != set_b:
				changes.append(PropertyChange(
					path,
					sorted(set_a),
					sorted(set_b),
				))

		else:
			if val_a != val_b:
				changes.append(PropertyChange(path, val_a, val_b))

	return changes