import pytest
from blendiff.diff_engine.camera_light_diff import diff_camera_data, diff_light_data
from blendiff.data_model.diff import PropertyChange


# Fixtures 

def _base_camera() -> dict:
	return {
		"type":         "PERSP",
		"focal_length": 50.0,
		"sensor_width": 36.0,
		"sensor_fit":   "AUTO",
		"clip_start":   0.1,
		"clip_end":     1000.0,
		"ortho_scale":  6.0,
		"shift_x":      0.0,
		"shift_y":      0.0,
		"dof_use":      False,
		"dof_distance": 10.0,
		"dof_fstop":    2.8,
	}


def _base_point_light() -> dict:
	return {
		"type":             "POINT",
		"color":            [1.0, 1.0, 1.0],
		"energy":           1000.0,
		"use_shadow":       True,
		"shadow_soft_size": 0.25,
	}


def _base_spot_light() -> dict:
	return {
		"type":             "SPOT",
		"color":            [1.0, 0.9, 0.8],
		"energy":           500.0,
		"use_shadow":       True,
		"shadow_soft_size": 0.1,
		"spot_size":        0.785,
		"spot_blend":       0.15,
	}


def _base_area_light() -> dict:
	return {
		"type":             "AREA",
		"color":            [1.0, 1.0, 1.0],
		"energy":           200.0,
		"use_shadow":       True,
		"shadow_soft_size": 0.0,
		"shape":            "RECTANGLE",
		"size":             2.0,
		"size_y":           1.0,
	}


def _base_sun_light() -> dict:
	return {
		"type":             "SUN",
		"color":            [1.0, 1.0, 0.9],
		"energy":           5.0,
		"use_shadow":       True,
		"shadow_soft_size": 0.0,
		"angle":            0.00918,  # ~0.53 degrees, solar diameter
	}


# Camera: no changes

class TestCameraNoChanges:
	def test_identical_returns_empty(self):
		assert diff_camera_data(_base_camera(), _base_camera()) == []

	def test_epsilon_no_false_positive_focal(self):
		a = _base_camera()
		b = _base_camera()
		b["focal_length"] = 50.0 + 1e-8
		assert diff_camera_data(a, b) == []

	def test_epsilon_no_false_positive_clip(self):
		a = _base_camera()
		b = _base_camera()
		b["clip_start"] = 0.1 + 1e-8
		assert diff_camera_data(a, b) == []


# Camera: type changes

class TestCameraTypeChange:
	def test_persp_to_ortho(self):
		a = _base_camera()
		b = _base_camera()
		b["type"] = "ORTHO"
		changes = diff_camera_data(a, b)
		paths = [c.property_path for c in changes]
		assert "camera.type" in paths

	def test_old_new_values_correct(self):
		a = _base_camera()
		b = _base_camera()
		b["type"] = "PANO"
		changes = diff_camera_data(a, b)
		c = next(x for x in changes if x.property_path == "camera.type")
		assert c.old_value == "PERSP"
		assert c.new_value == "PANO"


# Camera: focal length

class TestCameraFocalLength:
	def test_focal_length_change(self):
		a = _base_camera()
		b = _base_camera()
		b["focal_length"] = 85.0
		changes = diff_camera_data(a, b)
		paths = [c.property_path for c in changes]
		assert "camera.focal_length" in paths

	def test_focal_length_old_new(self):
		a = _base_camera()
		b = _base_camera()
		b["focal_length"] = 24.0
		changes = diff_camera_data(a, b)
		c = next(x for x in changes if x.property_path == "camera.focal_length")
		assert c.old_value == 50.0
		assert c.new_value == 24.0


# Camera: clip planes

class TestCameraClipPlanes:
	def test_clip_start_change(self):
		a = _base_camera()
		b = _base_camera()
		b["clip_start"] = 0.01
		changes = diff_camera_data(a, b)
		assert "camera.clip_start" in [c.property_path for c in changes]

	def test_clip_end_change(self):
		a = _base_camera()
		b = _base_camera()
		b["clip_end"] = 10000.0
		changes = diff_camera_data(a, b)
		assert "camera.clip_end" in [c.property_path for c in changes]


# Camera: DOF

class TestCameraDOF:
	def test_dof_toggle(self):
		a = _base_camera()
		b = _base_camera()
		b["dof_use"] = True
		changes = diff_camera_data(a, b)
		assert "camera.dof_use" in [c.property_path for c in changes]

	def test_dof_distance_change(self):
		a = _base_camera()
		b = _base_camera()
		b["dof_distance"] = 5.0
		changes = diff_camera_data(a, b)
		assert "camera.dof_distance" in [c.property_path for c in changes]

	def test_dof_fstop_change(self):
		a = _base_camera()
		b = _base_camera()
		b["dof_fstop"] = 1.4
		changes = diff_camera_data(a, b)
		assert "camera.dof_fstop" in [c.property_path for c in changes]


# Camera: shift

class TestCameraShift:
	def test_shift_x_change(self):
		a = _base_camera()
		b = _base_camera()
		b["shift_x"] = 0.1
		changes = diff_camera_data(a, b)
		assert "camera.shift_x" in [c.property_path for c in changes]

	def test_shift_y_change(self):
		a = _base_camera()
		b = _base_camera()
		b["shift_y"] = -0.05
		changes = diff_camera_data(a, b)
		assert "camera.shift_y" in [c.property_path for c in changes]


# Camera: None handling

class TestCameraNoneHandling:
	def test_both_none_returns_empty(self):
		assert diff_camera_data(None, None) == []

	def test_a_none_returns_change(self):
		changes = diff_camera_data(None, _base_camera())
		assert len(changes) == 1
		assert changes[0].old_value is None

	def test_b_none_returns_change(self):
		changes = diff_camera_data(_base_camera(), None)
		assert len(changes) == 1
		assert changes[0].new_value is None

	def test_returns_property_change_instances(self):
		a = _base_camera()
		b = _base_camera()
		b["focal_length"] = 35.0
		for c in diff_camera_data(a, b):
			assert isinstance(c, PropertyChange)


# Camera: custom prefix

class TestCameraPrefix:
	def test_custom_prefix_in_path(self):
		a = _base_camera()
		b = _base_camera()
		b["focal_length"] = 35.0
		changes = diff_camera_data(a, b, prefix="objects.Camera.camera")
		assert changes[0].property_path == "objects.Camera.camera.focal_length"


# Light: no changes

class TestLightNoChanges:
	def test_point_identical(self):
		assert diff_light_data(_base_point_light(), _base_point_light()) == []

	def test_spot_identical(self):
		assert diff_light_data(_base_spot_light(), _base_spot_light()) == []

	def test_color_epsilon_no_false_positive(self):
		a = _base_point_light()
		b = _base_point_light()
		b["color"] = [1.0, 1.0, 1.0 + 1e-8]
		assert diff_light_data(a, b) == []

	def test_energy_epsilon_no_false_positive(self):
		a = _base_point_light()
		b = _base_point_light()
		b["energy"] = 1000.0 + 1e-8
		assert diff_light_data(a, b) == []


# Light: type change

class TestLightTypeChange:
	def test_point_to_spot(self):
		a = _base_point_light()
		b = _base_point_light()
		b["type"] = "SPOT"
		changes = diff_light_data(a, b)
		assert "light.type" in [c.property_path for c in changes]

	def test_type_old_new_values(self):
		a = _base_point_light()
		b = _base_point_light()
		b["type"] = "SUN"
		c = next(x for x in diff_light_data(a, b) if x.property_path == "light.type")
		assert c.old_value == "POINT"
		assert c.new_value == "SUN"


# Light: energy

class TestLightEnergy:
	def test_energy_change(self):
		a = _base_point_light()
		b = _base_point_light()
		b["energy"] = 2000.0
		changes = diff_light_data(a, b)
		assert "light.energy" in [c.property_path for c in changes]


# Light: color

class TestLightColor:
	def test_color_change(self):
		a = _base_point_light()
		b = _base_point_light()
		b["color"] = [1.0, 0.5, 0.0]
		changes = diff_light_data(a, b)
		assert "light.color" in [c.property_path for c in changes]

	def test_color_old_new_values(self):
		a = _base_point_light()
		b = _base_point_light()
		b["color"] = [0.8, 0.8, 1.0]
		c = next(x for x in diff_light_data(a, b) if x.property_path == "light.color")
		assert c.old_value == [1.0, 1.0, 1.0]
		assert c.new_value == [0.8, 0.8, 1.0]


# Light: shadow

class TestLightShadow:
	def test_shadow_toggle(self):
		a = _base_point_light()
		b = _base_point_light()
		b["use_shadow"] = False
		changes = diff_light_data(a, b)
		assert "light.use_shadow" in [c.property_path for c in changes]

	def test_shadow_soft_size_change(self):
		a = _base_point_light()
		b = _base_point_light()
		b["shadow_soft_size"] = 1.0
		changes = diff_light_data(a, b)
		assert "light.shadow_soft_size" in [c.property_path for c in changes]


# Light: spot-specific

class TestSpotLight:
	def test_spot_size_change(self):
		a = _base_spot_light()
		b = _base_spot_light()
		b["spot_size"] = 1.047  # ~60 degrees
		changes = diff_light_data(a, b)
		assert "light.spot_size" in [c.property_path for c in changes]

	def test_spot_blend_change(self):
		a = _base_spot_light()
		b = _base_spot_light()
		b["spot_blend"] = 0.5
		changes = diff_light_data(a, b)
		assert "light.spot_blend" in [c.property_path for c in changes]


# Light: area-specific

class TestAreaLight:
	def test_shape_change(self):
		a = _base_area_light()
		b = _base_area_light()
		b["shape"] = "DISK"
		changes = diff_light_data(a, b)
		assert "light.shape" in [c.property_path for c in changes]

	def test_size_change(self):
		a = _base_area_light()
		b = _base_area_light()
		b["size"] = 4.0
		changes = diff_light_data(a, b)
		assert "light.size" in [c.property_path for c in changes]

	def test_size_y_change(self):
		a = _base_area_light()
		b = _base_area_light()
		b["size_y"] = 3.0
		changes = diff_light_data(a, b)
		assert "light.size_y" in [c.property_path for c in changes]


# Light: sun-specific

class TestSunLight:
	def test_angle_change(self):
		a = _base_sun_light()
		b = _base_sun_light()
		b["angle"] = 0.05
		changes = diff_light_data(a, b)
		assert "light.angle" in [c.property_path for c in changes]


# Light: None handling

class TestLightNoneHandling:
	def test_both_none_returns_empty(self):
		assert diff_light_data(None, None) == []

	def test_a_none(self):
		changes = diff_light_data(None, _base_point_light())
		assert len(changes) == 1
		assert changes[0].old_value is None

	def test_b_none(self):
		changes = diff_light_data(_base_point_light(), None)
		assert len(changes) == 1
		assert changes[0].new_value is None

	def test_returns_property_change_instances(self):
		a = _base_point_light()
		b = _base_point_light()
		b["energy"] = 500.0
		for c in diff_light_data(a, b):
			assert isinstance(c, PropertyChange)


# Light: custom prefix 

class TestLightPrefix:
	def test_custom_prefix_in_path(self):
		a = _base_point_light()
		b = _base_point_light()
		b["energy"] = 500.0
		changes = diff_light_data(a, b, prefix="objects.Sun.light")
		assert changes[0].property_path == "objects.Sun.light.energy"


# Edge cases 

class TestEdgeCases:
	def test_camera_extra_key_in_b(self):
		a = _base_camera()
		b = _base_camera()
		b["new_prop"] = "val"
		changes = diff_camera_data(a, b)
		assert "camera.new_prop" in [c.property_path for c in changes]

	def test_light_extra_key_in_b(self):
		a = _base_point_light()
		b = _base_point_light()
		b["new_prop"] = 42
		changes = diff_light_data(a, b)
		assert "light.new_prop" in [c.property_path for c in changes]

	def test_camera_exact_change_count(self):
		a = _base_camera()
		b = _base_camera()
		b["focal_length"] = 85.0
		b["clip_end"] = 500.0
		assert len(diff_camera_data(a, b)) == 2

	def test_light_exact_change_count(self):
		a = _base_point_light()
		b = _base_point_light()
		b["energy"] = 500.0
		b["use_shadow"] = False
		assert len(diff_light_data(a, b)) == 2
