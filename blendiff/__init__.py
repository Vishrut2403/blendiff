"""
BlenDiff — semantic diff, snapshot history and assisted merge for .blend files.

This module is both the Blender addon entry point and the root of the
pip-installable library, so it must import cleanly in three environments:
inside Blender with the UI present, inside Blender's Python with only the
pure-Python core installed from PyPI, and outside Blender entirely.
"""

#: Single source of truth for the version.
#
# It was previously stated in three places — here, in bl_info, and in
# pyproject.toml — which had drifted to 0.3.0 / 0.4.0 / 0.5.0 simultaneously.
# bl_info now derives from this, and pyproject reads it directly.
__version__ = "0.7.0"

_version_tuple = tuple(int(part) for part in __version__.split("."))

bl_info = {
	"name":        "BlenDiff",
	"author":      "Vishrut Sachan",
	"version":     _version_tuple,
	"blender":     (3, 6, 0),
	"location":    "3D Viewport > Sidebar > BlenDiff",
	"description": "Semantic scene diff, snapshot history, and assisted merge for .blend files",
	"category":    "Scene",
}

try:
	import bpy as _bpy
	_IN_BLENDER = _bpy is not None
except ModuleNotFoundError:
	_IN_BLENDER = False

# The UI needs bpy at import time, so it is only available inside Blender.
# The wheel and the addon zip ship the same code; what differs is that Blender
# discovers addons in its scripts/addons and extensions directories, not in
# site-packages — so a pip install inside Blender gives you the code but not an
# entry in the Add-ons list.
_UI_AVAILABLE = False
if _IN_BLENDER:
	try:
		from .ui import panels, operators, merge_panel
		_UI_AVAILABLE = True
	except ImportError:  # pragma: no cover — depends on install shape
		_UI_AVAILABLE = False


if _UI_AVAILABLE:

	def register() -> None:
		operators.register()
		panels.register()
		merge_panel.register()

	def unregister() -> None:
		merge_panel.unregister()
		panels.unregister()
		operators.unregister()

elif not _IN_BLENDER:

	def register() -> None:
		raise RuntimeError(
			"BlenDiff's UI only runs inside Blender. This looks like a plain "
			"Python interpreter, where the headless core and extractor are "
			"available but there is no UI to register."
		)

	def unregister() -> None:
		"""No-op: registration never succeeded, so there is nothing to undo."""
		return

else:

	def register() -> None:
		raise RuntimeError(
			"BlenDiff's UI modules failed to import. Install the addon .zip "
			"from the releases page via Edit > Preferences > Add-ons."
		)

	def unregister() -> None:
		"""No-op: registration never succeeded, so there is nothing to undo."""
		return
