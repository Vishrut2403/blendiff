from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _extract_strip(strip: Any) -> dict:
	"""Extract summary data from a single NlaStrip."""
	return {
		"name":          strip.name,
		"type":          strip.type,
		"action":        strip.action.name if strip.action else None,
		"frame_start":   round(strip.frame_start, 4),
		"frame_end":     round(strip.frame_end, 4),
		"action_frame_start": round(strip.action_frame_start, 4),
		"action_frame_end":   round(strip.action_frame_end, 4),
		"scale":         round(strip.scale, 6),
		"repeat":        round(strip.repeat, 6),
		"blend_type":    strip.blend_type,
		"blend_in":      round(strip.blend_in, 4),
		"blend_out":     round(strip.blend_out, 4),
		"influence":     round(strip.influence, 6),
		"mute":          strip.mute,
		"use_reverse":   strip.use_reverse,
		"use_sync_length": getattr(strip, "use_sync_length", False),
		"extrapolation": strip.extrapolation,
	}


def _extract_track(track: Any, track_index: int) -> dict:
	"""Extract summary data from a single NlaTrack."""
	strips = []
	for strip in track.strips:
		try:
			strips.append(_extract_strip(strip))
		except Exception as exc:
			log.debug("Could not extract NLA strip %r: %s", strip.name, exc)
	return {
		"index":  track_index,
		"name":   track.name,
		"mute":   track.mute,
		"lock":   track.lock,
		"strips": strips,
	}


def extract_nla_tracks(obj: Any) -> list[dict]:

	try:
		anim = obj.animation_data
		if anim is None:
			return []
		tracks = anim.nla_tracks
		if not tracks:
			return []
	except Exception as exc:
		log.warning("Could not access NLA tracks for %r: %s", obj.name, exc)
		return []

	result = []
	for i, track in enumerate(tracks):
		try:
			result.append(_extract_track(track, i))
		except Exception as exc:
			log.warning(
				"Failed to extract NLA track %r on %r: %s",
				track.name, obj.name, exc,
			)

	return result
