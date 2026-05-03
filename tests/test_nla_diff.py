from __future__ import annotations

import pytest
from blendiff.diff_engine.nla_diff import diff_nla_tracks, diff_all_nla
from blendiff.data_model.nla_diff import NLADiff
from blendiff.data_model.diff import PropertyChange


# Fixtures 

def _strip(
	name="Walk Cycle",
	type="CLIP",
	action="WalkAction",
	frame_start=1.0,
	frame_end=30.0,
	action_frame_start=1.0,
	action_frame_end=30.0,
	scale=1.0,
	repeat=1.0,
	blend_type="REPLACE",
	blend_in=0.0,
	blend_out=0.0,
	influence=1.0,
	mute=False,
	use_reverse=False,
	use_sync_length=False,
	extrapolation="HOLD",
) -> dict:
	return {
		"name": name, "type": type, "action": action,
		"frame_start": frame_start, "frame_end": frame_end,
		"action_frame_start": action_frame_start,
		"action_frame_end": action_frame_end,
		"scale": scale, "repeat": repeat,
		"blend_type": blend_type, "blend_in": blend_in,
		"blend_out": blend_out, "influence": influence,
		"mute": mute, "use_reverse": use_reverse,
		"use_sync_length": use_sync_length,
		"extrapolation": extrapolation,
	}

def _track(index=0, name="NLATrack", mute=False, lock=False, strips=None) -> dict:
	return {
		"index": index,
		"name": name,
		"mute": mute,
		"lock": lock,
		"strips": strips if strips is not None else [_strip()],
	}


# diff_nla_tracks: no changes 

class TestNoChanges:
	def test_both_empty(self):
		assert diff_nla_tracks("Cube", [], []).changes == []

	def test_identical_single_track(self):
		t = _track()
		assert diff_nla_tracks("Cube", [t], [t]).changes == []

	def test_identical_multiple_tracks(self):
		tracks = [_track(0), _track(1, name="NLATrack.001")]
		assert diff_nla_tracks("Cube", tracks, tracks).changes == []

	def test_returns_nla_diff(self):
		assert isinstance(diff_nla_tracks("Cube", [], []), NLADiff)

	def test_object_name_set(self):
		assert diff_nla_tracks("MyObj", [], []).object_name == "MyObj"

	def test_frame_epsilon_no_false_positive(self):
		a = _track(strips=[_strip(frame_start=1.0)])
		b = _track(strips=[_strip(frame_start=1.0 + 1e-5)])
		assert diff_nla_tracks("Cube", [a], [b]).changes == []

	def test_influence_epsilon_no_false_positive(self):
		a = _track(strips=[_strip(influence=1.0)])
		b = _track(strips=[_strip(influence=1.0 + 1e-5)])
		assert diff_nla_tracks("Cube", [a], [b]).changes == []


# Track structural changes 

class TestTrackStructuralChanges:
	def test_track_added(self):
		result = diff_nla_tracks("Cube", [], [_track()])
		assert any(c.old_value is None for c in result.changes)

	def test_track_added_path(self):
		result = diff_nla_tracks("Cube", [], [_track(0)])
		assert result.changes[0].property_path == "nla_tracks[0]"

	def test_track_added_new_value_is_name(self):
		result = diff_nla_tracks("Cube", [], [_track(0, name="MyTrack")])
		assert result.changes[0].new_value == "MyTrack"

	def test_track_removed(self):
		result = diff_nla_tracks("Cube", [_track()], [])
		assert any(c.new_value is None for c in result.changes)

	def test_track_removed_old_value_is_name(self):
		result = diff_nla_tracks("Cube", [_track(0, name="MyTrack")], [])
		assert result.changes[0].old_value == "MyTrack"


# Track property changes 

class TestTrackPropertyChanges:
	def test_track_name_changed(self):
		a = _track(name="Walk")
		b = _track(name="Run")
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("name" in c.property_path for c in result.changes)

	def test_track_mute_changed(self):
		a = _track(mute=False)
		b = _track(mute=True)
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("mute" in c.property_path for c in result.changes)

	def test_track_lock_changed(self):
		a = _track(lock=False)
		b = _track(lock=True)
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("lock" in c.property_path for c in result.changes)


# Strip structural changes 

class TestStripStructuralChanges:
	def test_strip_added(self):
		a = _track(strips=[])
		b = _track(strips=[_strip(name="NewStrip")])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any(c.old_value is None for c in result.changes)

	def test_strip_added_path(self):
		a = _track(strips=[])
		b = _track(strips=[_strip(name="NewStrip")])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("NewStrip" in c.property_path for c in result.changes)

	def test_strip_removed(self):
		a = _track(strips=[_strip(name="OldStrip")])
		b = _track(strips=[])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any(c.new_value is None for c in result.changes)

	def test_second_strip_added(self):
		a = _track(strips=[_strip("Walk")])
		b = _track(strips=[_strip("Walk"), _strip("Run", frame_start=31.0, frame_end=60.0)])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("Run" in c.property_path for c in result.changes)


# Strip property changes 

class TestStripPropertyChanges:
	def test_action_changed(self):
		a = _track(strips=[_strip(action="WalkAction")])
		b = _track(strips=[_strip(action="RunAction")])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("action" in c.property_path for c in result.changes)

	def test_action_values(self):
		a = _track(strips=[_strip(action="WalkAction")])
		b = _track(strips=[_strip(action="RunAction")])
		result = diff_nla_tracks("Cube", [a], [b])
		c = next(x for x in result.changes if "action" in x.property_path)
		assert c.old_value == "WalkAction"
		assert c.new_value == "RunAction"

	def test_frame_start_changed(self):
		a = _track(strips=[_strip(frame_start=1.0)])
		b = _track(strips=[_strip(frame_start=10.0)])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("frame_start" in c.property_path for c in result.changes)

	def test_frame_end_changed(self):
		a = _track(strips=[_strip(frame_end=30.0)])
		b = _track(strips=[_strip(frame_end=60.0)])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("frame_end" in c.property_path for c in result.changes)

	def test_scale_changed(self):
		a = _track(strips=[_strip(scale=1.0)])
		b = _track(strips=[_strip(scale=2.0)])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("scale" in c.property_path for c in result.changes)

	def test_influence_changed(self):
		a = _track(strips=[_strip(influence=1.0)])
		b = _track(strips=[_strip(influence=0.5)])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("influence" in c.property_path for c in result.changes)

	def test_blend_type_changed(self):
		a = _track(strips=[_strip(blend_type="REPLACE")])
		b = _track(strips=[_strip(blend_type="ADD")])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("blend_type" in c.property_path for c in result.changes)

	def test_mute_changed(self):
		a = _track(strips=[_strip(mute=False)])
		b = _track(strips=[_strip(mute=True)])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("mute" in c.property_path for c in result.changes)

	def test_use_reverse_changed(self):
		a = _track(strips=[_strip(use_reverse=False)])
		b = _track(strips=[_strip(use_reverse=True)])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("use_reverse" in c.property_path for c in result.changes)

	def test_extrapolation_changed(self):
		a = _track(strips=[_strip(extrapolation="HOLD")])
		b = _track(strips=[_strip(extrapolation="NOTHING")])
		result = diff_nla_tracks("Cube", [a], [b])
		assert any("extrapolation" in c.property_path for c in result.changes)

	def test_unchanged_strip_silent(self):
		t = _track(strips=[_strip()])
		assert diff_nla_tracks("Cube", [t], [t]).changes == []


# Multiple tracks 

class TestMultipleTracks:
	def test_only_changed_track_reported(self):
		a = [_track(0), _track(1, name="Track2", strips=[_strip("Walk")])]
		b = [_track(0), _track(1, name="Track2", strips=[_strip("Walk", action="RunAction")])]
		result = diff_nla_tracks("Cube", a, b)
		paths = [c.property_path for c in result.changes]
		assert not any("nla_tracks[0]" in p for p in paths)
		assert any("nla_tracks[1]" in p for p in paths)

	def test_unchanged_tracks_silent(self):
		tracks = [_track(0), _track(1, name="Track2")]
		assert diff_nla_tracks("Cube", tracks, tracks).changes == []


# Custom prefix 

class TestCustomPrefix:
	def test_custom_prefix_applied(self):
		result = diff_nla_tracks(
			"Cube", [], [_track()], prefix="objects.Cube.nla_tracks"
		)
		assert all(
			p.startswith("objects.Cube.nla_tracks")
			for p in [c.property_path for c in result.changes]
		)


# diff_all_nla 

class TestDiffAllNLA:
	def _wrap(self, tracks: list) -> dict:
		return {"nla_tracks": tracks}

	def test_no_changes_empty(self):
		objs = {"Cube": self._wrap([])}
		assert diff_all_nla(objs, objs) == []

	def test_detects_change(self):
		a = {"Cube": self._wrap([])}
		b = {"Cube": self._wrap([_track()])}
		result = diff_all_nla(a, b)
		assert len(result) == 1
		assert result[0].object_name == "Cube"

	def test_skips_objects_only_in_a(self):
		a = {"Cube": self._wrap([]), "Sphere": self._wrap([])}
		b = {"Cube": self._wrap([_track()])}
		names = [r.object_name for r in diff_all_nla(a, b)]
		assert "Sphere" not in names

	def test_skips_objects_only_in_b(self):
		a = {"Cube": self._wrap([])}
		b = {"Cube": self._wrap([_track()]), "Sphere": self._wrap([])}
		names = [r.object_name for r in diff_all_nla(a, b)]
		assert "Sphere" not in names

	def test_missing_key_treated_as_empty(self):
		a = {"Cube": {}}
		b = {"Cube": {}}
		assert diff_all_nla(a, b) == []

	def test_empty_dicts(self):
		assert diff_all_nla({}, {}) == []

	def test_result_sorted_by_name(self):
		a = {"Zebra": self._wrap([]), "Apple": self._wrap([])}
		b = {"Zebra": self._wrap([_track()]), "Apple": self._wrap([_track()])}
		result = diff_all_nla(a, b)
		assert [r.object_name for r in result] == ["Apple", "Zebra"]

	def test_only_changed_objects_included(self):
		a = {"Cube": self._wrap([_track(strips=[_strip(influence=1.0)])]),
			 "Sphere": self._wrap([])}
		b = {"Cube": self._wrap([_track(strips=[_strip(influence=0.5)])]),
			 "Sphere": self._wrap([])}
		result = diff_all_nla(a, b)
		assert len(result) == 1
		assert result[0].object_name == "Cube"

	def test_returns_nla_diff_instances(self):
		a = {"Cube": self._wrap([])}
		b = {"Cube": self._wrap([_track()])}
		assert all(isinstance(r, NLADiff) for r in diff_all_nla(a, b))


# NLADiff.summary 

class TestNLADiffSummary:
	def test_no_changes(self):
		assert "no NLA changes" in NLADiff("Cube", []).summary()

	def test_contains_object_name(self):
		assert "Cube" in NLADiff("Cube", []).summary()

	def test_shows_property_path(self):
		c = PropertyChange("nla_tracks[0].strips[Walk].action", "WalkAction", "RunAction")
		assert "nla_tracks[0].strips[Walk].action" in NLADiff("Cube", [c]).summary()

	def test_shows_values(self):
		c = PropertyChange("nla_tracks[0].strips[Walk].influence", 1.0, 0.5)
		summary = NLADiff("Cube", [c]).summary()
		assert "1.0" in summary
		assert "0.5" in summary


# SceneDiff integration 

class TestSceneDiffIntegration:
	def test_nla_diffs_in_has_changes(self):
		from blendiff.data_model.diff import SceneDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		assert not diff.has_changes
		diff.nla_diffs = [NLADiff("Cube", [
			PropertyChange("nla_tracks[0].strips[Walk].action", "WalkAction", "RunAction")
		])]
		assert diff.has_changes

	def test_nla_changes_in_summary(self):
		from blendiff.data_model.diff import SceneDiff
		diff = SceneDiff(scene_name_a="A", scene_name_b="B")
		diff.nla_diffs = [NLADiff("Cube", [
			PropertyChange("nla_tracks[0].strips[Walk].action", "WalkAction", "RunAction")
		])]
		assert diff.summary()["nla_changes"] == 1