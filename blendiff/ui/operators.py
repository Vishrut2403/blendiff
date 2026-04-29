import json
import bpy

from ..extractor.scene_extractor import SceneExtractor
from ..serializer.scene_serializer import SceneSerializer
from ..diff_engine.diff_engine import DiffEngine
from ..data_model.scene import SerializedScene
from ..storage.sidecar import SidecarManager
from ..data_model.conflict import Resolution
from ..merge_engine.merge_engine import MergeEngine


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
		
class BLENDIFF_OT_RunThreeWayDiff(bpy.types.Operator):
	"""Run a three-way diff between base, version A and version B snapshots"""
	bl_idname = "blendiff.run_threeway_diff"
	bl_label = "Run Three-Way Diff"
	bl_description = "Compare base vs version A vs version B to find conflicts"
 
	def execute(self, context):
		wm = context.window_manager
 
		if not bpy.data.filepath:
			self.report({"ERROR"}, "BlenDiff: Save your .blend file first.")
			return {"CANCELLED"}
 
		base_label = wm.blendiff_base_label.strip()
		a_label    = wm.blendiff_a_label.strip()
		b_label    = wm.blendiff_b_label.strip()

		if not all([base_label, a_label, b_label]):
			self.report({"ERROR"}, "BlenDiff: Please fill in Base, Version A and Version B labels.")
			return {"CANCELLED"}

		mgr = SidecarManager(bpy.data.filepath)
		all_snapshots = mgr.list_snapshots()

		def find(label, snaps):
			for s in snaps:
				if s.label == label:
					return s
			return None

		base  = find(base_label,  all_snapshots)
		ver_a = find(a_label,     all_snapshots)
		ver_b = find(b_label,     all_snapshots)

		missing = [l for l, s in [(base_label, base), (a_label, ver_a), (b_label, ver_b)] if s is None]
		if missing:
			self.report({"ERROR"}, f"BlenDiff: Snapshots not found: {', '.join(missing)}")
			return {"CANCELLED"}
 
		try:
			engine = MergeEngine()
			tw = engine.three_way_diff(
				base=base.data,
				version_a=ver_a.data,
				version_b=ver_b.data,
				base_label=base_label,
				label_a=a_label,
				label_b=b_label,
			)
 
			# Serialise ThreeWayDiff to JSON for UI storage
			result = _serialize_threeway(tw)
			wm["blendiff_threeway_result"] = json.dumps(result)
			wm["blendiff_threeway_obj"] = json.dumps(result)  # kept for applier
 
			s = tw.summary()
			self.report({"INFO"},
				f"BlenDiff: {s['total_conflicts']} conflict(s), "
				f"{s['auto_resolved']} auto-resolved, "
				f"{s['unresolved']} need resolution."
			)
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}
 
 
class BLENDIFF_OT_SetResolution(bpy.types.Operator):
	"""Set the resolution for a specific conflict"""
	bl_idname = "blendiff.set_resolution"
	bl_label = "Set Resolution"
 
	object_name:   bpy.props.StringProperty()
	property_path: bpy.props.StringProperty()
	resolution:    bpy.props.StringProperty()  # 'use_a', 'use_b', 'use_base'
 
	def execute(self, context):
		wm = context.window_manager
		raw = wm.get("blendiff_threeway_result")
		if not raw:
			self.report({"ERROR"}, "BlenDiff: No three-way diff result found.")
			return {"CANCELLED"}
 
		try:
			result = json.loads(raw)
 
			# Find and update the conflict
			for proposal in result.get("proposals", []):
				if proposal["object_name"] == self.object_name:
					for conflict in proposal.get("conflicts", []):
						if conflict["property_path"] == self.property_path:
							conflict["resolution"] = self.resolution
							break
 
			# Recompute ready_to_apply
			all_resolved = all(
				all(
					c.get("resolution", "unresolved") not in ("unresolved",)
					for c in p.get("conflicts", [])
				)
				for p in result.get("proposals", [])
			)
			result["summary"]["ready_to_apply"] = all_resolved
			unresolved = sum(
				sum(1 for c in p.get("conflicts", [])
					if c.get("resolution", "unresolved") == "unresolved")
				for p in result.get("proposals", [])
			)
			result["summary"]["unresolved"] = unresolved
 
			wm["blendiff_threeway_result"] = json.dumps(result)
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}
 
 
class BLENDIFF_OT_ApplyMerge(bpy.types.Operator):
	"""Apply all resolved merge decisions to the current scene"""
	bl_idname = "blendiff.apply_merge"
	bl_label = "Apply Merge"
	bl_description = "Apply all resolved conflict decisions to the scene"
 
	def invoke(self, context, event):
		return context.window_manager.invoke_confirm(self, event)
 
	def execute(self, context):
		wm = context.window_manager
		raw = wm.get("blendiff_threeway_result")
		if not raw:
			self.report({"ERROR"}, "BlenDiff: No three-way diff result.")
			return {"CANCELLED"}
 
		result = json.loads(raw)
		if not result.get("summary", {}).get("ready_to_apply", False):
			self.report({"ERROR"}, "BlenDiff: Not all conflicts resolved yet.")
			return {"CANCELLED"}
 
		try:
			from ..merge_engine.applier import Applier
			from ..data_model.conflict import (
				ThreeWayDiff, MergeProposal, PropertyConflict,
				NonConflictingChange, Resolution, ConflictKind,
			)
 
			# Reconstruct ThreeWayDiff from stored JSON
			tw = _deserialize_threeway(result)
			applier = Applier()
			apply_result = applier.apply_all(tw, context)
 
			# Clear the threeway result
			if "blendiff_threeway_result" in wm:
				del wm["blendiff_threeway_result"]
 
			self.report(
				{"INFO"},
				f"BlenDiff: Applied {apply_result.succeeded} proposal(s). "
				f"Failed: {apply_result.failed}."
			)
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}
 

# Serialization helpers for ThreeWayDiff ↔ JSON (for wm storage)
 
def _serialize_threeway(tw) -> dict:
	"""Convert ThreeWayDiff to a plain JSON-safe dict."""
	return {
		"base_label": tw.base_label,
		"label_a":    tw.label_a,
		"label_b":    tw.label_b,
		"summary":    tw.summary(),
		"proposals": [
			{
				"object_name": p.object_name,
				"structural_conflict": p.structural_conflict,
				"conflicts": [
					{
						"property_path": c.property_path,
						"base_value":    c.base_value,
						"value_a":       c.value_a,
						"value_b":       c.value_b,
						"kind":          c.kind.value,
						"resolution":    c.resolution.value,
					}
					for c in p.conflicts
				],
				"non_conflicting_from_a": [
					{"property_path": nc.property_path,
					 "base_value": nc.base_value,
					 "new_value": nc.new_value,
					 "source": nc.source}
					for nc in p.non_conflicting_from_a
				],
				"non_conflicting_from_b": [
					{"property_path": nc.property_path,
					 "base_value": nc.base_value,
					 "new_value": nc.new_value,
					 "source": nc.source}
					for nc in p.non_conflicting_from_b
				],
			}
			for p in tw.proposals
		],
	}
 
 
def _deserialize_threeway(d: dict):
	"""Reconstruct a ThreeWayDiff from a JSON dict."""
	from ..data_model.conflict import (
		ThreeWayDiff, MergeProposal, PropertyConflict,
		NonConflictingChange, Resolution, ConflictKind,
	)
 
	proposals = []
	for pd in d.get("proposals", []):
		conflicts = [
			PropertyConflict(
				property_path=c["property_path"],
				base_value=c["base_value"],
				value_a=c["value_a"],
				value_b=c["value_b"],
				kind=ConflictKind(c["kind"]),
				resolution=Resolution(c["resolution"]),
			)
			for c in pd.get("conflicts", [])
		]
		nc_a = [
			NonConflictingChange(**nc)
			for nc in pd.get("non_conflicting_from_a", [])
		]
		nc_b = [
			NonConflictingChange(**nc)
			for nc in pd.get("non_conflicting_from_b", [])
		]
		proposals.append(MergeProposal(
			object_name=pd["object_name"],
			conflicts=conflicts,
			non_conflicting_from_a=nc_a,
			non_conflicting_from_b=nc_b,
			structural_conflict=pd.get("structural_conflict", False),
		))
 
	tw = ThreeWayDiff(
		base_label=d["base_label"],
		label_a=d["label_a"],
		label_b=d["label_b"],
		proposals=proposals,
		auto_resolved_count=d.get("summary", {}).get("auto_resolved", 0),
	)
	return tw


# Registration

OPERATORS = [
	BLENDIFF_OT_CaptureSnapshot,
	BLENDIFF_OT_RunDiff,
	BLENDIFF_OT_ClearResults,
	BLENDIFF_OT_SaveSnapshot,
	BLENDIFF_OT_DiffAgainstSnapshot,
	BLENDIFF_OT_DeleteSnapshot,
	BLENDIFF_OT_ExportHTML,
	BLENDIFF_OT_RunThreeWayDiff,
	BLENDIFF_OT_SetResolution,
	BLENDIFF_OT_ApplyMerge,
]


def register():
	for cls in OPERATORS:
		bpy.utils.register_class(cls)


def unregister():
	for cls in reversed(OPERATORS):
		bpy.utils.unregister_class(cls)
