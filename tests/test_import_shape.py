"""
tests/test_import_shape.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Imports must not name the package absolutely.

BlenDiff ships in three shapes, and the package name differs in each:

* pip install         -> ``blendiff``
* legacy addon zip    -> ``blendiff``
* Blender extension   -> ``bl_ext.<repository>.blendiff``

An absolute ``from blendiff.data_model import ...`` resolves in the first two
and raises ModuleNotFoundError in the third. Six modules under diff_engine did
exactly that. Everything passed: the unit suite imports the top-level package,
where absolute imports are correct by definition, and the in-Blender tests
loaded the source directory rather than an installed extension. The failure
appeared only when the built zip was installed the way the Extensions Platform
installs it, and even then it surfaced as "UI modules failed to import" with no
mention of which module or why.

The rule is that nothing inside the package may refer to the package by name.
This test reads the source rather than importing it, because importing is the
one thing that cannot detect the problem.
"""

import ast
import os

import pytest

PACKAGE_ROOT = os.path.join(os.path.dirname(__file__), "..", "blendiff")
PACKAGE_NAME = "blendiff"


def _python_files():
	for dirpath, dirnames, filenames in os.walk(PACKAGE_ROOT):
		dirnames[:] = [d for d in dirnames if d != "__pycache__"]
		for filename in filenames:
			if filename.endswith(".py"):
				yield os.path.join(dirpath, filename)


def _absolute_self_imports(path):
	"""
	Import statements in one file that name the package absolutely.

	Parsed rather than grepped so that the same text inside a docstring or a
	comment, where it is documenting the public pip API, is not a finding.
	"""
	with open(path, encoding="utf-8") as handle:
		tree = ast.parse(handle.read(), filename=path)

	found = []
	for node in ast.walk(tree):
		if isinstance(node, ast.ImportFrom):
			# level > 0 is a relative import, which is what we want.
			if node.level == 0 and node.module and (
				node.module == PACKAGE_NAME
				or node.module.startswith(PACKAGE_NAME + ".")
			):
				found.append((node.lineno, f"from {node.module} import ..."))
		elif isinstance(node, ast.Import):
			for alias in node.names:
				if alias.name == PACKAGE_NAME or alias.name.startswith(PACKAGE_NAME + "."):
					found.append((node.lineno, f"import {alias.name}"))
	return found


class TestNoAbsoluteSelfImports:

	def test_no_module_imports_the_package_by_name(self):
		offenders = []
		for path in sorted(_python_files()):
			for lineno, statement in _absolute_self_imports(path):
				rel = os.path.relpath(path, os.path.join(PACKAGE_ROOT, ".."))
				offenders.append(f"{rel}:{lineno}  {statement}")

		assert not offenders, (
			"These imports name the package absolutely, which breaks when "
			"BlenDiff is installed as an extension under bl_ext.<repo>.blendiff. "
			"Use a relative import instead:\n  " + "\n  ".join(offenders)
		)

	def test_the_check_can_tell_relative_from_absolute(self, tmp_path):
		"""A guard on the guard, so a parser change cannot silently pass everything."""
		sample = tmp_path / "sample.py"
		sample.write_text(
			"from blendiff.data_model.diff import PropertyChange\n"
			"from ..data_model.diff import PropertyChange\n"
			'"""from blendiff.cli.api import compare_snapshots"""\n'
		)
		found = _absolute_self_imports(str(sample))
		assert len(found) == 1, f"expected exactly the absolute import, got {found}"
		assert found[0][0] == 1
