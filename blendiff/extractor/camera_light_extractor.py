from __future__ import annotations
from typing import TYPE_CHECKING


def extract_camera_data(obj) -> dict:
	"""
	Parameters
	----------
	obj : bpy.types.Object
		A Blender object with type == 'CAMERA'.

	Returns
	-------
	dict
		Plain Python dict — safe to JSON-serialise with no mathutils types.
	"""
	cam = obj.data  # bpy.types.Camera

	return {
		"type":         cam.type,           # PERSP, ORTHO, PANO
		"focal_length": cam.lens,           # mm, only meaningful for PERSP
		"sensor_width": cam.sensor_width,   # mm
		"sensor_fit":   cam.sensor_fit,     # AUTO, HORIZONTAL, VERTICAL
		"clip_start":   cam.clip_start,
		"clip_end":     cam.clip_end,
		"ortho_scale":  cam.ortho_scale,    # only meaningful for ORTHO
		"shift_x":      cam.shift_x,
		"shift_y":      cam.shift_y,
		"dof_use":      cam.dof.use_dof,
		"dof_distance": cam.dof.focus_distance,
		"dof_fstop":    cam.dof.aperture_fstop,
	}


def extract_light_data(obj) -> dict:
	"""
	Parameters
	----------
	obj : bpy.types.Object
		A Blender object with type == 'LIGHT'.

	Returns
	-------
	dict
		Plain Python dict — safe to JSON-serialise with no mathutils types.
	"""
	light = obj.data  # bpy.types.Light

	data = {
		"type":            light.type,          # POINT, SUN, SPOT, AREA
		"color":           list(light.color),   # [r, g, b]
		"energy":          light.energy,        # watts
		"use_shadow":      light.use_shadow,
		"shadow_soft_size":light.shadow_soft_size,
	}

	# SPOT-specific
	if light.type == "SPOT":
		data["spot_size"]  = light.spot_size    # radians
		data["spot_blend"] = light.spot_blend

	# AREA-specific
	if light.type == "AREA":
		data["shape"]  = light.shape            # SQUARE, RECTANGLE, DISK, ELLIPSE
		data["size"]   = light.size
		data["size_y"] = light.size_y

	# SUN-specific
	if light.type == "SUN":
		data["angle"] = light.angle             # angular diameter, radians

	return data
