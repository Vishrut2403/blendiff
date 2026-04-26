import pytest
from blendiff.diff_engine.world_diff import diff_world_data
from blendiff.data_model.diff import PropertyChange, WorldDiff


# Fixtures 

def _base_world() -> dict:
    return {
        "name":                "World",
        "use_nodes":           True,
        "color":               [0.05, 0.05, 0.05],
        "use_ao":              False,
        "ao_factor":           1.0,
        "ao_distance":         10.0,
        "background_color":    [0.051, 0.051, 0.051, 1.0],
        "background_strength": 1.0,
        "hdri_filepath":       None,
        "hdri_strength":       None,
    }


def _hdri_world() -> dict:
    return {
        "name":                "World",
        "use_nodes":           True,
        "color":               [0.05, 0.05, 0.05],
        "use_ao":              False,
        "ao_factor":           1.0,
        "ao_distance":         10.0,
        "background_color":    [1.0, 1.0, 1.0, 1.0],
        "background_strength": 2.0,
        "hdri_filepath":       "//textures/studio.hdr",
        "hdri_strength":       2.0,
    }


# No changes 

class TestNoChanges:
    def test_identical_returns_no_changes(self):
        result = diff_world_data(_base_world(), _base_world())
        assert not result.has_changes

    def test_returns_world_diff_instance(self):
        result = diff_world_data(_base_world(), _base_world())
        assert isinstance(result, WorldDiff)

    def test_hdri_identical(self):
        result = diff_world_data(_hdri_world(), _hdri_world())
        assert not result.has_changes

    def test_float_epsilon_no_false_positive(self):
        a = _base_world()
        b = _base_world()
        b["background_strength"] = 1.0 + 1e-8
        assert not diff_world_data(a, b).has_changes

    def test_color_epsilon_no_false_positive(self):
        a = _base_world()
        b = _base_world()
        b["color"] = [0.05 + 1e-8, 0.05, 0.05]
        assert not diff_world_data(a, b).has_changes


# Name change 

class TestNameChange:
    def test_world_renamed(self):
        a = _base_world()
        b = _base_world()
        b["name"] = "Outdoor"
        result = diff_world_data(a, b)
        assert result.has_changes
        assert "world.name" in [c.property_path for c in result.changes]

    def test_name_old_new_values(self):
        a = _base_world()
        b = _base_world()
        b["name"] = "Studio"
        c = next(x for x in diff_world_data(a, b).changes if x.property_path == "world.name")
        assert c.old_value == "World"
        assert c.new_value == "Studio"


# Background color and strength 

class TestBackground:
    def test_background_strength_change(self):
        a = _base_world()
        b = _base_world()
        b["background_strength"] = 2.0
        result = diff_world_data(a, b)
        assert "world.background_strength" in [c.property_path for c in result.changes]

    def test_background_color_change(self):
        a = _base_world()
        b = _base_world()
        b["background_color"] = [0.5, 0.5, 0.5, 1.0]
        result = diff_world_data(a, b)
        assert "world.background_color" in [c.property_path for c in result.changes]

    def test_background_color_old_new(self):
        a = _base_world()
        b = _base_world()
        b["background_color"] = [1.0, 0.0, 0.0, 1.0]
        c = next(x for x in diff_world_data(a, b).changes if x.property_path == "world.background_color")
        assert c.old_value == [0.051, 0.051, 0.051, 1.0]
        assert c.new_value == [1.0, 0.0, 0.0, 1.0]

    def test_strength_above_epsilon(self):
        a = _base_world()
        b = _base_world()
        b["background_strength"] = 1.5
        result = diff_world_data(a, b)
        assert "world.background_strength" in [c.property_path for c in result.changes]


# HDRI 

class TestHDRI:
    def test_hdri_added(self):
        a = _base_world()
        b = _hdri_world()
        result = diff_world_data(a, b)
        assert result.has_changes
        assert "world.hdri_filepath" in [c.property_path for c in result.changes]

    def test_hdri_removed(self):
        a = _hdri_world()
        b = _base_world()
        result = diff_world_data(a, b)
        assert "world.hdri_filepath" in [c.property_path for c in result.changes]

    def test_hdri_swapped(self):
        a = _hdri_world()
        b = _hdri_world()
        b["hdri_filepath"] = "//textures/outdoor.hdr"
        result = diff_world_data(a, b)
        assert "world.hdri_filepath" in [c.property_path for c in result.changes]

    def test_hdri_filepath_old_new(self):
        a = _hdri_world()
        b = _hdri_world()
        b["hdri_filepath"] = "//textures/outdoor.hdr"
        c = next(x for x in diff_world_data(a, b).changes if x.property_path == "world.hdri_filepath")
        assert c.old_value == "//textures/studio.hdr"
        assert c.new_value == "//textures/outdoor.hdr"

    def test_hdri_strength_change(self):
        a = _hdri_world()
        b = _hdri_world()
        b["hdri_strength"] = 5.0
        result = diff_world_data(a, b)
        assert "world.hdri_strength" in [c.property_path for c in result.changes]


# Ambient occlusion 

class TestAmbientOcclusion:
    def test_ao_toggle(self):
        a = _base_world()
        b = _base_world()
        b["use_ao"] = True
        result = diff_world_data(a, b)
        assert "world.use_ao" in [c.property_path for c in result.changes]

    def test_ao_factor_change(self):
        a = _base_world()
        b = _base_world()
        b["ao_factor"] = 0.5
        result = diff_world_data(a, b)
        assert "world.ao_factor" in [c.property_path for c in result.changes]

    def test_ao_distance_change(self):
        a = _base_world()
        b = _base_world()
        b["ao_distance"] = 5.0
        result = diff_world_data(a, b)
        assert "world.ao_distance" in [c.property_path for c in result.changes]

    def test_ao_factor_epsilon_no_fp(self):
        a = _base_world()
        b = _base_world()
        b["ao_factor"] = 1.0 + 1e-8
        assert not diff_world_data(a, b).has_changes


# use_nodes toggle 

class TestUseNodes:
    def test_use_nodes_toggle(self):
        a = _base_world()
        b = _base_world()
        b["use_nodes"] = False
        result = diff_world_data(a, b)
        assert "world.use_nodes" in [c.property_path for c in result.changes]


# None handling 

class TestNoneHandling:
    def test_both_none_no_changes(self):
        result = diff_world_data(None, None)
        assert not result.has_changes

    def test_a_none_world_added(self):
        result = diff_world_data(None, _base_world())
        assert result.has_changes
        assert result.changes[0].old_value is None
        assert result.changes[0].new_value == "World"

    def test_b_none_world_removed(self):
        result = diff_world_data(_base_world(), None)
        assert result.has_changes
        assert result.changes[0].new_value is None

    def test_returns_world_diff_always(self):
        assert isinstance(diff_world_data(None, None), WorldDiff)
        assert isinstance(diff_world_data(None, _base_world()), WorldDiff)
        assert isinstance(diff_world_data(_base_world(), None), WorldDiff)

    def test_returns_property_change_instances(self):
        a = _base_world()
        b = _base_world()
        b["background_strength"] = 3.0
        for c in diff_world_data(a, b).changes:
            assert isinstance(c, PropertyChange)


# WorldDiff.has_changes and summary 

class TestWorldDiff:
    def test_has_changes_false_when_empty(self):
        result = diff_world_data(_base_world(), _base_world())
        assert not result.has_changes

    def test_has_changes_true_when_changed(self):
        a = _base_world()
        b = _base_world()
        b["background_strength"] = 5.0
        assert diff_world_data(a, b).has_changes

    def test_summary_no_changes(self):
        result = diff_world_data(_base_world(), _base_world())
        assert "no changes" in result.summary()

    def test_summary_lists_changes(self):
        a = _base_world()
        b = _base_world()
        b["background_strength"] = 5.0
        b["use_ao"] = True
        result = diff_world_data(a, b)
        summary = result.summary()
        assert "world.background_strength" in summary
        assert "world.use_ao" in summary
        assert "2 change" in summary

    def test_exact_change_count(self):
        a = _base_world()
        b = _base_world()
        b["background_strength"] = 5.0
        b["use_ao"] = True
        b["hdri_filepath"] = "//sky.hdr"
        assert len(diff_world_data(a, b).changes) == 3


# Edge cases 

class TestEdgeCases:
    def test_empty_dicts(self):
        assert not diff_world_data({}, {}).has_changes

    def test_extra_key_in_b(self):
        a = _base_world()
        b = _base_world()
        b["new_prop"] = "val"
        result = diff_world_data(a, b)
        assert "world.new_prop" in [c.property_path for c in result.changes]