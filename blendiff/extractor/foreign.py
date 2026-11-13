"""
blendiff.extractor.foreign
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Reading a scene out of a .blend you are not currently in.

Until now BlenDiff compared a file against its own history. The question it
could not answer is the one people reach for version control to settle:
what is different between my file and the one a colleague just sent me.

The engine was never the obstacle. DiffEngine.compare takes two scene dicts
and does not care where they came from. The obstacle was getting a dict out
of a file that is not open.

Why not run a second Blender
----------------------------
The obvious approach is `blender --background theirs.blend --python ...` and
read back the JSON. It would work, and it is the wrong thing to ship. The
Extensions Platform declined an earlier submission for depending on software
outside Blender, and BlenDiff now carries a test forbidding any subprocess in
the add-on. Spawning Blender would technically be spawning Blender, but the
rule exists so an add-on cannot reach outside itself, and arguing the edge of
it to a reviewer is a poor trade for a feature that does not need it.

So the other file is linked instead. Blender can attach a scene from another
.blend without opening it, the extractor can read any scene rather than only
the active one, and the link is removed afterwards. Nothing is spawned and
nothing is left behind: measured after a round trip, the library count is
back to zero, the object list is unchanged, and the file is not marked dirty.

What a comparison across files means
------------------------------------
Objects are matched by name. Persistent ids are stamped per file, so two
unrelated files share none and name matching is the honest reading. Where one
file is a copy of the other, the ids travel with the copy and renames are
tracked across the pair as they are within one file's history.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from .scene_extractor import SceneExtractor

log = logging.getLogger(__name__)


class ForeignFileError(Exception):
	"""Raised when another .blend cannot be read."""


def _library_of(filepath: str) -> Optional[Any]:
	"""The library datablock for a path, matched the way Blender stores it."""
	import bpy

	wanted = os.path.normpath(os.path.abspath(filepath))
	for library in bpy.data.libraries:
		try:
			resolved = os.path.normpath(bpy.path.abspath(library.filepath))
		except Exception:
			continue
		if resolved == wanted:
			return library
	return None


def extract_scene_from_file(
	filepath: str,
	scene_name: str | None = None,
	store_geometry: bool = False,
) -> tuple[dict, str]:
	"""
	Read one scene out of another .blend, and leave no trace of having done it.

	Returns the serialisable scene dict and the name of the scene read.

	The link is always removed, including when extraction fails: a file left
	quietly attached to somebody's project because a diff went wrong is a far
	worse outcome than the diff not happening.
	"""
	import bpy

	if not filepath:
		raise ForeignFileError("No file chosen.")
	if not os.path.isfile(filepath):
		raise ForeignFileError(f"{os.path.basename(filepath)} does not exist.")
	if os.path.normpath(os.path.abspath(filepath)) == os.path.normpath(
		os.path.abspath(bpy.data.filepath or "")
	):
		raise ForeignFileError("That is this file. Choose a different .blend.")

	already_linked = _library_of(filepath) is not None
	if already_linked:
		# Removing it afterwards would detach something the user linked on
		# purpose, so refuse rather than damage their scene.
		raise ForeignFileError(
			f"{os.path.basename(filepath)} is already linked into this file, "
			f"so BlenDiff will not attach and detach it."
		)

	try:
		with bpy.data.libraries.load(filepath, link=True) as (source, target):
			available = list(source.scenes)
			if not available:
				raise ForeignFileError(
					f"{os.path.basename(filepath)} has no scenes to compare."
				)
			wanted = scene_name if scene_name in available else available[0]
			target.scenes = [wanted]
	except ForeignFileError:
		raise
	except Exception as exc:
		raise ForeignFileError(f"Could not read that .blend: {exc}") from exc

	try:
		# Found by which library it came from, not by name. Both files
		# usually have a scene called "Scene", so a new-name check filtered
		# out the very scene it had just linked.
		library = _library_of(filepath)
		linked = [
			scene for scene in bpy.data.scenes
			if scene.library is not None and scene.library == library
		]
		if not linked:
			raise ForeignFileError("The scene could not be linked.")

		scene = linked[0]
		# Never stamp: the objects belong to someone else's file, and a diff
		# must not write to either side.
		return (
			SceneExtractor.extract_scene(scene, store_geometry=store_geometry),
			scene.name,
		)
	finally:
		_detach(filepath)


def _detach(filepath: str) -> None:
	"""Remove the library this module attached, best effort."""
	import bpy

	library = _library_of(filepath)
	if library is None:
		return
	try:
		bpy.data.libraries.remove(library)
	except Exception as exc:
		# Worth saying loudly: the user's file now holds a link they did not
		# ask for, and they need to know to remove it.
		log.error("Could not detach %s after comparing: %s", filepath, exc)


def scene_names_in_file(filepath: str) -> list[str]:
	"""Every scene name in another .blend, without linking anything."""
	import bpy

	try:
		with bpy.data.libraries.load(filepath, link=True) as (source, _target):
			return list(source.scenes)
	except Exception as exc:
		raise ForeignFileError(f"Could not read that .blend: {exc}") from exc
