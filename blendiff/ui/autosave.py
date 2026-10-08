"""
blendiff.ui.autosave
~~~~~~~~~~~~~~~~~~~~~
Taking a snapshot every time the file is saved.

Every snapshot was manual, which makes the history only as good as somebody's
memory. A version control tool you have to remember to use gets used right up
until the one time it would have mattered.

This is off by default and lives in the add-on preferences, because writing a
file beside somebody's .blend without being asked is not a decision an add-on
should make for them.

Why it does not stamp identities
--------------------------------
Capture normally gives objects a persistent id so renames stay trackable, and
marks the file modified so the stamps survive the session. Doing that from a
save handler would leave the file dirty the instant it was saved, which looks
like a bug and trains people to distrust the save indicator.

So an automatic snapshot reads the ids that are already there and writes none.
Objects created since the last manual snapshot are matched by name until a
manual snapshot stamps them, which is the same fallback used for any snapshot
taken before identities existed.
"""

from __future__ import annotations

import logging

import bpy
from bpy.app.handlers import persistent

from ..storage.sidecar import SidecarManager
from .registration import register_classes, unregister_classes

log = logging.getLogger(__name__)

#: The add-on's own module name, which is what preferences are keyed by.
#
# This module is blendiff.ui.autosave under a legacy install and
# bl_ext.<repo>.blendiff.ui.autosave as an extension, so the package is
# derived rather than written down.
ADDON_PACKAGE = __package__.rsplit(".", 1)[0]


class BLENDIFF_AddonPreferences(bpy.types.AddonPreferences):
	bl_idname = ADDON_PACKAGE

	snapshot_on_save: bpy.props.BoolProperty(
		name="Snapshot on save",
		description=(
			"Take a snapshot automatically every time the .blend is saved. "
			"Automatic snapshots are pruned; the ones you take by hand are not"
		),
		default=False,
	)

	keep_auto_snapshots: bpy.props.IntProperty(
		name="Keep",
		description=(
			"How many automatic snapshots to keep. The oldest are dropped "
			"beyond this. Snapshots you took by hand are never pruned"
		),
		default=10,
		min=1,
		max=500,
	)

	def draw(self, context):
		layout = self.layout
		layout.prop(self, "snapshot_on_save")
		row = layout.row()
		row.enabled = self.snapshot_on_save
		row.prop(self, "keep_auto_snapshots")
		if self.snapshot_on_save:
			layout.label(
				text="Snapshots you take by hand are never pruned.",
				icon="INFO",
			)


def _preferences():
	"""This add-on's preferences, or None when they cannot be reached."""
	try:
		return bpy.context.preferences.addons[ADDON_PACKAGE].preferences
	except (KeyError, AttributeError):
		# Happens while the add-on is being registered, and in background
		# runs that never loaded preferences at all.
		return None


@persistent
def snapshot_after_save(_dummy=None, _dummy2=None) -> None:
	"""
	Save handler. Never raises: a failure here must not break saving.

	Blender shows no useful error from a handler, and a traceback at save time
	would look like the save itself failed. Anything that goes wrong is logged
	and the save stands.
	"""
	prefs = _preferences()
	if prefs is None or not prefs.snapshot_on_save:
		return

	try:
		from .operators import _extract_current_scene

		manager = SidecarManager(bpy.data.filepath)
		if not manager.is_available:
			return

		scene_dict, scene_name = _extract_current_scene(
			bpy.context, stamp_identity=False,
		)
		label = _auto_label(manager)
		manager.save_snapshot(label, scene_name, scene_dict, auto=True)
		removed = manager.prune_auto_snapshots(prefs.keep_auto_snapshots)
		log.info("Automatic snapshot %r saved (pruned %d)", label, removed)
	except Exception as exc:
		log.warning("Automatic snapshot failed, the save itself is fine: %s", exc)


def _auto_label(manager) -> str:
	"""
	A label that reads as automatic, sorts sensibly, and is not already taken.

	Labels have to be unique, which a timestamp alone does not guarantee: two
	saves in the same second produced two snapshots called the same thing.
	That is not just untidy. The merge and compare pickers are enum properties
	keyed by label, so duplicates make choosing one ambiguous.
	"""
	from datetime import datetime

	base = datetime.now().strftime("Auto %Y-%m-%d %H:%M:%S")
	try:
		taken = {snap.label for snap in manager.list_snapshots()}
	except Exception:
		return base

	if base not in taken:
		return base
	for suffix in range(2, 1000):
		candidate = f"{base} ({suffix})"
		if candidate not in taken:
			return candidate
	return f"{base} ({datetime.now().microsecond})"


CLASSES = [BLENDIFF_AddonPreferences]


def register():
	register_classes(CLASSES)
	if snapshot_after_save not in bpy.app.handlers.save_post:
		bpy.app.handlers.save_post.append(snapshot_after_save)


def unregister():
	# Leaving a handler behind would keep writing snapshots after the add-on
	# was switched off, which is the worst possible way to lose trust in it.
	if snapshot_after_save in bpy.app.handlers.save_post:
		bpy.app.handlers.save_post.remove(snapshot_after_save)
	unregister_classes(CLASSES)
