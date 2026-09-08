"""
blendiff.extractor.identity
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Stable, persistent identity for Blender objects.

The problem
-----------
Diffing keyed on ``obj.name`` cannot survive a rename. "Cube" becoming
"Body_LOW" reads as a deletion plus an unrelated addition, discarding every
property change along with it. Artists rename constantly, so a version control
tool that loses history on rename is not doing its job.

``obj.session_uid`` is unique but, as the name says, only for the session — it
is regenerated on file load, so it cannot link two snapshots.

The approach
------------
Stamp each object with a UUID stored in a custom property, ``_blendiff_id``.
Custom properties are saved inside the .blend, so the id survives file reload,
rename, append and link. Snapshots record it, and the diff engine pairs objects
by id first, falling back to name only for objects that have none.

Deliberate constraints
----------------------
* **Never stamp a linked/library object.** Its data belongs to another file and
  is read-only; attempting a write raises, and even if it succeeded the change
  could not be saved.
* **Stamping is opt-in per call.** Extraction for a read-only diff must not
  dirty the user's file. Only snapshot capture, which the user explicitly asked
  for, stamps objects.
* **The id is hidden from custom-property diffing.** It is BlenDiff bookkeeping,
  not user data, so it is filtered out of the ``custom_props`` domain — see
  ``blendiff.extractor.custom_prop_extractor``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

log = logging.getLogger(__name__)

#: Custom-property key holding an object's persistent BlenDiff identity.
ID_KEY = "_blendiff_id"


def new_id() -> str:
	"""Generate a fresh identity value."""
	return uuid.uuid4().hex


def read_id(obj: Any) -> Optional[str]:
	"""
	Return an object's persistent BlenDiff id, or None if it has none.

	Never raises: an object with no custom-property support, or a malformed
	value written by something else, simply reports no identity.
	"""
	try:
		value = obj.get(ID_KEY)
	except Exception:  # pragma: no cover — defensive against exotic ID types
		return None

	if isinstance(value, str) and value:
		return value
	return None


def is_stampable(obj: Any) -> bool:
	"""
	True when a persistent id can actually be written to this object.

	Linked and library-overridden objects live in another .blend file; writing
	to them either raises or produces a change that can never be saved.
	"""
	try:
		if getattr(obj, "library", None) is not None:
			return False
		if getattr(obj, "override_library", None) is not None:
			return False
		return True
	except Exception:  # pragma: no cover — defensive
		return False


def ensure_id(obj: Any, stamp: bool = False) -> Optional[str]:
	"""
	Return this object's persistent id, creating one when asked.

	Parameters
	----------
	obj:
		A ``bpy.types.Object``.
	stamp:
		When True, write a new id to objects that lack one. Callers performing
		a read-only diff must leave this False so that merely inspecting the
		scene does not mark the .blend as modified.

	Returns
	-------
	The object's id, or None when it has none and could not be given one.
	"""
	existing = read_id(obj)
	if existing:
		return existing

	if not stamp or not is_stampable(obj):
		return None

	value = new_id()
	try:
		obj[ID_KEY] = value
	except Exception as exc:
		log.warning("Could not stamp identity on %r: %s", getattr(obj, "name", "?"), exc)
		return None
	return value


def stamp_scene(scene: Any) -> int:
	"""
	Ensure every stampable object in a scene carries an id.

	Returns the number of objects newly stamped. Called when the user captures
	a snapshot, so that identity exists from the first snapshot onwards.
	"""
	stamped = 0
	for obj in scene.objects:
		if read_id(obj) is None and ensure_id(obj, stamp=True) is not None:
			stamped += 1
	return stamped
