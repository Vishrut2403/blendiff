__version__ = "0.3.0"

bl_info = {
	"name":        "BlenDiff",
	"author":      "Vishrut Sachan",
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
