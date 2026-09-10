"""
blendiff.merge_engine.armature_applier
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Writing rest-bone changes back, which requires edit mode.

Why this is separate
--------------------
Every other property BlenDiff applies is a plain attribute write, dispatched
one at a time through the applier registry. Rest bones are not: a bone's
parent, connection, head, tail and roll exist only on ``EditBone``, reachable
solely while the armature is in edit mode.

That makes them a poor fit for per-property dispatch. Toggling in and out of
edit mode once per property would be slow on a real rig and would push a stack
of undo steps, so an object's rest-bone changes are collected and applied in a
single edit-mode session instead.

Extraction deliberately avoids edit mode — it runs on every diff, must not
disturb the user's mode, and cannot touch a linked rig at all. Applying is the
opposite situation: the user explicitly asked for it, the scene is already
being modified, and it runs from an operator where mode switching is
legitimate. The constraint that rules edit mode out during extraction does not
apply here.

Ordering
--------
Fields are applied per bone in a fixed order because they interact:

1. ``parent`` — everything else is relative to it
2. ``head_local`` / ``tail_local`` — the bone's geometry
3. ``roll`` — orientation about the bone axis
4. ``use_connect`` — **last**, because connecting a bone snaps its head onto
   the parent's tail. Applying it earlier would have the head write fight it,
   and moving the head of a connected bone drags the parent's tail with it.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

log = logging.getLogger(__name__)

#: Rest-bone fields that can only be written in edit mode, mapped to the
#: EditBone attribute they correspond to. The snapshot uses Bone's naming
#: (head_local/tail_local, armature space); EditBone calls the same values
#: head/tail.
EDIT_BONE_FIELDS: dict[str, str] = {
	"parent": "parent",
	"head_local": "head",
	"tail_local": "tail",
	"roll": "roll",
	"use_connect": "use_connect",
}

#: Order fields are applied in. See the module docstring — use_connect last.
_FIELD_ORDER = ("parent", "head_local", "tail_local", "roll", "use_connect")

REST_BONE_PATH = re.compile(
	r'^armature\.bones\["(?P<bone>[^"]+)"\]\.(?P<field>' +
	"|".join(EDIT_BONE_FIELDS) + r")$"
)


def parse_rest_bone_path(property_path: str) -> Optional[tuple[str, str]]:
	"""Return ``(bone_name, field)`` for an edit-mode rest-bone path, else None."""
	match = REST_BONE_PATH.match(property_path)
	if match is None:
		return None
	return match.group("bone"), match.group("field")


def is_rest_bone_edit(property_path: str) -> bool:
	"""True when this path can only be applied inside edit mode."""
	return REST_BONE_PATH.match(property_path) is not None


def can_edit(obj: Any) -> Optional[str]:
	"""
	Check whether this object's rest bones can be edited.

	Returns None when editing is possible, or a human-readable reason why not.
	A reason is far more useful than a failure: "this rig is linked from
	another file" tells the user what to do, whereas a traceback does not.
	"""
	if getattr(obj, "type", None) != "ARMATURE":
		return "not an armature"
	if getattr(obj, "data", None) is None:
		return "armature has no data"
	if getattr(obj, "library", None) is not None:
		return "rig is linked from another file and cannot be edited"
	if getattr(obj, "override_library", None) is not None:
		return "rig is a library override; edit it in the source file"

	try:
		import bpy

		if obj.name not in bpy.context.view_layer.objects:
			return "rig is not in the active view layer"
	except Exception:  # pragma: no cover — defensive
		pass

	return None


class _EditModeSession:
	"""
	Put one armature into edit mode, and put everything back afterwards.

	Mode, active object and selection all belong to the user, who is in the
	middle of their own work. Restoring them is not politeness — leaving an
	artist in edit mode on an object they did not select, with their selection
	replaced, is a genuinely disruptive thing for a merge to do.
	"""

	def __init__(self, obj: Any):
		self._obj = obj
		self._previous_active = None
		self._previous_mode = "OBJECT"
		self._previous_selection: list = []

	def __enter__(self):
		import bpy

		view_layer = bpy.context.view_layer
		self._previous_active = view_layer.objects.active
		if self._previous_active is not None:
			self._previous_mode = getattr(self._previous_active, "mode", "OBJECT")
		self._previous_selection = [
			o for o in view_layer.objects if o.select_get()
		]

		# Edit mode acts on the active object only, so the rig has to become
		# active and selected first.
		if self._previous_mode != "OBJECT":
			bpy.ops.object.mode_set(mode="OBJECT")

		self._obj.select_set(True)
		view_layer.objects.active = self._obj
		bpy.ops.object.mode_set(mode="EDIT")
		return self._obj.data.edit_bones

	def __exit__(self, exc_type, exc, tb):
		import bpy

		try:
			bpy.ops.object.mode_set(mode="OBJECT")
		except Exception as error:  # pragma: no cover — defensive
			log.warning("Could not leave edit mode: %s", error)

		try:
			view_layer = bpy.context.view_layer
			for other in view_layer.objects:
				other.select_set(other in self._previous_selection)
			if self._previous_active is not None:
				view_layer.objects.active = self._previous_active
				if self._previous_mode != "OBJECT":
					bpy.ops.object.mode_set(mode=self._previous_mode)
		except Exception as error:  # pragma: no cover — defensive
			log.warning("Could not restore the previous mode/selection: %s", error)

		return False  # never swallow the caller's exception


def _apply_field(edit_bones: Any, bone: Any, field: str, value: Any) -> None:
	"""Write one field onto an EditBone."""
	attr = EDIT_BONE_FIELDS[field]

	if field == "parent":
		if value is None:
			bone.parent = None
			return
		parent = edit_bones.get(value)
		if parent is None:
			raise ValueError(f"parent bone {value!r} not found")
		if parent is bone:
			raise ValueError("a bone cannot be its own parent")
		bone.parent = parent
		return

	if field in ("head_local", "tail_local"):
		setattr(bone, attr, tuple(value))
		return

	if field == "roll":
		if value is None:
			raise ValueError("roll is unknown in this snapshot")
		setattr(bone, attr, float(value))
		return

	setattr(bone, attr, bool(value))


def apply_rest_bone_changes(obj: Any, changes: list[tuple[str, Any]]) -> list[tuple]:
	"""
	Apply every rest-bone change for one object in a single edit-mode session.

	Parameters
	----------
	obj:
		The armature object.
	changes:
		``(property_path, value)`` pairs, all matching REST_BONE_PATH.

	Returns
	-------
	A list of ``(property_path, status, detail)`` where status is "applied",
	"skipped" or "failed". Every change gets an entry, so the caller can
	account for each one rather than reporting a whole-object outcome.
	"""
	if not changes:
		return []

	blocked = can_edit(obj)
	if blocked is not None:
		return [(path, "skipped", blocked) for path, _value in changes]

	# Group by bone so each is written once, in the interacting-field order.
	by_bone: dict[str, dict[str, Any]] = {}
	for path, value in changes:
		parsed = parse_rest_bone_path(path)
		if parsed is None:  # pragma: no cover — caller filters
			continue
		bone_name, field = parsed
		by_bone.setdefault(bone_name, {})[field] = (path, value)

	outcomes: list[tuple] = []

	try:
		with _EditModeSession(obj) as edit_bones:
			for bone_name, fields in by_bone.items():
				bone = edit_bones.get(bone_name)
				if bone is None:
					for path, _value in fields.values():
						outcomes.append((path, "failed", f"bone {bone_name!r} not found"))
					continue

				for field in _FIELD_ORDER:
					if field not in fields:
						continue
					path, value = fields[field]
					try:
						_apply_field(edit_bones, bone, field, value)
						outcomes.append((path, "applied", ""))
					except Exception as error:
						outcomes.append((path, "failed", str(error)))
	except Exception as error:
		# Entering edit mode failed outright; nothing was written.
		log.warning("Could not edit rest bones on %r: %s", getattr(obj, "name", "?"), error)
		accounted = {path for path, _status, _detail in outcomes}
		return outcomes + [
			(path, "failed", f"could not enter edit mode: {error}")
			for path, _value in changes
			if path not in accounted
		]

	return outcomes
