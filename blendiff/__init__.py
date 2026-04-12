bl_info = {
    "name":        "BlenDiff",
    "author":      "BlenDiff Contributors",
    "version":     (0, 1, 0),
    "blender":     (3, 6, 0),
    "location":    "3D Viewport > Sidebar > BlenDiff",
    "description": "Semantic scene diff and assisted merge for .blend files",
    "category":    "Scene",
}

try:
    import bpy
    _IN_BLENDER = True
except ModuleNotFoundError:
    _IN_BLENDER = False

if _IN_BLENDER:
    from .ui import panels, operators

    def register() -> None:
        operators.register()
        panels.register()

    def unregister() -> None:
        panels.unregister()
        operators.unregister()