"""
blendiff.ui.merge_panel
~~~~~~~~~~~~~~~~~~~~~~~~
Three-way merge conflict resolution panel.

Location: 3D Viewport → N panel → BlenDiff → Three-Way Merge

Workflow:
  1. User picks Base, Version A, Version B snapshots from dropdowns
  2. Hits "Run Three-Way Diff"
  3. Conflicts appear per object, each with Use A / Use B / Use Base buttons
  4. When all resolved, "Apply Merge" button becomes active
  5. Applier runs, scene is updated

The ThreeWayDiff result is stored as JSON on wm["blendiff_threeway_result"].
"""

from __future__ import annotations

import json
import bpy

from ..storage.sidecar import SidecarManager


def _get_sidecar(context):
	return SidecarManager(bpy.data.filepath)


def _get_threeway(context):
	raw = context.window_manager.get("blendiff_threeway_result")
	if not raw:
		return None
	try:
		return json.loads(raw)
	except Exception:
		return None


# Main three-way merge panel

class BLENDIFF_PT_ThreeWayMerge(bpy.types.Panel):
	bl_label = "Three-Way Merge"
	bl_idname = "BLENDIFF_PT_ThreeWayMerge"
	bl_space_type = "VIEW_3D"
	bl_region_type = "UI"
	bl_category = "BlenDiff"
	bl_options = {"DEFAULT_CLOSED"}

	def draw(self, context):
		layout = self.layout
		wm = context.window_manager

		if not bpy.data.filepath:
			layout.label(text="Save your .blend file first", icon="ERROR")
			return

		# --- Snapshot pickers ---
		layout.label(text="Select Snapshots", icon="BOOKMARKS")
		col = layout.column(align=True)
		col.prop(wm, "blendiff_base_label",   text="Base")
		col.prop(wm, "blendiff_a_label",      text="Version A")
		col.prop(wm, "blendiff_b_label",      text="Version B")

		layout.separator()
		layout.operator("blendiff.run_threeway_diff", icon="PLAY")

		# --- Results ---
		tw = _get_threeway(context)
		if tw is None:
			return

		layout.separator()
		summary = tw.get("summary", {})
		layout.label(
			text=f"Conflicts: {summary.get('total_conflicts', 0)}  "
				 f"Unresolved: {summary.get('unresolved', 0)}  "
				 f"Auto: {summary.get('auto_resolved', 0)}",
			icon="INFO",
		)

		# Apply button — only active when all resolved
		row = layout.row()
		row.enabled = summary.get("ready_to_apply", False)
		row.operator("blendiff.apply_merge", icon="CHECKMARK")

		layout.separator()

		# --- Per-proposal conflict cards ---
		proposals = tw.get("proposals", [])
		for proposal in proposals:
			self._draw_proposal(layout, proposal)

	def _draw_proposal(self, layout, proposal: dict):
		name = proposal["object_name"]
		conflicts = proposal.get("conflicts", [])
		nc_a = proposal.get("non_conflicting_from_a", [])
		nc_b = proposal.get("non_conflicting_from_b", [])

		box = layout.box()
		row = box.row()
		has_conflicts = bool(conflicts)
		icon = "ERROR" if has_conflicts else "CHECKMARK"
		row.label(text=name, icon=icon)

		# Non-conflicting changes (informational)
		if nc_a or nc_b:
			sub = box.column()
			sub.scale_y = 0.8
			for nc in nc_a:
				if nc["property_path"] != "__structural__":
					sub.label(text=f"  A: {nc['property_path']}", icon="DOT")
			for nc in nc_b:
				if nc["property_path"] != "__structural__":
					sub.label(text=f"  B: {nc['property_path']}", icon="DOT")

		# Conflict rows
		for conflict in conflicts:
			self._draw_conflict(box, name, conflict)

	def _draw_conflict(self, layout, object_name: str, conflict: dict):
		prop_path   = conflict["property_path"]
		resolution  = conflict.get("resolution", "unresolved")
		kind        = conflict.get("kind", "")
		value_a     = _fmt(conflict.get("value_a"))
		value_b     = _fmt(conflict.get("value_b"))
		base_val    = _fmt(conflict.get("base_value"))

		sub = layout.box()
		sub.scale_y = 0.9

		# Property path
		sub.label(text=prop_path, icon="DECORATE_DRIVER")

		# Values
		row = sub.row()
		row.label(text=f"Base: {base_val}")
		row = sub.row()
		row.label(text=f"A: {value_a}")
		row.label(text=f"B: {value_b}")

		if resolution == "auto":
			sub.label(text="✓ Auto-resolved (same change)", icon="CHECKMARK")
			return

		# Resolution buttons
		row = sub.row(align=True)

		op = row.operator("blendiff.set_resolution", text="Use A",
						  icon="RADIOBUT_ON" if resolution == "use_a" else "RADIOBUT_OFF")
		op.object_name  = object_name
		op.property_path = prop_path
		op.resolution   = "use_a"

		op = row.operator("blendiff.set_resolution", text="Use B",
						  icon="RADIOBUT_ON" if resolution == "use_b" else "RADIOBUT_OFF")
		op.object_name  = object_name
		op.property_path = prop_path
		op.resolution   = "use_b"

		op = row.operator("blendiff.set_resolution", text="Base",
						  icon="RADIOBUT_ON" if resolution == "use_base" else "RADIOBUT_OFF")
		op.object_name  = object_name
		op.property_path = prop_path
		op.resolution   = "use_base"


def _fmt(value) -> str:
	if value is None:
		return "(none)"
	if isinstance(value, list):
		if all(isinstance(x, (int, float)) for x in value):
			return "[" + ", ".join(f"{x:.3f}" if isinstance(x, float) else str(x) for x in value) + "]"
	return str(value)[:40]


# WindowManager properties for snapshot label pickers

def register_wm_props():
	bpy.types.WindowManager.blendiff_base_label = bpy.props.StringProperty(
		name="Base Snapshot Label",
		description="Label of the common ancestor snapshot",
		default="",
	)
	bpy.types.WindowManager.blendiff_a_label = bpy.props.StringProperty(
		name="Version A Label",
		description="Label of version A snapshot",
		default="",
	)
	bpy.types.WindowManager.blendiff_b_label = bpy.props.StringProperty(
		name="Version B Label",
		description="Label of version B snapshot",
		default="",
	)


def unregister_wm_props():
	del bpy.types.WindowManager.blendiff_base_label
	del bpy.types.WindowManager.blendiff_a_label
	del bpy.types.WindowManager.blendiff_b_label


# Registration

PANELS = [
	BLENDIFF_PT_ThreeWayMerge,
]


def register():
	register_wm_props()
	for cls in PANELS:
		bpy.utils.register_class(cls)


def unregister():
	for cls in reversed(PANELS):
		bpy.utils.unregister_class(cls)
	unregister_wm_props()
