from __future__ import annotations

from ..data_model.diff import PropertyChange
from ..extractor.geometry_hash import comparable as _hashes_comparable

_EPSILON = 1e-4  # tolerance for bounding box float comparison

# Integer properties 
_INT_PROPS = {"vertex_count", "edge_count", "face_count", "loop_count"}

# Float-list properties
_FLOAT_VEC_PROPS = {"bbox_min", "bbox_max"}

# List-of-string properties
_ORDERED_LIST_PROPS = {"uv_layers", "shape_keys", "vertex_groups"}

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

		if key in _HASH_PROPS:
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