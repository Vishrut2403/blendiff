from __future__ import annotations

from ..data_model.diff import PropertyChange
from ..data_model.nla_diff import NLADiff

_FLOAT_EPSILON = 1e-3


def _frames_equal(a: float, b: float) -> bool:
	return abs(a - b) < _FLOAT_EPSILON


def _floats_equal(a: float, b: float) -> bool:
	return abs(a - b) < _FLOAT_EPSILON


def _diff_strip(
	strip_a: dict,
	strip_b: dict,
	prefix: str,
) -> list[PropertyChange]:
	"""Compare two strip dicts and return property changes."""
	changes: list[PropertyChange] = []

	# String / bool properties — exact match
	for key in ("type", "action", "blend_type", "extrapolation",
				"mute", "use_reverse", "use_sync_length"):
		va = strip_a.get(key)
		vb = strip_b.get(key)
		if va != vb:
			changes.append(PropertyChange(f"{prefix}.{key}", va, vb))

	# Float properties — with tolerance
	for key in ("frame_start", "frame_end", "action_frame_start",
				"action_frame_end", "blend_in", "blend_out"):
		va = strip_a.get(key)
		vb = strip_b.get(key)
		if va is None or vb is None:
			if va != vb:
				changes.append(PropertyChange(f"{prefix}.{key}", va, vb))
		elif not _frames_equal(float(va), float(vb)):
			changes.append(PropertyChange(f"{prefix}.{key}", va, vb))

	for key in ("scale", "repeat", "influence"):
		va = strip_a.get(key)
		vb = strip_b.get(key)
		if va is None or vb is None:
			if va != vb:
				changes.append(PropertyChange(f"{prefix}.{key}", va, vb))
		elif not _floats_equal(float(va), float(vb)):
			changes.append(PropertyChange(f"{prefix}.{key}", va, vb))

	return changes


def diff_nla_tracks(
	obj_name: str,
	tracks_a: list[dict],
	tracks_b: list[dict],
	prefix: str = "nla_tracks",
) -> NLADiff:

	changes: list[PropertyChange] = []

	map_a = {t["index"]: t for t in tracks_a}
	map_b = {t["index"]: t for t in tracks_b}
	all_indices = sorted(set(map_a) | set(map_b))

	for idx in all_indices:
		track_slot = f"{prefix}[{idx}]"
		track_a = map_a.get(idx)
		track_b = map_b.get(idx)

		if track_a is None:
			changes.append(PropertyChange(track_slot, None, track_b["name"]))
			continue

		if track_b is None:
			changes.append(PropertyChange(track_slot, track_a["name"], None))
			continue

		# Track name changed
		if track_a["name"] != track_b["name"]:
			changes.append(PropertyChange(
				f"{track_slot}.name", track_a["name"], track_b["name"]
			))

		# Track mute/lock
		if track_a["mute"] != track_b["mute"]:
			changes.append(PropertyChange(
				f"{track_slot}.mute", track_a["mute"], track_b["mute"]
			))
		if track_a["lock"] != track_b["lock"]:
			changes.append(PropertyChange(
				f"{track_slot}.lock", track_a["lock"], track_b["lock"]
			))

		# Strips — keyed by name
		strips_a = {s["name"]: s for s in track_a.get("strips", [])}
		strips_b = {s["name"]: s for s in track_b.get("strips", [])}
		all_strip_names = sorted(set(strips_a) | set(strips_b))

		for sname in all_strip_names:
			strip_slot = f"{track_slot}.strips[{sname}]"
			sa = strips_a.get(sname)
			sb = strips_b.get(sname)

			if sa is None:
				changes.append(PropertyChange(strip_slot, None, sb["action"]))
				continue
			if sb is None:
				changes.append(PropertyChange(strip_slot, sa["action"], None))
				continue

			changes.extend(_diff_strip(sa, sb, strip_slot))

	return NLADiff(object_name=obj_name, changes=changes)


def diff_all_nla(
	objs_a: dict[str, dict],
	objs_b: dict[str, dict],
) -> list[NLADiff]:
	
	results: list[NLADiff] = []

	for name in sorted(set(objs_a) & set(objs_b)):
		diff = diff_nla_tracks(
			obj_name=name,
			tracks_a=objs_a[name].get("nla_tracks", []),
			tracks_b=objs_b[name].get("nla_tracks", []),
		)
		if diff.changes:
			results.append(diff)

	return results