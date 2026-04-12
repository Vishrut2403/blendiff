"""
blendiff.ui.operators
~~~~~~~~~~~~~~~~~~~~~
Blender operators that wire the UI to the diff pipeline.

Each operator is a single, focused action.  Operators store their result
on the WindowManager so the UI panel can read it without coupling to the
operator's execution context.

Design: store the SceneDiff result as a JSON string on
``bpy.context.window_manager.blendiff_result``.  The panel deserializes it
for display.  Using a string property avoids registering complex custom
PropertyGroup trees for now.
"""

from __future__ import annotations

import json
import logging

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from ..extractor import SceneExtractor
from ..serializer import SceneSerializer
from ..diff_engine import DiffEngine

log = logging.getLogger(__name__)


# Operator: run diff on the active scene against a reference snapshot

class BLENDIFF_OT_CapureSnapshot(Operator):
	"""Capture the current scene as a reference snapshot (Scene A)."""
	bl_idname  = "blendiff.capture_snapshot"
	bl_label   = "Capture Snapshot (A)"
	bl_options = {"REGISTER"}

	def execute(self, context):
		try:
			raw = SceneExtractor.extract(context)
			serialized = SceneSerializer().serialize(raw)
			context.window_manager["blendiff_snapshot_a"] = json.dumps(serialized)
			self.report({"INFO"}, f"Snapshot A captured: {len(serialized['objects'])} objects.")
			return {"FINISHED"}
		except Exception as exc:
			log.exception("Snapshot capture failed")
			self.report({"ERROR"}, str(exc))
			return {"CANCELLED"}


class BLENDIFF_OT_RunDiff(Operator):
	"""
	Diff the current scene (B) against the stored snapshot (A).
	Result is stored as JSON on the WindowManager for the panel to display.
	"""
	bl_idname  = "blendiff.run_diff"
	bl_label   = "Run Diff"
	bl_options = {"REGISTER"}

	def execute(self, context):
		wm = context.window_manager

		snapshot_a_json = wm.get("blendiff_snapshot_a")
		if not snapshot_a_json:
			self.report({"WARNING"}, "No snapshot A found. Capture one first.")
			return {"CANCELLED"}

		try:
			scene_a = json.loads(snapshot_a_json)
			raw_b   = SceneExtractor.extract(context)
			scene_b = SceneSerializer().serialize(raw_b)

			diff = DiffEngine().compare(scene_a, scene_b)

			# Store summary + diffs as JSON for the panel
			result = {
				"summary": diff.summary(),
				"object_diffs": [
					{
						"name": d.name,
						"kind": d.kind.value,
						"changes": [
							{
								"property_path": c.property_path,
								"old_value": c.old_value,
								"new_value": c.new_value,
							}
							for c in d.changes
						],
					}
					for d in diff.object_diffs
				],
				"collection_diffs": [
					{
						"path": d.path,
						"kind": d.kind.value,
						"changes": [
							{
								"property_path": c.property_path,
								"old_value": c.old_value,
								"new_value": c.new_value,
							}
							for c in d.changes
						],
					}
					for d in diff.collection_diffs
				],
			}
			wm["blendiff_result"] = json.dumps(result)

			summary = diff.summary()
			self.report(
				{"INFO"},
				f"Diff complete — +{summary['added']} "
				f"-{summary['removed']} "
				f"~{summary['modified']} objects.",
			)
			return {"FINISHED"}

		except Exception as exc:
			log.exception("Diff run failed")
			self.report({"ERROR"}, str(exc))
			return {"CANCELLED"}


class BLENDIFF_OT_ClearResults(Operator):
	"""Clear stored snapshot and diff results."""
	bl_idname  = "blendiff.clear_results"
	bl_label   = "Clear"
	bl_options = {"REGISTER"}

	def execute(self, context):
		wm = context.window_manager
		wm.pop("blendiff_snapshot_a", None)
		wm.pop("blendiff_result", None)
		self.report({"INFO"}, "BlenDiff results cleared.")
		return {"FINISHED"}


# Registration

_CLASSES = [
	BLENDIFF_OT_CapureSnapshot,
	BLENDIFF_OT_RunDiff,
	BLENDIFF_OT_ClearResults,
]


def register():
	for cls in _CLASSES:
		bpy.utils.register_class(cls)


def unregister():
	for cls in reversed(_CLASSES):
		bpy.utils.unregister_class(cls)