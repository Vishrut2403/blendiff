import pytest
from blendiff.diff_engine.render_diff import diff_render_settings
from blendiff.data_model.diff import RenderDiff, PropertyChange


# Fixtures

def _base_render() -> dict:
	"""Minimal render dict matching render_extractor output."""
	return {
		"engine": "CYCLES",
		"resolution_x": 1920,
		"resolution_y": 1080,
		"resolution_percentage": 100,
		"filepath": "//renders/",
		"file_format": "PNG",
		"color_mode": "RGBA",
		"color_depth": "8",
		"frame_start": 1,
		"frame_end": 250,
		"frame_step": 1,
		"fps": 24,
		"fps_base": 1.0,
		"display_device": "sRGB",
		"view_transform": "Filmic",
		"look": "None",
		"exposure": 0.0,
		"gamma": 1.0,
		"cycles": {
			"samples": 128,
			"preview_samples": 32,
			"use_denoising": False,
			"denoiser": "OPTIX",
			"device": "GPU",
		},
		"eevee": {
			"taa_render_samples": 64,
			"use_bloom": False,
			"use_ssr": False,
			"shadow_cube_size": "512",
			"shadow_cascade_size": "1024",
		},
	}


# ── No-change tests ────────────────────────────────────────────────────────────

class TestNoChanges:
	def test_identical_dicts_produce_empty_diff(self):
		a = _base_render()
		b = _base_render()
		result = diff_render_settings(a, b)
		assert not result.has_changes
		assert result.changes == []

	def test_returns_render_diff_instance(self):
		result = diff_render_settings(_base_render(), _base_render())
		assert isinstance(result, RenderDiff)

	def test_float_epsilon_no_false_positive(self):
		a = _base_render()
		b = _base_render()
		b["exposure"] = 1e-8  # within epsilon
		result = diff_render_settings(a, b)
		assert not result.has_changes


# ── Engine changes ─────────────────────────────────────────────────────────────

class TestEngineChange:
	def test_engine_switch_detected(self):
		a = _base_render()
		b = _base_render()
		b["engine"] = "BLENDER_EEVEE"
		result = diff_render_settings(a, b)
		assert result.has_changes
		paths = [c.property_path for c in result.changes]
		assert "render.engine" in paths

	def test_engine_change_old_new_values(self):
		a = _base_render()
		b = _base_render()
		b["engine"] = "BLENDER_WORKBENCH"
		result = diff_render_settings(a, b)
		change = next(c for c in result.changes if c.property_path == "render.engine")
		assert change.old_value == "CYCLES"
		assert change.new_value == "BLENDER_WORKBENCH"


# ── Resolution changes ─────────────────────────────────────────────────────────

class TestResolutionChanges:
	def test_resolution_x_change(self):
		a = _base_render()
		b = _base_render()
		b["resolution_x"] = 3840
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.resolution_x" in paths

	def test_resolution_y_change(self):
		a = _base_render()
		b = _base_render()
		b["resolution_y"] = 2160
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.resolution_y" in paths

	def test_resolution_percentage_change(self):
		a = _base_render()
		b = _base_render()
		b["resolution_percentage"] = 50
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.resolution_percentage" in paths

	def test_multiple_resolution_changes_all_captured(self):
		a = _base_render()
		b = _base_render()
		b["resolution_x"] = 3840
		b["resolution_y"] = 2160
		b["resolution_percentage"] = 75
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.resolution_x" in paths
		assert "render.resolution_y" in paths
		assert "render.resolution_percentage" in paths


# ── Frame range changes ────────────────────────────────────────────────────────

class TestFrameRangeChanges:
	def test_frame_end_change(self):
		a = _base_render()
		b = _base_render()
		b["frame_end"] = 500
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.frame_end" in paths

	def test_frame_start_change(self):
		a = _base_render()
		b = _base_render()
		b["frame_start"] = 10
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.frame_start" in paths

	def test_fps_change(self):
		a = _base_render()
		b = _base_render()
		b["fps"] = 30
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.fps" in paths

	def test_fps_base_float_change(self):
		a = _base_render()
		b = _base_render()
		b["fps_base"] = 1.001  # beyond epsilon
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.fps_base" in paths


# ── Output changes ─────────────────────────────────────────────────────────────

class TestOutputChanges:
	def test_file_format_change(self):
		a = _base_render()
		b = _base_render()
		b["file_format"] = "OPEN_EXR"
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.file_format" in paths

	def test_color_mode_change(self):
		a = _base_render()
		b = _base_render()
		b["color_mode"] = "RGB"
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.color_mode" in paths

	def test_filepath_change(self):
		a = _base_render()
		b = _base_render()
		b["filepath"] = "//output/v2/"
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.filepath" in paths


# ── Color management changes ───────────────────────────────────────────────────

class TestColorManagementChanges:
	def test_view_transform_change(self):
		a = _base_render()
		b = _base_render()
		b["view_transform"] = "AgX"
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.view_transform" in paths

	def test_exposure_change_above_epsilon(self):
		a = _base_render()
		b = _base_render()
		b["exposure"] = 0.5
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.exposure" in paths

	def test_gamma_change(self):
		a = _base_render()
		b = _base_render()
		b["gamma"] = 2.2
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.gamma" in paths

	def test_look_change(self):
		a = _base_render()
		b = _base_render()
		b["look"] = "High Contrast"
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.look" in paths


# ── Cycles sub-dict changes ────────────────────────────────────────────────────

class TestCyclesChanges:
	def test_samples_change(self):
		a = _base_render()
		b = _base_render()
		b["cycles"]["samples"] = 512
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.cycles.samples" in paths

	def test_denoising_toggle(self):
		a = _base_render()
		b = _base_render()
		b["cycles"]["use_denoising"] = True
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.cycles.use_denoising" in paths

	def test_device_change(self):
		a = _base_render()
		b = _base_render()
		b["cycles"]["device"] = "CPU"
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.cycles.device" in paths

	def test_denoiser_change(self):
		a = _base_render()
		b = _base_render()
		b["cycles"]["denoiser"] = "OPENIMAGEDENOISE"
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.cycles.denoiser" in paths

	def test_preview_samples_change(self):
		a = _base_render()
		b = _base_render()
		b["cycles"]["preview_samples"] = 8
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.cycles.preview_samples" in paths

	def test_cycles_absent_in_b(self):
		"""If cycles key disappears entirely (unlikely but safe to handle)."""
		a = _base_render()
		b = _base_render()
		b["cycles"] = {}
		result = diff_render_settings(a, b)
		# Every cycles key in A should appear as a change
		assert result.has_changes


# ── EEVEE sub-dict changes ─────────────────────────────────────────────────────

class TestEeveeChanges:
	def test_render_samples_change(self):
		a = _base_render()
		b = _base_render()
		b["eevee"]["taa_render_samples"] = 128
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.eevee.taa_render_samples" in paths

	def test_bloom_toggle(self):
		a = _base_render()
		b = _base_render()
		b["eevee"]["use_bloom"] = True
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.eevee.use_bloom" in paths

	def test_ssr_toggle(self):
		a = _base_render()
		b = _base_render()
		b["eevee"]["use_ssr"] = True
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.eevee.use_ssr" in paths

	def test_shadow_cube_size_change(self):
		a = _base_render()
		b = _base_render()
		b["eevee"]["shadow_cube_size"] = "1024"
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.eevee.shadow_cube_size" in paths


# ── Summary string ─────────────────────────────────────────────────────────────

class TestSummary:
	def test_summary_no_changes(self):
		result = diff_render_settings(_base_render(), _base_render())
		assert "no changes" in result.summary()

	def test_summary_lists_changes(self):
		a = _base_render()
		b = _base_render()
		b["engine"] = "BLENDER_EEVEE"
		b["resolution_x"] = 3840
		result = diff_render_settings(a, b)
		summary = result.summary()
		assert "render.engine" in summary
		assert "render.resolution_x" in summary
		assert "2 change" in summary

	def test_summary_shows_old_and_new(self):
		a = _base_render()
		b = _base_render()
		b["engine"] = "BLENDER_WORKBENCH"
		result = diff_render_settings(a, b)
		summary = result.summary()
		assert "CYCLES" in summary
		assert "BLENDER_WORKBENCH" in summary


# ── Empty / edge cases ─────────────────────────────────────────────────────────

class TestEdgeCases:
	def test_both_empty_dicts(self):
		result = diff_render_settings({}, {})
		assert not result.has_changes

	def test_key_added_in_b(self):
		a = _base_render()
		b = _base_render()
		b["new_prop"] = "value"
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.new_prop" in paths

	def test_key_removed_in_b(self):
		a = _base_render()
		b = _base_render()
		del b["filepath"]
		result = diff_render_settings(a, b)
		paths = [c.property_path for c in result.changes]
		assert "render.filepath" in paths

	def test_change_count_is_exact(self):
		a = _base_render()
		b = _base_render()
		b["engine"] = "BLENDER_EEVEE"
		b["resolution_x"] = 3840
		b["cycles"]["samples"] = 256
		result = diff_render_settings(a, b)
		assert len(result.changes) == 3

	def test_all_changes_are_property_change_instances(self):
		a = _base_render()
		b = _base_render()
		b["engine"] = "BLENDER_EEVEE"
		result = diff_render_settings(a, b)
		for change in result.changes:
			assert isinstance(change, PropertyChange)