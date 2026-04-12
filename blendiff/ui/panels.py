"""
blendiff.ui.panels
~~~~~~~~~~~~~~~~~~
Sidebar panel for the BlenDiff add-on.

Layout
------
  [Capture Snapshot (A)]
  [Run Diff]           [Clear]

  ── Summary ──────────────────
  Added:    2    Removed: 0
  Modified: 3    Collections: 1

  ── Object Diffs ─────────────
  ▸ [+] Cube.001         (added)
  ▸ [~] Suzanne          (modified)
	   transform.location  [0,0,0] → [1,2,3]
	   material_slots[0]   None → Metal
  ...

Design decisions
----------------
* The panel reads from wm["blendiff_result"] (a JSON string).  This
  decouples the panel completely from the diff pipeline — it is a pure
  display layer.
* We parse the JSON lazily (only when the panel draws) so stale results
  from a previous session never crash registration.
* Each object diff section is collapsible using a per-object bool stored
  on the WindowManager.
"""

from __future__ import annotations

import json
import logging

import bpy
from bpy.types import Panel

log = logging.getLogger(__name__)

# Colour tags for the diff kind labels
_KIND_ICON = {
	"added":    "ADD",
	"removed":  "REMOVE",
	"modified": "MODIFIER",
}

_KIND_LABEL = {
	"added":    "(+) added",
	"removed":  "(-) removed",
	"modified": "(~) modified",
}


class BLENDIFF_PT_MainPanel(Panel):
	bl_label       = "BlenDiff"
	bl_idname      = "BLENDIFF_PT_MainPanel"
	bl_space_type  = "VIEW_3D"
	bl_region_type = "UI"
	bl_category    = "BlenDiff"

	def draw(self, context):
		layout = self.layout
		wm     = context.window_manager

		# Actions
		row = layout.row(align=True)
		row.operator("blendiff.capture_snapshot", icon="CAMERA_DATA")

		row2 = layout.row(align=True)
		row2.operator("blendiff.run_diff", icon="FILE_REFRESH")
		row2.operator("blendiff.clear_results", icon="X", text="")

		has_snapshot = bool(wm.get("blendiff_snapshot_a"))
		layout.label(
			text=f"Snapshot A: {'ready' if has_snapshot else 'none'}",
			icon="CHECKMARK" if has_snapshot else "RADIOBUT_OFF",
		)

		layout.separator()

		# Results
		result_json = wm.get("blendiff_result")
		if not result_json:
			layout.label(text="No diff results yet.", icon="INFO")
			return

		try:
			result = json.loads(result_json)
		except (json.JSONDecodeError, TypeError) as exc:
			layout.label(text=f"Error reading results: {exc}", icon="ERROR")
			return

		self._draw_summary(layout, result.get("summary", {}))
		self._draw_object_diffs(layout, result.get("object_diffs", []))
		self._draw_collection_diffs(layout, result.get("collection_diffs", []))



	def _draw_summary(self, layout, summary: dict) -> None:
		box = layout.box()
		box.label(text="Summary", icon="LINENUMBERS_ON")

		grid = box.grid_flow(row_major=True, columns=2, even_columns=True)
		grid.label(text=f"Added:    {summary.get('added', 0)}")
		grid.label(text=f"Removed:  {summary.get('removed', 0)}")
		grid.label(text=f"Modified: {summary.get('modified', 0)}")
		grid.label(text=f"Collections: {summary.get('collection_changes', 0)}")

	def _draw_object_diffs(self, layout, diffs: list) -> None:
		if not diffs:
			return

		box = layout.box()
		box.label(text="Object Changes", icon="OBJECT_DATA")

		for diff in diffs:
			kind  = diff.get("kind", "modified")
			name  = diff.get("name", "?")
			icon  = _KIND_ICON.get(kind, "DOT")
			label = _KIND_LABEL.get(kind, kind)

			row = box.row()
			row.label(text=f"{name}  {label}", icon=icon)

			# Show property changes for modified objects
			if kind == "modified":
				changes = diff.get("changes", [])
				for change in changes[:8]:   # cap at 8 lines to avoid huge panels
					sub = box.row()
					sub.scale_y = 0.7
					sub.label(
						text=f"  {change['property_path']}: "
							 f"{_fmt(change['old_value'])} → "
							 f"{_fmt(change['new_value'])}",
						icon="BLANK1",
					)
				if len(changes) > 8:
					box.label(text=f"  … and {len(changes) - 8} more.")

	def _draw_collection_diffs(self, layout, diffs: list) -> None:
		if not diffs:
			return

		box = layout.box()
		box.label(text="Collection Changes", icon="OUTLINER_COLLECTION")

		for diff in diffs:
			kind  = diff.get("kind", "modified")
			path  = diff.get("path", "?")
			icon  = _KIND_ICON.get(kind, "DOT")
			label = _KIND_LABEL.get(kind, kind)
			box.label(text=f"{path}  {label}", icon=icon)


# Helpers

def _fmt(value) -> str:
	"""Compact display of a diff value."""
	if value is None:
		return "None"
	if isinstance(value, list):
		if len(value) == 3:
			return f"[{value[0]:.3f}, {value[1]:.3f}, {value[2]:.3f}]"
		return str(value)
	return str(value)


# Registration

_CLASSES = [BLENDIFF_PT_MainPanel]


def register():
	for cls in _CLASSES:
		bpy.utils.register_class(cls)


def unregister():
	for cls in reversed(_CLASSES):
		bpy.utils.unregister_class(cls)
