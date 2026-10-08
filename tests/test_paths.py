"""
tests/test_paths.py
~~~~~~~~~~~~~~~~~~~~
Names with quotes in them, inside property paths.

Blender lets a shape key be called `say "hi"` and a bone the same. Writing
that straight into a path gave `mesh.shape_keys["say "hi""].value`, which the
applier's regex read as the key `say ` and then could not find. It failed
safe, nothing wrong was written, but the change was reported as unapplicable
with a reason that pointed nowhere, so an ordinary name quietly made part of
the merge stop working.

Found by testing names a user can actually type, rather than the names
fixtures happen to use.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.data_model.paths import QUOTED_NAME, escape_name, unescape_name
from blendiff.merge_engine.armature_applier import parse_rest_bone_path
from blendiff.merge_engine.property_appliers import can_apply

HOSTILE = [
	"Smile",
	'say "hi"',
	r"back\slash",
	'both "and" \\ together',
	'"',
	'ends with a quote"',
	'"starts with one',
	"",
]


class TestEscaping:

	@pytest.mark.parametrize("name", HOSTILE)
	def test_a_name_survives_the_round_trip(self, name):
		assert unescape_name(escape_name(name)) == name

	@pytest.mark.parametrize("name", HOSTILE)
	def test_the_escaped_name_parses_out_of_a_path(self, name):
		path = f'mesh.shape_keys["{escape_name(name)}"].value'
		match = re.match(r'^mesh\.shape_keys\["' + QUOTED_NAME + r'"\]\.(\w+)$', path)
		assert match is not None, path
		assert unescape_name(match.group(1)) == name

	def test_escaping_is_what_blender_does(self):
		# bpy.utils.escape_identifier escapes a backslash and a double quote,
		# and nothing else. Matching it keeps BlenDiff's paths readable as
		# Blender data paths.
		assert escape_name('a"b') == 'a\\"b'
		assert escape_name("a\\b") == "a\\\\b"
		assert escape_name("a'b") == "a'b"


class TestAppliersAcceptHostileNames:
	"""can_apply must not quietly go False because of a quote in a name."""

	@pytest.mark.parametrize("name", [n for n in HOSTILE if n])
	def test_shape_key_path_is_applicable(self, name):
		assert can_apply(f'mesh.shape_keys["{escape_name(name)}"].value')

	@pytest.mark.parametrize("name", [n for n in HOSTILE if n])
	def test_pose_bone_path_is_applicable(self, name):
		assert can_apply(f'pose.bones["{escape_name(name)}"].rotation_mode')

	@pytest.mark.parametrize("name", [n for n in HOSTILE if n])
	def test_rest_bone_path_parses_back_to_the_name(self, name):
		parsed = parse_rest_bone_path(f'armature.bones["{escape_name(name)}"].roll')
		assert parsed == (name, "roll")

	def test_an_unescaped_quote_is_still_rejected(self):
		"""The old broken form must not start silently half-matching."""
		assert not can_apply('mesh.shape_keys["say "hi""].value')
