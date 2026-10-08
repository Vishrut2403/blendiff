"""
blendiff.data_model.paths
~~~~~~~~~~~~~~~~~~~~~~~~~~
Putting a datablock's name inside a property path, and getting it back out.

Paths name a bone, a shape key or anything else held by name the way Blender's
own data paths do::

    pose.bones["Head"].location
    mesh.shape_keys["Smile"].value

Blender lets a name contain a double quote. A shape key really can be called
``say "hi"``, and so can a bone. Writing that straight into the path produced::

    mesh.shape_keys["say "hi""].value

which the applier's regex read as the key ``say `` and then could not find, so
the change was reported as unapplicable and silently never merged. It failed
safe, in that nothing wrong was written, but a perfectly ordinary name made
part of the tool stop working with a reason that pointed nowhere.

This is the same problem Blender solves with ``bpy.utils.escape_identifier``,
and the same escaping is used here: a backslash before any backslash or
double quote. It is reimplemented rather than imported because the diff engine
is pure Python and must not reach for bpy.
"""

from __future__ import annotations

import re

#: One quoted name inside a path: the characters between the quotes, where a
#: backslash escapes whatever follows it.
QUOTED_NAME = r'((?:[^"\\]|\\.)*)'


def escape_name(name: str) -> str:
	"""Make a name safe to sit inside double quotes in a property path."""
	return str(name).replace("\\", "\\\\").replace('"', '\\"')


def unescape_name(name: str) -> str:
	"""Recover the original name from its escaped form."""
	return re.sub(r"\\(.)", r"\1", str(name))
