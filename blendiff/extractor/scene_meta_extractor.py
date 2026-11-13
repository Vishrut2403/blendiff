"""
blendiff.extractor.scene_meta_extractor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Timeline markers and unit settings.

Two small parts of a scene that were not captured at all, and whose absence
costs more than their size suggests.

Markers are how shot boundaries and key beats are recorded. Moving one, or
renaming it, changes where an edit lands and produced no diff. A marker can
also bind a camera, which is how camera switching works, so a changed binding
silently changes what renders.

Units decide what every measurement in the file means. Switching a scene from
metric to imperial, or changing the unit scale, leaves every number on screen
reading differently while the geometry is untouched. That is exactly the kind
of change somebody makes by accident and nobody notices until much later.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

#: Unit settings worth recording. Each decides how numbers in the file are
#: read, rather than what the geometry is.
_UNIT_ATTRS = (
	"system",
	"system_rotation",
	"scale_length",
	"use_separate",
	"length_unit",
	"mass_unit",
	"time_unit",
	"temperature_unit",
)


def extract_timeline_markers(scene) -> list[dict]:
	"""
	Every marker in the scene, with the frame and camera it binds.

	Sorted by frame, then name, so two snapshots of the same timeline compare
	equal regardless of the order Blender happens to hold them in.
	"""
	markers = getattr(scene, "timeline_markers", None)
	if not markers:
		return []

	result = []
	for marker in markers:
		try:
			camera = getattr(marker, "camera", None)
			result.append({
				"name": marker.name,
				"frame": int(marker.frame),
				# A marker can switch the active camera. Recorded by name,
				# since a pointer means nothing once the file is reopened.
				"camera": camera.name if camera is not None else None,
			})
		except Exception as exc:
			log.warning("Could not read a timeline marker: %s", exc)

	result.sort(key=lambda entry: (entry["frame"], entry["name"]))
	return result


def extract_unit_settings(scene) -> dict:
	"""
	How this scene interprets numbers.

	Attributes absent on a given Blender are left out rather than recorded as
	None, so a snapshot from a build without one compares as "not captured"
	instead of as a value nobody set.
	"""
	units = getattr(scene, "unit_settings", None)
	if units is None:
		return {}

	recorded = {}
	for attr in _UNIT_ATTRS:
		try:
			value = getattr(units, attr)
		except AttributeError:
			continue
		except Exception as exc:
			log.warning("Could not read unit setting %r: %s", attr, exc)
			continue
		recorded[attr] = (
			round(float(value), 6) if isinstance(value, float)
			else value if isinstance(value, str)
			else bool(value)
		)
	return recorded
