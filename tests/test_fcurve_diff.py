from __future__ import annotations

import pytest
from blendiff.diff_engine.fcurve_diff import diff_fcurves, diff_all_fcurves
from blendiff.data_model.fcurve_diff import FCurveDiff
from blendiff.data_model.diff import PropertyChange


# Fixtures 

def _curve(
    data_path="location",
    array_index=0,
    keyframe_count=10,
    frame_start=1.0,
    frame_end=100.0,
    interpolation="BEZIER",
    extrapolation="CONSTANT",
) -> dict:
    return {
        "data_path":      data_path,
        "array_index":    array_index,
        "keyframe_count": keyframe_count,
        "frame_start":    frame_start,
        "frame_end":      frame_end,
        "interpolation":  interpolation,
        "extrapolation":  extrapolation,
    }

def _loc_x(**kw) -> dict:
    return _curve(data_path="location", array_index=0, **kw)

def _loc_y(**kw) -> dict:
    return _curve(data_path="location", array_index=1, **kw)

def _rot_x(**kw) -> dict:
    return _curve(data_path="rotation_euler", array_index=0, **kw)


# diff_fcurves: no changes 

class TestNoChanges:
    def test_both_empty(self):
        assert diff_fcurves("Cube", [], []).changes == []

    def test_identical_single(self):
        c = _loc_x()
        assert diff_fcurves("Cube", [c], [c]).changes == []

    def test_identical_multiple(self):
        curves = [_loc_x(), _loc_y(), _rot_x()]
        assert diff_fcurves("Cube", curves, curves).changes == []

    def test_returns_fcurve_diff(self):
        assert isinstance(diff_fcurves("Cube", [], []), FCurveDiff)

    def test_object_name_set(self):
        assert diff_fcurves("MyObj", [], []).object_name == "MyObj"

    def test_frame_epsilon_no_false_positive(self):
        a = _loc_x(frame_start=1.0)
        b = _loc_x(frame_start=1.0 + 1e-5)
        assert diff_fcurves("Cube", [a], [b]).changes == []


# Structural changes 

class TestStructuralChanges:
    def test_curve_added(self):
        result = diff_fcurves("Cube", [], [_loc_x()])
        assert len(result.changes) == 1
        assert result.changes[0].old_value is None

    def test_curve_added_path(self):
        result = diff_fcurves("Cube", [], [_loc_x()])
        assert "location" in result.changes[0].property_path
        assert "[0]" in result.changes[0].property_path

    def test_curve_added_new_value_is_keyframe_count(self):
        result = diff_fcurves("Cube", [], [_loc_x(keyframe_count=5)])
        assert result.changes[0].new_value == 5

    def test_curve_removed(self):
        result = diff_fcurves("Cube", [_loc_x()], [])
        assert len(result.changes) == 1
        assert result.changes[0].new_value is None

    def test_curve_removed_old_value_is_keyframe_count(self):
        result = diff_fcurves("Cube", [_loc_x(keyframe_count=8)], [])
        assert result.changes[0].old_value == 8

    def test_second_channel_added(self):
        a = [_loc_x()]
        b = [_loc_x(), _loc_y()]
        result = diff_fcurves("Cube", a, b)
        assert any("location" in c.property_path and "[1]" in c.property_path
                   for c in result.changes)


# Property changes 

class TestKeyframeCountChanges:
    def test_keyframe_count_changed(self):
        a = _loc_x(keyframe_count=10)
        b = _loc_x(keyframe_count=20)
        result = diff_fcurves("Cube", [a], [b])
        assert any("keyframe_count" in c.property_path for c in result.changes)

    def test_keyframe_count_values(self):
        a = _loc_x(keyframe_count=10)
        b = _loc_x(keyframe_count=20)
        result = diff_fcurves("Cube", [a], [b])
        c = next(x for x in result.changes if "keyframe_count" in x.property_path)
        assert c.old_value == 10
        assert c.new_value == 20


class TestFrameRangeChanges:
    def test_frame_start_changed(self):
        a = _loc_x(frame_start=1.0)
        b = _loc_x(frame_start=10.0)
        result = diff_fcurves("Cube", [a], [b])
        assert any("frame_start" in c.property_path for c in result.changes)

    def test_frame_start_values(self):
        a = _loc_x(frame_start=1.0)
        b = _loc_x(frame_start=10.0)
        result = diff_fcurves("Cube", [a], [b])
        c = next(x for x in result.changes if "frame_start" in x.property_path)
        assert c.old_value == 1.0
        assert c.new_value == 10.0

    def test_frame_end_changed(self):
        a = _loc_x(frame_end=100.0)
        b = _loc_x(frame_end=250.0)
        result = diff_fcurves("Cube", [a], [b])
        assert any("frame_end" in c.property_path for c in result.changes)

    def test_frame_above_epsilon(self):
        a = _loc_x(frame_start=1.0)
        b = _loc_x(frame_start=1.01)
        result = diff_fcurves("Cube", [a], [b])
        assert any("frame_start" in c.property_path for c in result.changes)


class TestInterpolationChanges:
    def test_interpolation_changed(self):
        a = _loc_x(interpolation="BEZIER")
        b = _loc_x(interpolation="LINEAR")
        result = diff_fcurves("Cube", [a], [b])
        assert any("interpolation" in c.property_path for c in result.changes)

    def test_interpolation_values(self):
        a = _loc_x(interpolation="BEZIER")
        b = _loc_x(interpolation="LINEAR")
        result = diff_fcurves("Cube", [a], [b])
        c = next(x for x in result.changes if "interpolation" in x.property_path)
        assert c.old_value == "BEZIER"
        assert c.new_value == "LINEAR"

    def test_extrapolation_changed(self):
        a = _loc_x(extrapolation="CONSTANT")
        b = _loc_x(extrapolation="LINEAR")
        result = diff_fcurves("Cube", [a], [b])
        assert any("extrapolation" in c.property_path for c in result.changes)


# Multiple channels 

class TestMultipleChannels:
    def test_only_changed_channel_reported(self):
        a = [_loc_x(keyframe_count=10), _loc_y(keyframe_count=10)]
        b = [_loc_x(keyframe_count=10), _loc_y(keyframe_count=20)]
        result = diff_fcurves("Cube", a, b)
        paths = [c.property_path for c in result.changes]
        assert not any("[0]" in p and "location" in p for p in paths)
        assert any("[1]" in p and "location" in p for p in paths)

    def test_multiple_changed_channels(self):
        a = [_loc_x(keyframe_count=10), _rot_x(keyframe_count=5)]
        b = [_loc_x(keyframe_count=20), _rot_x(keyframe_count=10)]
        result = diff_fcurves("Cube", a, b)
        paths = [c.property_path for c in result.changes]
        assert any("location" in p for p in paths)
        assert any("rotation_euler" in p for p in paths)

    def test_unchanged_channels_silent(self):
        a = [_loc_x(), _loc_y()]
        b = [_loc_x(), _loc_y()]
        assert diff_fcurves("Cube", a, b).changes == []


# Custom prefix 

class TestCustomPrefix:
    def test_custom_prefix_applied(self):
        result = diff_fcurves(
            "Cube", [], [_loc_x()], prefix="objects.Cube.fcurves"
        )
        assert all(
            p.startswith("objects.Cube.fcurves")
            for p in [c.property_path for c in result.changes]
        )


# None / empty handling 

class TestNoneHandling:
    def test_changes_are_property_change_instances(self):
        result = diff_fcurves("Cube", [], [_loc_x()])
        for c in result.changes:
            assert isinstance(c, PropertyChange)


# diff_all_fcurves 

class TestDiffAllFCurves:
    def _wrap(self, curves: list) -> dict:
        return {"fcurves": curves}

    def test_no_changes_empty(self):
        objs = {"Cube": self._wrap([])}
        assert diff_all_fcurves(objs, objs) == []

    def test_detects_change(self):
        a = {"Cube": self._wrap([])}
        b = {"Cube": self._wrap([_loc_x()])}
        result = diff_all_fcurves(a, b)
        assert len(result) == 1
        assert result[0].object_name == "Cube"

    def test_skips_objects_only_in_a(self):
        a = {"Cube": self._wrap([]), "Sphere": self._wrap([])}
        b = {"Cube": self._wrap([_loc_x()])}
        names = [r.object_name for r in diff_all_fcurves(a, b)]
        assert "Sphere" not in names

    def test_skips_objects_only_in_b(self):
        a = {"Cube": self._wrap([])}
        b = {"Cube": self._wrap([_loc_x()]), "Sphere": self._wrap([])}
        names = [r.object_name for r in diff_all_fcurves(a, b)]
        assert "Sphere" not in names

    def test_missing_key_treated_as_empty(self):
        a = {"Cube": {}}
        b = {"Cube": {}}
        assert diff_all_fcurves(a, b) == []

    def test_empty_dicts(self):
        assert diff_all_fcurves({}, {}) == []

    def test_result_sorted_by_name(self):
        a = {"Zebra": self._wrap([]), "Apple": self._wrap([])}
        b = {"Zebra": self._wrap([_loc_x()]), "Apple": self._wrap([_loc_x()])}
        result = diff_all_fcurves(a, b)
        assert [r.object_name for r in result] == ["Apple", "Zebra"]

    def test_only_changed_objects_included(self):
        a = {"Cube": self._wrap([_loc_x(keyframe_count=10)]), "Sphere": self._wrap([])}
        b = {"Cube": self._wrap([_loc_x(keyframe_count=20)]), "Sphere": self._wrap([])}
        result = diff_all_fcurves(a, b)
        assert len(result) == 1
        assert result[0].object_name == "Cube"

    def test_returns_fcurve_diff_instances(self):
        a = {"Cube": self._wrap([])}
        b = {"Cube": self._wrap([_loc_x()])}
        assert all(isinstance(r, FCurveDiff) for r in diff_all_fcurves(a, b))


# FCurveDiff.summary 

class TestFCurveDiffSummary:
    def test_no_changes(self):
        assert "no F-curve changes" in FCurveDiff("Cube", []).summary()

    def test_contains_object_name(self):
        assert "Cube" in FCurveDiff("Cube", []).summary()

    def test_shows_property_path(self):
        c = PropertyChange("fcurves[location][0].keyframe_count", 10, 20)
        assert "fcurves[location][0].keyframe_count" in FCurveDiff("Cube", [c]).summary()

    def test_shows_values(self):
        c = PropertyChange("fcurves[location][0].interpolation", "BEZIER", "LINEAR")
        summary = FCurveDiff("Cube", [c]).summary()
        assert "BEZIER" in summary
        assert "LINEAR" in summary


# SceneDiff integration 

class TestSceneDiffIntegration:
    def test_fcurve_diffs_in_has_changes(self):
        from blendiff.data_model.diff import SceneDiff
        diff = SceneDiff(scene_name_a="A", scene_name_b="B")
        assert not diff.has_changes
        diff.fcurve_diffs = [FCurveDiff("Cube", [
            PropertyChange("fcurves[location][0].keyframe_count", 10, 20)
        ])]
        assert diff.has_changes

    def test_fcurve_changes_in_summary(self):
        from blendiff.data_model.diff import SceneDiff
        diff = SceneDiff(scene_name_a="A", scene_name_b="B")
        diff.fcurve_diffs = [FCurveDiff("Cube", [
            PropertyChange("fcurves[location][0].keyframe_count", 10, 20)
        ])]
        assert diff.summary()["fcurve_changes"] == 1