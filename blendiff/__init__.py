"""
BlenDiff — semantic diff, snapshot history and assisted merge for .blend files.

Copyright (C) 2026 Vishrut Sachan

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <https://www.gnu.org/licenses/>.

Blender's Extensions Platform requires add-ons to be GPL-3.0-or-later, since
anything using the bpy API is treated as a derivative of Blender itself. The
whole project is licensed that way rather than splitting it, so the pip package
and the addon are the same code under the same terms.

This module is both the Blender addon entry point and the root of the
pip-installable library, so it must import cleanly in three environments:
inside Blender with the UI present, inside Blender's Python with only the
pure-Python core installed from PyPI, and outside Blender entirely.
"""

#: Single source of truth for the version.
#
# It was previously stated in three places, here, in bl_info, and in
# pyproject.toml, which had drifted to 0.3.0 / 0.4.0 / 0.5.0 simultaneously.
# pyproject reads this string directly, and a test keeps bl_info in step.
__version__ = "0.8.0"

# bl_info's version must be written out as a literal tuple, never computed from
# __version__.
#
# Blender never imports an addon to read its bl_info. It parses the source and
# runs ast.literal_eval on the dict, which accepts only literals and rejects a
# variable reference. Deriving the version from a computed tuple made that call
# raise, addon_utils skipped the module, and BlenDiff was missing from the
# Add-ons list entirely: not greyed out or failing to enable, simply absent,
# with no way to tick it. Every other addon in the list parsed fine, so nothing
# pointed at BlenDiff as the cause.
#
# Repeating the version here is the price of that constraint. The duplication
# is held in check by tests/test_manifest.py, which parses this file the way
# Blender does and compares the result against __version__.
bl_info = {
	"name":        "BlenDiff",
	"author":      "Vishrut Sachan",
	"version":     (0, 8, 0),
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
