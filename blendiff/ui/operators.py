"""
ui/operators.py

All BlenDiff operators.

Existing operators (untouched behaviour):
  BLENDIFF_OT_CaptureSnapshot  — capture scene A into wm (in-memory, legacy)
  BLENDIFF_OT_RunDiff          — diff wm snapshot A against current scene
  BLENDIFF_OT_ClearResults     — clear wm keys

New sidecar operators:
  BLENDIFF_OT_SaveSnapshot     — save current scene to .blendiff sidecar
  BLENDIFF_OT_DiffAgainstSnapshot — diff a sidecar snapshot against current scene
  BLENDIFF_OT_DeleteSnapshot   — delete a snapshot from the sidecar
"""

import json
import bpy

from ..extractor.scene_extractor import SceneExtractor
from ..serializer.scene_serializer import SceneSerializer
from ..diff_engine.diff_engine import DiffEngine
from ..data_model.scene import SerializedScene
from ..storage.sidecar import SidecarManager


# Helpers

def _extract_current_scene(context) -> tuple[dict, str]:
	"""
	Extract + serialise the current scene.
	Returns (serialized_dict, scene_name).
	"""
	extractor = SceneExtractor()
	serializer = SceneSerializer()
	raw = extractor.extract(context)
	scene: SerializedScene = serializer.serialize(raw)
	return scene, context.scene.name


def _get_sidecar(context) -> SidecarManager:
	return SidecarManager(bpy.data.filepath)


def _run_diff_against_dict(context, snapshot_dict: dict) -> dict:
	"""
	Diff snapshot_dict (a serialised scene dict) against the current scene.
	Stores result JSON on wm["blendiff_result"].
	Returns the SceneDiff summary dict.
	"""
	current_dict, _ = _extract_current_scene(context)

	engine = DiffEngine()
	diff = engine.compare(snapshot_dict, current_dict)

	s = diff.summary()
	result = {
		"summary": f"Added: {s['added']}  Removed: {s['removed']}  Modified: {s['modified']}  Collections: {s['collection_changes']}",
		"added_objects": [o.name for o in diff.added_objects],
		"removed_objects": [o.name for o in diff.removed_objects],
		"modified_objects": [
			{
				"name": o.name,
				"changes": [
					{
						"property_path": c.property_path,
						"old_value": c.old_value,
						"new_value": c.new_value,
					}
					for c in o.changes
				],
			}
			for o in diff.modified_objects
		],
		"collection_diffs": [
			{
				"path": cd.path,
				"kind": cd.kind.value,
				"changes": [
					{
						"property_path": c.property_path,
						"old_value": c.old_value,
						"new_value": c.new_value,
					}
					for c in cd.changes
				],
			}
			for cd in diff.collection_diffs
		],
	}

	context.window_manager["blendiff_result"] = json.dumps(result)
	return result


# Existing operators (preserved exactly)

class BLENDIFF_OT_CaptureSnapshot(bpy.types.Operator):
	"""Capture the current scene as Snapshot A (in-memory)"""
	bl_idname = "blendiff.capture_snapshot"
	bl_label = "Capture Snapshot A"
	bl_description = "Serialise the current scene state as the base for diffing"

	def execute(self, context):
		try:
			scene_dict, _ = _extract_current_scene(context)
			context.window_manager["blendiff_snapshot_a"] = json.dumps(scene_dict)
			self.report({"INFO"}, "BlenDiff: Snapshot A captured.")
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_RunDiff(bpy.types.Operator):
	"""Diff Snapshot A (in-memory) against the current scene"""
	bl_idname = "blendiff.run_diff"
	bl_label = "Run Diff"
	bl_description = "Compare Snapshot A to the current scene state"

	def execute(self, context):
		wm = context.window_manager
		if "blendiff_snapshot_a" not in wm:
			self.report({"ERROR"}, "BlenDiff: No Snapshot A found. Capture one first.")
			return {"CANCELLED"}

		try:
			snapshot_dict = json.loads(wm["blendiff_snapshot_a"])
			result = _run_diff_against_dict(context, snapshot_dict)
			self.report({"INFO"}, f"BlenDiff: {result['summary']}")
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_ClearResults(bpy.types.Operator):
	"""Clear all BlenDiff in-memory data"""
	bl_idname = "blendiff.clear_results"
	bl_label = "Clear Results"
	bl_description = "Clear snapshot A and diff results from memory"

	def execute(self, context):
		wm = context.window_manager
		for key in ("blendiff_snapshot_a", "blendiff_result"):
			if key in wm:
				del wm[key]
		self.report({"INFO"}, "BlenDiff: Cleared.")
		return {"FINISHED"}


# New sidecar operators

class BLENDIFF_OT_SaveSnapshot(bpy.types.Operator):
	"""Save current scene as a named snapshot to the .blendiff sidecar"""
	bl_idname = "blendiff.save_snapshot"
	bl_label = "Save Snapshot"
	bl_description = "Save a named, timestamped snapshot to the .blendiff file next to your .blend"

	label: bpy.props.StringProperty(
		name="Label",
		description="A short name for this snapshot (e.g. 'Before rigging')",
		default="",
	)

	def invoke(self, context, event):
		# Pre-fill with a sensible default
		self.label = f"Snapshot {_get_sidecar(context).snapshot_count() + 1}"
		return context.window_manager.invoke_props_dialog(self)

	def draw(self, context):
		self.layout.prop(self, "label")

	def execute(self, context):
		mgr = _get_sidecar(context)

		if not mgr.is_available:
			self.report(
				{"ERROR"},
				"BlenDiff: Please save your .blend file before using snapshot history.",
			)
			return {"CANCELLED"}

		label = self.label.strip() or f"Snapshot {mgr.snapshot_count() + 1}"

		try:
			scene_dict, scene_name = _extract_current_scene(context)
			snap = mgr.save_snapshot(label, scene_name, scene_dict)
			self.report({"INFO"}, f"BlenDiff: Saved snapshot '{snap.label}' ({snap.id[:8]})")
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_DiffAgainstSnapshot(bpy.types.Operator):
	"""Diff a sidecar snapshot against the current scene"""
	bl_idname = "blendiff.diff_against_snapshot"
	bl_label = "Diff Against This Snapshot"
	bl_description = "Compare this saved snapshot to the current scene"

	snapshot_id: bpy.props.StringProperty()

	def execute(self, context):
		if not self.snapshot_id:
			self.report({"ERROR"}, "BlenDiff: No snapshot ID provided.")
			return {"CANCELLED"}

		mgr = _get_sidecar(context)
		snap = mgr.get_snapshot(self.snapshot_id)

		if snap is None:
			self.report({"ERROR"}, f"BlenDiff: Snapshot {self.snapshot_id[:8]} not found.")
			return {"CANCELLED"}

		try:
			# Store the source label so the panel can show which snapshot is active
			context.window_manager["blendiff_active_snapshot_label"] = snap.label
			context.window_manager["blendiff_active_snapshot_id"] = snap.id

			result = _run_diff_against_dict(context, snap.data)
			self.report({"INFO"}, f"BlenDiff [{snap.label}]: {result['summary']}")
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_DeleteSnapshot(bpy.types.Operator):
	"""Delete a snapshot from the sidecar"""
	bl_idname = "blendiff.delete_snapshot"
	bl_label = "Delete Snapshot"
	bl_description = "Permanently delete this snapshot from the .blendiff file"

	snapshot_id: bpy.props.StringProperty()

	def invoke(self, context, event):
		return context.window_manager.invoke_confirm(self, event)

	def execute(self, context):
		if not self.snapshot_id:
			self.report({"ERROR"}, "BlenDiff: No snapshot ID provided.")
			return {"CANCELLED"}

		mgr = _get_sidecar(context)
		deleted = mgr.delete_snapshot(self.snapshot_id)

		if deleted:
			# Clear active snapshot if it was the one deleted
			wm = context.window_manager
			if wm.get("blendiff_active_snapshot_id") == self.snapshot_id:
				for key in ("blendiff_active_snapshot_id", "blendiff_active_snapshot_label",
							"blendiff_result"):
					if key in wm:
						del wm[key]
			self.report({"INFO"}, "BlenDiff: Snapshot deleted.")
		else:
			self.report({"WARNING"}, "BlenDiff: Snapshot not found.")

		return {"FINISHED"}
	
class BLENDIFF_OT_ExportHTML(bpy.types.Operator):
	"""Export the current diff result as a self-contained HTML report"""
	bl_idname = "blendiff.export_html"
	bl_label = "Export HTML Report"
	bl_description = "Save the diff result as a shareable HTML file"

	def execute(self, context):
		wm = context.window_manager

		if "blendiff_result" not in wm:
			self.report({"ERROR"}, "BlenDiff: No diff result to export. Run a diff first.")
			return {"CANCELLED"}

		if not bpy.data.filepath:
			self.report({"ERROR"}, "BlenDiff: Please save your .blend file first.")
			return {"CANCELLED"}

		try:
				from ..export.html_exporter import export_to_file, build_output_path

				result = json.loads(wm["blendiff_result"])
				snapshot_label = wm.get("blendiff_active_snapshot_label", "Snapshot")

				output_path = build_output_path(bpy.data.filepath, snapshot_label)
				export_to_file(
						result=result,
						snapshot_label=snapshot_label,
						blend_filepath=bpy.data.filepath,
						output_path=output_path,
				)

				self.report({"INFO"}, f"BlenDiff: Exported to {output_path}")
				return {"FINISHED"}

		except Exception as e:
				self.report({"ERROR"}, f"BlenDiff: {e}")
				return {"CANCELLED"}


# Registration

OPERATORS = [
	BLENDIFF_OT_CaptureSnapshot,
	BLENDIFF_OT_RunDiff,
	BLENDIFF_OT_ClearResults,
	BLENDIFF_OT_SaveSnapshot,
	BLENDIFF_OT_DiffAgainstSnapshot,
	BLENDIFF_OT_DeleteSnapshot,
	BLENDIFF_OT_ExportHTML,
]


def register():
	for cls in OPERATORS:
		bpy.utils.register_class(cls)


def unregister():
	for cls in reversed(OPERATORS):
		bpy.utils.unregister_class(cls)
