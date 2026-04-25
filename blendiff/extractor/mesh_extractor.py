from __future__ import annotations


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

	return {
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

		# Shape keys
		"shape_keys":     (
			[sk.name for sk in mesh.shape_keys.key_blocks]
			if mesh.shape_keys else []
		),

		# Vertex groups (stored on object, not mesh)
		"vertex_groups":  [vg.name for vg in obj.vertex_groups],
	}