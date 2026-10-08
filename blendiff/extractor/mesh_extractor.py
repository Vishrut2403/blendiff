from __future__ import annotations

import logging

from .geometry_hash import EMPTY, extract_geometry_hashes, hash_floats

log = logging.getLogger(__name__)


# Shape keys
#
# Shape keys were recorded as a list of names, so everything that makes a
# shape key do anything was invisible: its value, whether it is muted, its
# slider range, and the shape itself. An animator sliding a key from 0 to 1,
# the single most common thing anyone does with one, produced no diff.
#
# Each key's point positions are hashed rather than stored, for the same
# reason mesh geometry is: a key on a dense mesh holds a position per vertex,
# and the sidecar is meant to stay small enough to live beside the .blend.

def _shape_key_points_hash(key_block) -> str:
	"""Digest of one shape key's point positions."""
	points = getattr(key_block, "data", None)
	if not points:
		return EMPTY
	try:
		buffer = _float_buffer(len(points) * 3)
		points.foreach_get("co", buffer)
		return hash_floats(buffer)
	except Exception as exc:
		log.warning("Could not hash shape key %r: %s", key_block.name, exc)
		return EMPTY


def _float_buffer(size: int):
	"""numpy buffer when available, matching how geometry hashing reads."""
	try:
		import numpy as np

		return np.empty(size, dtype=np.float32)
	except ImportError:
		return [0.0] * size


def extract_shape_key_data(mesh) -> list[dict]:
	"""
	Every shape key on a mesh, with the settings that affect the result.

	Returns an empty list for a mesh with no shape keys, which is also what a
	mesh whose keys were all removed returns, so the two are indistinguishable
	on purpose: in both cases there is nothing to compare.
	"""
	keys = getattr(mesh, "shape_keys", None)
	if keys is None:
		return []

	blocks = []
	for block in keys.key_blocks:
		relative = getattr(block, "relative_key", None)
		blocks.append({
			"name":          block.name,
			"value":         round(float(block.value), 6),
			"mute":          bool(block.mute),
			"slider_min":    round(float(block.slider_min), 6),
			"slider_max":    round(float(block.slider_max), 6),
			"interpolation": block.interpolation,
			"vertex_group":  block.vertex_group or None,
			"relative_key":  relative.name if relative is not None else None,
			"points_hash":   _shape_key_points_hash(block),
		})
	return blocks


def extract_mesh_data(obj) -> dict | None:
	"""
	Parameters
	----------
	obj : bpy.types.Object
		A Blender object with type == 'MESH'.

	Returns
	-------
	dict | None
		Plain Python dict safe to JSON-serialise.
		Returns None if obj.data is None (empty mesh object).
	"""
	mesh = obj.data  # bpy.types.Mesh
	if mesh is None:
		return None

	bb = obj.bound_box  # 8 x 3 floats
	if bb:
		xs = [v[0] for v in bb]
		ys = [v[1] for v in bb]
		zs = [v[2] for v in bb]
		bbox_min = [min(xs), min(ys), min(zs)]
		bbox_max = [max(xs), max(ys), max(zs)]
	else:
		bbox_min = [0.0, 0.0, 0.0]
		bbox_max = [0.0, 0.0, 0.0]

	data = {
		# Topology counts
		"vertex_count":   len(mesh.vertices),
		"edge_count":     len(mesh.edges),
		"face_count":     len(mesh.polygons),
		"loop_count":     len(mesh.loops),      # total corner count

		# Bounding box (local space)
		"bbox_min":       [round(v, 6) for v in bbox_min],
		"bbox_max":       [round(v, 6) for v in bbox_max],

		# UV layers
		"uv_layers":      [uv.name for uv in mesh.uv_layers],

		# Shape keys. The name list stays for snapshots written before the
		# settings below were captured, and because "which keys exist" is a
		# different question from "what are they set to".
		"shape_keys":     (
			[sk.name for sk in mesh.shape_keys.key_blocks]
			if mesh.shape_keys else []
		),
		"shape_key_data": extract_shape_key_data(mesh),
		"shape_keys_relative": (
			bool(mesh.shape_keys.use_relative) if mesh.shape_keys else None
		),

		# Vertex groups (stored on object, not mesh)
		"vertex_groups":  [vg.name for vg in obj.vertex_groups],
	}

	# Counts and a bounding box cannot see a topology-preserving edit: move a
	# vertex inside the existing bounds and every number above is unchanged.
	# The digests below are what make such an edit visible at all.
	data.update(extract_geometry_hashes(mesh))

	return data