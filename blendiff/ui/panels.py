import json
import bpy

from ..storage.sidecar import SidecarManager


# Helpers

def _get_sidecar(context) -> SidecarManager:
	return SidecarManager(bpy.data.filepath)


def _get_diff_result(context) -> dict | None:
	raw = context.window_manager.get("blendiff_result")
	if not raw:
		return None
	try:
		return json.loads(raw)
	except (json.JSONDecodeError, TypeError):
		return None


# Main panel (legacy in-memory workflow — preserved)

class BLENDIFF_PT_Main(bpy.types.Panel):
	bl_label = "BlenDiff"
	bl_idname = "BLENDIFF_PT_Main"
	bl_space_type = "VIEW_3D"
	bl_region_type = "UI"
	bl_category = "BlenDiff"

	def draw(self, context):
		layout = self.layout
		wm = context.window_manager

		# --- In-memory snapshot workflow ---
		layout.label(text="Quick Diff (in-memory)", icon="CAMERA_DATA")
		col = layout.column(align=True)
		col.operator("blendiff.capture_snapshot", icon="PLUS")
		col.operator("blendiff.run_diff", icon="PLAY")
		col.operator("blendiff.clear_results", icon="X")

		layout.separator()

		# --- Sidecar snapshot workflow ---
		layout.label(text="Snapshot History", icon="DISK_DRIVE")
		if not bpy.data.filepath:
			layout.label(text="Save your .blend file first", icon="ERROR")
		else:
			layout.operator("blendiff.save_snapshot", icon="PLUS")


# Snapshot History sub-panel

class BLENDIFF_PT_SnapshotHistory(bpy.types.Panel):
	bl_label = "Snapshot History"
	bl_idname = "BLENDIFF_PT_SnapshotHistory"
	bl_space_type = "VIEW_3D"
	bl_region_type = "UI"
	bl_category = "BlenDiff"
	bl_parent_id = "BLENDIFF_PT_Main"
	bl_options = {"DEFAULT_CLOSED"}

	@classmethod
	def poll(cls, context):
		return bool(bpy.data.filepath)

	def draw(self, context):
		layout = self.layout
		wm = context.window_manager

		mgr = _get_sidecar(context)
		snapshots = mgr.list_snapshots()

		if not snapshots:
			layout.label(text="No snapshots saved yet.", icon="INFO")
			return

		active_id = wm.get("blendiff_active_snapshot_id", "")

		for snap in snapshots:
			box = layout.box()
			row = box.row()

			# Highlight active snapshot
			is_active = snap.id == active_id
			icon = "RADIOBUT_ON" if is_active else "RADIOBUT_OFF"

			# Label + timestamp
			col = row.column()
			col.label(text=snap.label, icon=icon)
			col.label(text=snap.timestamp_display())

			# Action buttons
			col = row.column(align=True)

			op = col.operator(
				"blendiff.diff_against_snapshot",
				text="",
				icon="PLAY",
			)
			op.snapshot_id = snap.id

			op = col.operator(
				"blendiff.delete_snapshot",
				text="",
				icon="TRASH",
			)
			op.snapshot_id = snap.id


# Results sub-panel

class BLENDIFF_PT_Results(bpy.types.Panel):
	bl_label = "Diff Results"
	bl_idname = "BLENDIFF_PT_Results"
	bl_space_type = "VIEW_3D"
	bl_region_type = "UI"
	bl_category = "BlenDiff"
	bl_parent_id = "BLENDIFF_PT_Main"
	bl_options = {"DEFAULT_CLOSED"}

	@classmethod
	def poll(cls, context):
		return bool(context.window_manager.get("blendiff_result"))

	def draw(self, context):
		layout = self.layout
		wm = context.window_manager
		diff = _get_diff_result(context)

		if diff is None:
			layout.label(text="No diff result available.", icon="INFO")
			return

		# --- Active snapshot label ---
		active_label = wm.get("blendiff_active_snapshot_label")
		if active_label:
			layout.label(text=f"vs. '{active_label}'", icon="BOOKMARKS")

		layout.operator("blendiff.export_html", icon="EXPORT")

		# --- Summary ---
		layout.label(text=diff.get("summary", ""), icon="INFO")
		layout.separator()

		# --- Added objects ---
		added = diff.get("added_objects", [])
		if added:
			box = layout.box()
			box.label(text=f"Added ({len(added)})", icon="ADD")
			for name in added:
				box.label(text=f"  + {name}")

		# --- Removed objects ---
		removed = diff.get("removed_objects", [])
		if removed:
			box = layout.box()
			box.label(text=f"Removed ({len(removed)})", icon="REMOVE")
			for name in removed:
				box.label(text=f"  - {name}")

		# --- Modified objects ---
		modified = diff.get("modified_objects", [])
		if modified:
			box = layout.box()
			box.label(text=f"Modified ({len(modified)})", icon="MODIFIER")
			for obj in modified:
				row = box.row()
				row.label(text=f"  ~ {obj['name']}")
				for change in obj.get("changes", []):
					sub = box.column()
					sub.scale_y = 0.8
					prop = change["property_path"]
					old = _format_value(change["old_value"])
					new = _format_value(change["new_value"])
					sub.label(text=f"      {prop}")
					sub.label(text=f"        {old}  →  {new}")

		# --- Collection diffs ---
		col_diffs = diff.get("collection_diffs", [])
		if col_diffs:
			box = layout.box()
			box.label(text=f"Collections ({len(col_diffs)})", icon="OUTLINER_COLLECTION")
			for cd in col_diffs:
				kind = cd["kind"].capitalize()
				box.label(text=f"  {kind}: {cd['path']}")
				for change in cd.get("changes", []):
					sub = box.column()
					sub.scale_y = 0.8
					prop = change["property_path"]
					old = _format_value(change["old_value"])
					new = _format_value(change["new_value"])
					sub.label(text=f"      {prop}")
					sub.label(text=f"        {old}  →  {new}")


# Value formatting helper  (fixes the material slot dict display bug)

def _format_value(value) -> str:
	"""
	Convert a diff value to a readable string for the panel.

	Handles the material slot display bug:
	  Before: {'index': 0, 'name': 'Material.001', 'use_nodes': True}
	  After:  Material.001
	"""
	if isinstance(value, dict):
		# Material slot dict
		if "name" in value and "index" in value:
			name = value["name"]
			return name if name else "(empty)"
		# Generic dict — show key=value pairs compactly
		pairs = ", ".join(f"{k}={v}" for k, v in value.items())
		return f"{{{pairs}}}"

	if isinstance(value, list):
		# Short numeric lists (transform components) — round for readability
		if all(isinstance(x, (int, float)) for x in value):
			rounded = [round(x, 4) for x in value]
			return str(rounded)
		return str(value)

	if value is None:
		return "(none)"

	return str(value)


# Registration

PANELS = [
	BLENDIFF_PT_Main,
	BLENDIFF_PT_SnapshotHistory,
	BLENDIFF_PT_Results,
]


def register():
	for cls in PANELS:
		bpy.utils.register_class(cls)


def unregister():
	for cls in reversed(PANELS):
		bpy.utils.unregister_class(cls)
