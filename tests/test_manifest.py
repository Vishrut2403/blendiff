"""
tests/test_manifest.py
~~~~~~~~~~~~~~~~~~~~~~~
The Blender Extensions manifest.

BlenDiff carries two pieces of addon metadata: `bl_info` in __init__.py, which
Blender 3.6-4.1 reads from the legacy addon zip, and blender_manifest.toml,
which the Extensions Platform reads for 4.2+. They describe the same addon, so
they must never disagree — a version mismatch would publish an extension
claiming to be a release it is not.

The platform's own constraints are asserted here too, because finding out about
a 65-character tagline during submission review is a slow way to learn it.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
	import tomllib
except ModuleNotFoundError:  # pragma: no cover — Python < 3.11
	tomllib = None

import blendiff

MANIFEST_PATH = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
	"blendiff", "blender_manifest.toml",
)

pytestmark = pytest.mark.skipif(tomllib is None, reason="tomllib needs Python 3.11+")


@pytest.fixture(scope="module")
def manifest():
	with open(MANIFEST_PATH, "rb") as f:
		return tomllib.load(f)


class TestManifestExists:
	def test_manifest_is_inside_the_package(self):
		"""
		An extension zip has the manifest beside __init__.py, because Blender
		installs the zip's contents *as* the package.
		"""
		assert os.path.exists(MANIFEST_PATH)

	def test_required_fields_present(self):
		with open(MANIFEST_PATH, "rb") as f:
			data = tomllib.load(f)
		for field in ("schema_version", "id", "version", "name", "tagline",
		              "maintainer", "type", "blender_version_min", "license"):
			assert field in data, f"manifest missing required field {field!r}"


class TestVersionAgreement:
	def test_manifest_matches_package_version(self, manifest):
		"""The single source of truth is __version__; the manifest follows it."""
		assert manifest["version"] == blendiff.__version__

	def test_manifest_matches_bl_info(self, manifest):
		expected = ".".join(str(p) for p in blendiff.bl_info["version"])
		assert manifest["version"] == expected


class TestPlatformConstraints:
	def test_tagline_within_length_limit(self, manifest):
		assert len(manifest["tagline"]) <= 64

	def test_tagline_has_no_trailing_punctuation(self, manifest):
		"""The platform rejects a tagline ending in punctuation."""
		assert manifest["tagline"][-1] not in ".!?,;:"

	def test_license_is_gpl(self, manifest):
		"""
		The Extensions Platform requires add-ons be GPL-3.0-or-later: anything
		using the bpy API counts as a derivative of Blender, which is GPL.
		"""
		assert manifest["license"] == ["SPDX:GPL-3.0-or-later"]

	def test_type_is_addon(self, manifest):
		assert manifest["type"] == "add-on"

	def test_extensions_require_blender_4_2(self, manifest):
		major, minor = (int(p) for p in manifest["blender_version_min"].split(".")[:2])
		assert (major, minor) >= (4, 2)

	def test_legacy_bl_info_supports_older_blender(self):
		"""
		bl_info must keep a lower floor than the manifest, or users below 4.2
		lose the legacy zip without gaining the extension.
		"""
		assert blendiff.bl_info["blender"] < (4, 2, 0)

	def test_permissions_are_declared_with_reasons(self, manifest):
		permissions = manifest.get("permissions", {})
		assert "files" in permissions, "BlenDiff writes sidecars; declare it"
		for name, reason in permissions.items():
			assert reason, f"permission {name!r} needs a justification"
			assert len(reason) <= 64, f"permission {name!r} reason too long"

	def test_no_network_permission_claimed(self, manifest):
		"""BlenDiff makes no network calls; claiming it would fail review."""
		assert "network" not in manifest.get("permissions", {})

	def test_build_excludes_tests_and_caches(self, manifest):
		patterns = manifest.get("build", {}).get("paths_exclude_pattern", [])
		joined = " ".join(patterns)
		assert "tests" in joined and "__pycache__" in joined


class TestBlInfoIsParseableWithoutImporting:
	"""
	bl_info must survive the way Blender actually reads it.

	Every other test here reads `blendiff.bl_info` from the imported module,
	which is not how Blender gets at it. addon_utils never imports an addon to
	build the Add-ons list: it parses the source file and runs ast.literal_eval
	on the bl_info assignment. Anything that is not a literal makes that call
	raise, addon_utils skips the module, and the addon vanishes from the list
	with no error the user can see.

	That is what happened when bl_info's version was computed from __version__.
	The addon still imported, still registered, and every unit test passed,
	while being impossible to enable from the interface. These tests parse the
	file the same way Blender does so the failure surfaces here instead.
	"""

	@pytest.fixture(scope="class")
	def parsed_bl_info(self):
		import ast

		path = os.path.join(os.path.dirname(__file__), "..", "blendiff", "__init__.py")
		with open(path, encoding="utf-8") as handle:
			tree = ast.parse(handle.read())

		for node in tree.body:
			if not isinstance(node, ast.Assign):
				continue
			for target in node.targets:
				if isinstance(target, ast.Name) and target.id == "bl_info":
					return ast.literal_eval(node.value)
		pytest.fail("bl_info assignment not found in blendiff/__init__.py")

	def test_bl_info_is_a_literal(self, parsed_bl_info):
		"""Fails with ValueError if any field is computed rather than written out."""
		assert parsed_bl_info["name"] == "BlenDiff"

	def test_parsed_version_matches_dunder_version(self, parsed_bl_info):
		expected = tuple(int(part) for part in blendiff.__version__.split("."))
		assert parsed_bl_info["version"] == expected, (
			"bl_info['version'] and __version__ have drifted; "
			"bl_info must repeat the version as a literal tuple"
		)

	def test_parsed_bl_info_matches_imported(self, parsed_bl_info):
		assert parsed_bl_info == blendiff.bl_info


class TestLicenseTextIsShipped:

	@staticmethod
	def _read(*parts):
		path = os.path.join(os.path.dirname(__file__), "..", *parts)
		with open(path, encoding="utf-8") as handle:
			return handle.read()

	def test_license_ships_inside_the_package(self):
		text = self._read("blendiff", "LICENSE")
		assert "GNU GENERAL PUBLIC LICENSE" in text
		assert "Version 3" in text

	def test_packaged_license_matches_the_repository_root(self):
		assert self._read("blendiff", "LICENSE") == self._read("LICENSE"), (
			"blendiff/LICENSE has drifted from the root LICENSE; they must be "
			"the same text"
		)

	def test_license_is_not_excluded_from_the_build(self, manifest):
		patterns = manifest.get("build", {}).get("paths_exclude_pattern", [])
		assert not any("LICENSE" in p.upper() for p in patterns)
