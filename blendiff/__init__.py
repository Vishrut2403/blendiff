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

# The wheel published to PyPI ships only the pure-Python core; ui/ and
# extractor/ are excluded because they require bpy. Installing that wheel into
# Blender's own Python therefore gives an environment where bpy imports but the
# UI modules do not exist — so the presence of bpy alone is not enough to
# assume the addon half is available.
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

else:

	def register() -> None:
		raise RuntimeError(
			"BlenDiff's Blender UI is not installed. The PyPI package ships "
			"only the headless core; install the addon .zip from the releases "
			"page to use BlenDiff inside Blender."
		)

	def unregister() -> None:
		"""No-op: registration never succeeded, so there is nothing to undo."""
		return
