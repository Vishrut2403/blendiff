"""
blendiff.merge_engine.property_appliers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Registry mapping diff property paths to the code that writes them back.

Why a registry
--------------
The applier used to be an ``if/elif`` chain covering six property paths, with
everything else falling through to a debug log. Meanwhile the diff engine
reports property paths across sixteen domains. The result was a merge UI that
let a user resolve a modifier or constraint conflict, reported success, and
applied nothing at all — a silent no-op on exactly the operation where silence
is most dangerous.

Making the mapping data rather than control flow fixes that in two ways:

* ``can_apply`` lets the UI and the merge engine tell, *before* the user
  invests effort, which conflicts are actually applicable — so unsupported
  ones are shown as read-only instead of pretending.
* Adding a diff domain without an applier is now visible: the domain simply
  reports ``supported=False`` everywhere, rather than disappearing.

Each entry owns a matcher and a writer. Writers receive the resolved value and
the live ``bpy`` object, and may raise — the caller records the failure per
property rather than aborting the whole merge.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

#: Structural markers the merge engine uses instead of real property paths.
PATH_STRUCTURAL = "__structural__"
PATH_EXISTENCE = "__existence__"
PATH_ADD_ADD = "__add_add__"


@dataclass(frozen=True)
class ApplierEntry:
	"""One applicable property path family."""

	pattern: re.Pattern
	writer: Callable[..., None]
	description: str

	def matches(self, property_path: str) -> bool:
		return bool(self.pattern.match(property_path))


# Attribute maps
#
# Snapshot keys are chosen for readability in reports and do not always match
# the bpy attribute. These maps are the authoritative translation back.

CAMERA_ATTRS: dict[str, str] = {
	"type": "type",
	"focal_length": "lens",
	"sensor_width": "sensor_width",
	"sensor_fit": "sensor_fit",
	"clip_start": "clip_start",
	"clip_end": "clip_end",
	"ortho_scale": "ortho_scale",
	"shift_x": "shift_x",
	"shift_y": "shift_y",
	# Depth of field lives on a nested struct.
	"dof_use": "dof.use_dof",
	"dof_distance": "dof.focus_distance",
	"dof_fstop": "dof.aperture_fstop",
}

LIGHT_ATTRS: dict[str, str] = {
	"type": "type",
	"color": "color",
	"energy": "energy",
	"use_shadow": "use_shadow",
	"shadow_soft_size": "shadow_soft_size",
	"spot_size": "spot_size",
	"spot_blend": "spot_blend",
	"shape": "shape",
	"size": "size",
	"size_y": "size_y",
	"angle": "angle",
}

PARENT_ATTRS: dict[str, str] = {
	"parent_type": "parent_type",
	"parent_bone": "parent_bone",
}


def _set_nested(target: Any, dotted: str, value: Any) -> None:
	"""Assign through a dotted attribute path such as ``dof.focus_distance``."""
	parts = dotted.split(".")
	for part in parts[:-1]:
		target = getattr(target, part)
	setattr(target, parts[-1], value)


# Writers

def _apply_name(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Rename the object.

	Blender enforces unique object names, so a colliding rename would silently
	become "Name.001" and quietly diverge from what the merge promised. Better
	to fail loudly and let the user resolve it.
	"""
	import bpy

	if not isinstance(value, str) or not value:
		raise ValueError(f"Invalid object name: {value!r}")

	existing = bpy.data.objects.get(value)
	if existing is not None and existing is not obj:
		raise ValueError(
			f"Cannot rename to {value!r}: an object with that name already exists."
		)
	obj.name = value


def _apply_location(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.location = tuple(value)


def _apply_rotation_euler(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.rotation_euler = tuple(value)


def _apply_rotation_quaternion(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.rotation_quaternion = tuple(value)


def _apply_rotation_axis_angle(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.rotation_axis_angle = tuple(value)


def _apply_rotation_mode(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.rotation_mode = str(value)


def _apply_scale(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.scale = tuple(value)


def _apply_visible(obj: Any, path: str, value: Any, context: Any) -> None:
	"""``visible`` is the snapshot's inverted view of hide_viewport."""
	obj.hide_viewport = not bool(value)


def _apply_hide_viewport(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.hide_viewport = bool(value)


def _apply_hide_render(obj: Any, path: str, value: Any, context: Any) -> None:
	obj.hide_render = bool(value)


def _apply_collection_path(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Move the object so it belongs to exactly the named collection."""
	_link_to_collections(obj, [value] if value else [])


def _apply_collection_paths(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Set full collection membership, which may be several collections."""
	_link_to_collections(obj, list(value or []))


def _link_to_collections(obj: Any, paths: list[str]) -> None:
	"""
	Relink an object to exactly the given collections.

	Paths are full ("Scene Collection/Props"); the final segment is the
	collection's name, which is what bpy.data.collections is keyed by.
	"""
	import bpy

	targets = []
	for path in paths:
		name = path.rsplit("/", 1)[-1]
		collection = bpy.data.collections.get(name)
		if collection is None:
			# The scene's root collection is not in bpy.data.collections.
			scene = bpy.context.scene
			if scene and scene.collection and scene.collection.name == name:
				collection = scene.collection
		if collection is None:
			raise ValueError(f"Collection {name!r} not found.")
		targets.append(collection)

	if not targets:
		raise ValueError("Refusing to unlink object from every collection.")

	for collection in list(obj.users_collection):
		collection.objects.unlink(obj)
	for collection in targets:
		collection.objects.link(obj)


_SLOT_INDEX = re.compile(r"material_slots\[(\d+)\]")


def _apply_material_slot(obj: Any, path: str, value: Any, context: Any) -> None:
	import bpy

	match = _SLOT_INDEX.match(path)
	if not match:
		raise ValueError(f"Cannot parse material slot index from {path!r}")
	index = int(match.group(1))

	if index >= len(obj.material_slots):
		raise ValueError(f"{obj.name!r} has no material slot {index}.")

	if value is None:
		obj.material_slots[index].material = None
		return

	material = bpy.data.materials.get(value)
	if material is None:
		raise ValueError(f"Material {value!r} not found.")
	obj.material_slots[index].material = material


def _apply_parent(obj: Any, path: str, value: Any, context: Any) -> None:
	"""
	Re-parent, preserving the object's world position.

	Setting ``obj.parent`` alone makes the object jump, because its local
	transform is then interpreted relative to the new parent. Capturing the
	world matrix and restoring it afterwards is what the Object > Parent
	operator does, and is what a user merging a parenting change expects.
	"""
	import bpy

	key = path.split(".", 1)[1]

	if key == "parent_name":
		world = obj.matrix_world.copy()
		if value is None:
			obj.parent = None
		else:
			parent = bpy.data.objects.get(value)
			if parent is None:
				raise ValueError(f"Parent object {value!r} not found.")
			if parent is obj:
				raise ValueError("An object cannot be its own parent.")
			obj.parent = parent
		obj.matrix_world = world
		return

	attr = PARENT_ATTRS.get(key)
	if attr is None:
		raise ValueError(f"Unsupported parent property {key!r}")

	world = obj.matrix_world.copy()
	setattr(obj, attr, value if value is not None else "")
	obj.matrix_world = world


def _apply_custom_prop(obj: Any, path: str, value: Any, context: Any) -> None:
	"""Set or delete a user custom property."""
	key = path.split(".", 1)[1]

	if value is None:
		# None means the property was removed in the winning snapshot.
		if key in obj:
			del obj[key]
		return
	obj[key] = value


def _apply_camera(obj: Any, path: str, value: Any, context: Any) -> None:
	key = path.split(".", 1)[1]
	attr = CAMERA_ATTRS.get(key)
	if attr is None:
		raise ValueError(f"Unsupported camera property {key!r}")
	if obj.data is None:
		raise ValueError(f"{obj.name!r} has no camera data.")
	_set_nested(obj.data, attr, value)


def _apply_light(obj: Any, path: str, value: Any, context: Any) -> None:
	key = path.split(".", 1)[1]
	attr = LIGHT_ATTRS.get(key)
	if attr is None:
		raise ValueError(f"Unsupported light property {key!r}")
	if obj.data is None:
		raise ValueError(f"{obj.name!r} has no light data.")
	_set_nested(obj.data, attr, value)


# Registry
#
# Order matters only in that the first match wins; patterns are disjoint.

REGISTRY: tuple[ApplierEntry, ...] = (
	ApplierEntry(re.compile(r"^name$"), _apply_name, "Object name"),
	ApplierEntry(re.compile(r"^transform\.location$"), _apply_location, "Location"),
	ApplierEntry(re.compile(r"^transform\.rotation_euler$"), _apply_rotation_euler, "Euler rotation"),
	ApplierEntry(re.compile(r"^transform\.rotation_quaternion$"), _apply_rotation_quaternion, "Quaternion rotation"),
	ApplierEntry(re.compile(r"^transform\.rotation_axis_angle$"), _apply_rotation_axis_angle, "Axis-angle rotation"),
	ApplierEntry(re.compile(r"^transform\.rotation_mode$"), _apply_rotation_mode, "Rotation mode"),
	ApplierEntry(re.compile(r"^transform\.scale$"), _apply_scale, "Scale"),
	ApplierEntry(re.compile(r"^visible$"), _apply_visible, "Viewport visibility"),
	ApplierEntry(re.compile(r"^hide_viewport$"), _apply_hide_viewport, "Viewport visibility"),
	ApplierEntry(re.compile(r"^hide_render$"), _apply_hide_render, "Render visibility"),
	ApplierEntry(re.compile(r"^collection_path$"), _apply_collection_path, "Collection"),
	ApplierEntry(re.compile(r"^collection_paths$"), _apply_collection_paths, "Collection membership"),
	ApplierEntry(re.compile(r"^material_slots\[\d+\](\.name)?$"), _apply_material_slot, "Material slot"),
	ApplierEntry(re.compile(r"^parent\.(parent_name|parent_type|parent_bone)$"), _apply_parent, "Parenting"),
	ApplierEntry(re.compile(r"^custom_props\.[^.]+$"), _apply_custom_prop, "Custom property"),
	ApplierEntry(re.compile(r"^camera\.[^.]+$"), _apply_camera, "Camera data"),
	ApplierEntry(re.compile(r"^light\.[^.]+$"), _apply_light, "Light data"),
)


# Paths that are genuinely not applicable, with the reason shown to the user.
# Being explicit here is the point: an unlisted, unmatched path is a gap in
# BlenDiff, whereas these are inherent limits worth stating plainly.
UNSUPPORTED_REASONS: tuple[tuple[re.Pattern, str], ...] = (
	(re.compile(r"^type$"),
	 "An object's type cannot be changed after creation."),
	(re.compile(r"^visible_in_viewlayer$"),
	 "Derived from collection and object visibility; set those instead."),
	(re.compile(r"^mesh\."),
	 "Mesh geometry is summarised, not stored — BlenDiff cannot rebuild it."),
	(re.compile(r"^modifiers\."),
	 "Modifier stacks are not yet applicable; re-create the modifier manually."),
	(re.compile(r"^constraints?\."),
	 "Constraint stacks are not yet applicable; re-create the constraint manually."),
	(re.compile(r"^fcurves?\."),
	 "Animation curves are summarised, not stored — keyframes cannot be rebuilt."),
	(re.compile(r"^drivers?\."),
	 "Drivers are not yet applicable; re-create the driver manually."),
	(re.compile(r"^nla"),
	 "NLA tracks are not yet applicable; re-create the strip manually."),
	(re.compile(r"^material\."),
	 "Material node graphs are not yet applicable; edit the material directly."),
	(re.compile(r"^scene\."),
	 "Scene-level settings are applied separately from object merges."),
	(re.compile(r"^__add_add__$"),
	 "Both sides added an object with this name; BlenDiff cannot create objects."),
)


def find_applier(property_path: str) -> Optional[ApplierEntry]:
	"""Return the applier for a property path, or None when there is none."""
	for entry in REGISTRY:
		if entry.matches(property_path):
			return entry
	return None


def can_apply(property_path: str) -> bool:
	"""
	True when BlenDiff can actually write this property back to the scene.

	The merge UI uses this to mark unappliable conflicts read-only rather than
	inviting a resolution it would silently discard.
	"""
	return find_applier(property_path) is not None


def unsupported_reason(property_path: str) -> str:
	"""
	Explain why a property path cannot be applied.

	Always returns something usable: a specific reason for known limits, and a
	generic one otherwise, so the UI never has to render a blank explanation.
	"""
	for pattern, reason in UNSUPPORTED_REASONS:
		if pattern.match(property_path):
			return reason
	return "BlenDiff cannot apply this property automatically; change it by hand."


def describe(property_path: str) -> str:
	"""Human-readable name of what a property path affects."""
	entry = find_applier(property_path)
	if entry is not None:
		return entry.description
	return property_path


def apply_property(obj: Any, property_path: str, value: Any, context: Any) -> bool:
	"""
	Write one property back to a live Blender object.

	Returns True when applied, False when no applier covers the path. Writers
	raise on genuine failure so the caller can report it per property instead
	of silently dropping it.
	"""
	entry = find_applier(property_path)
	if entry is None:
		return False
	entry.writer(obj, property_path, value, context)
	return True
