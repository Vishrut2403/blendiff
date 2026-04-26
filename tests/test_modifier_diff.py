import pytest
from blendiff.diff_engine.modifier_diff import diff_modifier_stack
from blendiff.data_model.diff import PropertyChange


# Fixtures

def _subsurf(index=0, name="Subdivision", levels=2, render_levels=2) -> dict:
	return {
		"index": index, "name": name, "type": "SUBSURF",
		"show_viewport": True, "show_render": True, "is_active": True,
		"params": {
			"levels": levels, "render_levels": render_levels,
			"subdivision_type": "CATMULL_CLARK", "use_creases": False,
		},
	}


def _mirror(index=0, name="Mirror") -> dict:
	return {
		"index": index, "name": name, "type": "MIRROR",
		"show_viewport": True, "show_render": True, "is_active": True,
		"params": {
			"use_axis": [True, False, False],
			"use_bisect_axis": [False, False, False],
			"use_clip": True,
			"merge_threshold": 0.001,
		},
	}


def _array(index=0, name="Array", count=3) -> dict:
	return {
		"index": index, "name": name, "type": "ARRAY",
		"show_viewport": True, "show_render": True, "is_active": True,
		"params": {
			"fit_type": "FIXED_COUNT", "count": count,
			"relative_offset": [1.0, 0.0, 0.0],
			"use_relative_offset": True, "use_constant_offset": False,
		},
	}


def _bevel(index=0, name="Bevel") -> dict:
	return {
		"index": index, "name": name, "type": "BEVEL",
		"show_viewport": True, "show_render": True, "is_active": True,
		"params": {
			"width": 0.1, "segments": 2,
			"limit_method": "ANGLE", "miter_outer": "SHARP", "affect": "EDGES",
		},
	}


# No changes

class TestNoChanges:
	def test_empty_stacks(self):
		assert diff_modifier_stack([], []) == []

	def test_identical_single(self):
		assert diff_modifier_stack([_subsurf()], [_subsurf()]) == []

	def test_identical_multiple(self):
		a = [_mirror(0), _subsurf(1)]
		assert diff_modifier_stack(a, a[:]) == []

	def test_float_epsilon_no_fp(self):
		a = [_mirror()]
		b = [_mirror()]
		b[0]["params"]["merge_threshold"] = 0.001 + 1e-7
		assert diff_modifier_stack(a, b) == []


# Added / removed

class TestAddedRemoved:
	def test_modifier_added(self):
		a = []
		b = [_subsurf()]
		changes = diff_modifier_stack(a, b)
		assert len(changes) == 1
		assert changes[0].old_value is None
		assert "SUBSURF" in changes[0].new_value

	def test_modifier_removed(self):
		a = [_subsurf()]
		b = []
		changes = diff_modifier_stack(a, b)
		assert len(changes) == 1
		assert changes[0].new_value is None
		assert "SUBSURF" in changes[0].old_value

	def test_second_modifier_added(self):
		a = [_mirror(0)]
		b = [_mirror(0), _subsurf(1)]
		changes = diff_modifier_stack(a, b)
		paths = [c.property_path for c in changes]
		assert "modifiers[1]" in paths

	def test_first_modifier_removed(self):
		a = [_mirror(0), _subsurf(1)]
		b = [_subsurf(1)]
		changes = diff_modifier_stack(a, b)
		paths = [c.property_path for c in changes]
		assert "modifiers[0]" in paths


# Type change

class TestTypeChange:
	def test_type_changed(self):
		a = [_subsurf()]
		b = [_bevel()]
		changes = diff_modifier_stack(a, b)
		paths = [c.property_path for c in changes]
		assert "modifiers[0].type" in paths

	def test_type_change_old_new(self):
		a = [_subsurf()]
		b = [_bevel()]
		c = next(x for x in diff_modifier_stack(a, b) if x.property_path == "modifiers[0].type")
		assert c.old_value == "SUBSURF"
		assert c.new_value == "BEVEL"

	def test_type_change_skips_param_diff(self):
		"""When type changes, param diffs are noise — only type should be reported."""
		a = [_subsurf()]
		b = [_bevel()]
		changes = diff_modifier_stack(a, b)
		assert len(changes) == 1


# Name change

class TestNameChange:
	def test_modifier_renamed(self):
		a = [_subsurf(name="SubdivisionSurface")]
		b = [_subsurf(name="SubDiv_v2")]
		changes = diff_modifier_stack(a, b)
		paths = [c.property_path for c in changes]
		assert "modifiers[0].name" in paths

	def test_name_old_new(self):
		a = [_subsurf(name="Old")]
		b = [_subsurf(name="New")]
		c = next(x for x in diff_modifier_stack(a, b) if x.property_path == "modifiers[0].name")
		assert c.old_value == "Old"
		assert c.new_value == "New"


# Visibility

class TestVisibility:
	def test_show_viewport_toggle(self):
		a = [_subsurf()]
		b = [_subsurf()]
		b[0]["show_viewport"] = False
		changes = diff_modifier_stack(a, b)
		assert "modifiers[0].show_viewport" in [c.property_path for c in changes]

	def test_show_render_toggle(self):
		a = [_subsurf()]
		b = [_subsurf()]
		b[0]["show_render"] = False
		changes = diff_modifier_stack(a, b)
		assert "modifiers[0].show_render" in [c.property_path for c in changes]


# Param changes

class TestParamChanges:
	def test_subsurf_levels_change(self):
		a = [_subsurf(levels=2)]
		b = [_subsurf(levels=3)]
		changes = diff_modifier_stack(a, b)
		assert "modifiers[0].levels" in [c.property_path for c in changes]

	def test_subsurf_levels_old_new(self):
		a = [_subsurf(levels=2)]
		b = [_subsurf(levels=4)]
		c = next(x for x in diff_modifier_stack(a, b) if x.property_path == "modifiers[0].levels")
		assert c.old_value == 2
		assert c.new_value == 4

	def test_array_count_change(self):
		a = [_array(count=3)]
		b = [_array(count=5)]
		changes = diff_modifier_stack(a, b)
		assert "modifiers[0].count" in [c.property_path for c in changes]

	def test_mirror_axis_change(self):
		a = [_mirror()]
		b = [_mirror()]
		b[0]["params"]["use_axis"] = [True, True, False]
		changes = diff_modifier_stack(a, b)
		assert "modifiers[0].use_axis" in [c.property_path for c in changes]

	def test_bevel_width_change(self):
		a = [_bevel()]
		b = [_bevel()]
		b[0]["params"]["width"] = 0.5
		changes = diff_modifier_stack(a, b)
		assert "modifiers[0].width" in [c.property_path for c in changes]

	def test_bevel_segments_change(self):
		a = [_bevel()]
		b = [_bevel()]
		b[0]["params"]["segments"] = 4
		changes = diff_modifier_stack(a, b)
		assert "modifiers[0].segments" in [c.property_path for c in changes]

	def test_float_param_above_epsilon(self):
		a = [_mirror()]
		b = [_mirror()]
		b[0]["params"]["merge_threshold"] = 0.01
		changes = diff_modifier_stack(a, b)
		assert "modifiers[0].merge_threshold" in [c.property_path for c in changes]

	def test_multiple_param_changes(self):
		a = [_subsurf(levels=2, render_levels=2)]
		b = [_subsurf(levels=3, render_levels=4)]
		changes = diff_modifier_stack(a, b)
		paths = [c.property_path for c in changes]
		assert "modifiers[0].levels" in paths
		assert "modifiers[0].render_levels" in paths


# Stack reorder

class TestReorder:
	def test_reorder_detected(self):
		a = [_mirror(0, "Mirror"), _subsurf(1, "Subdivision")]
		b = [_subsurf(0, "Subdivision"), _mirror(1, "Mirror")]
		# Reorder changes indices so it shows as slot changes
		changes = diff_modifier_stack(a, b)
		assert len(changes) > 0

	def test_pure_reorder_no_other_changes(self):
		"""Same mods, same params, just reordered — order change detected."""
		a = [
			{"index": 0, "name": "Mirror", "type": "MIRROR",
			 "show_viewport": True, "show_render": True, "is_active": True, "params": {}},
			{"index": 1, "name": "Subsurf", "type": "SUBSURF",
			 "show_viewport": True, "show_render": True, "is_active": True, "params": {}},
		]
		b = [
			{"index": 0, "name": "Subsurf", "type": "SUBSURF",
			 "show_viewport": True, "show_render": True, "is_active": True, "params": {}},
			{"index": 1, "name": "Mirror", "type": "MIRROR",
			 "show_viewport": True, "show_render": True, "is_active": True, "params": {}},
		]
		changes = diff_modifier_stack(a, b)
		assert len(changes) > 0


# Multiple modifiers

class TestMultipleModifiers:
	def test_change_in_second_modifier(self):
		a = [_mirror(0), _subsurf(1, levels=2)]
		b = [_mirror(0), _subsurf(1, levels=3)]
		changes = diff_modifier_stack(a, b)
		assert "modifiers[1].levels" in [c.property_path for c in changes]
		assert "modifiers[0]" not in [c.property_path for c in changes]

	def test_changes_in_both_modifiers(self):
		a = [_subsurf(0, levels=2), _array(1, count=3)]
		b = [_subsurf(0, levels=4), _array(1, count=6)]
		changes = diff_modifier_stack(a, b)
		paths = [c.property_path for c in changes]
		assert "modifiers[0].levels" in paths
		assert "modifiers[1].count" in paths

	def test_exact_change_count(self):
		a = [_subsurf(levels=2)]
		b = [_subsurf(levels=3)]
		assert len(diff_modifier_stack(a, b)) == 1


# Custom prefix

class TestPrefix:
	def test_custom_prefix(self):
		a = [_subsurf(levels=2)]
		b = [_subsurf(levels=3)]
		changes = diff_modifier_stack(a, b, prefix="objects.Cube.modifiers")
		assert changes[0].property_path == "objects.Cube.modifiers[0].levels"


# PropertyChange instances

class TestPropertyChangeInstances:
	def test_all_changes_are_property_change(self):
		a = [_subsurf(levels=2)]
		b = [_subsurf(levels=3)]
		for c in diff_modifier_stack(a, b):
			assert isinstance(c, PropertyChange)
