"""
BlenDiff — semantic diff, snapshot history, and assisted merge for .blend files.

When imported outside Blender (e.g. via pip), only the pure-Python core is
available: data_model, diff_engine, serializer, storage, export, cli.

When imported inside Blender, the full addon registers its UI panels and
operators on top of the core.
"""

__version__ = "0.3.0"

bl_info = {
	"name":        "BlenDiff",
	"author":      "Vishrut",
	"version":     (0, 3, 0),
	"blender":     (3, 6, 0),
	"location":    "3D Viewport > Sidebar > BlenDiff",
	"description": "Semantic scene diff, snapshot history, and assisted merge for .blend files",
	"category":    "Scene",
}

try:
	import bpy
	_IN_BLENDER = True
except ModuleNotFoundError:
	_IN_BLENDER = False

if _IN_BLENDER:
	from .ui import panels, operators, merge_panel

	def register() -> None:
		operators.register()
		panels.register()
		merge_panel.register()

	def unregister() -> None:
		merge_panel.unregister()
		panels.unregister()
		operators.unregister()
