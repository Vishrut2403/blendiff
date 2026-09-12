"""
tests/test_no_external_programs.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
BlenDiff must run on Blender alone.

Why this file exists
--------------------
The Extensions Platform declined the first submission because
``storage/sidecar.py`` ran ``git rev-parse`` to stamp snapshots with the short
HEAD hash of the repository containing the .blend. Terms of service 5.2 is
explicit that an extension may not need anything installed beyond Blender
itself, and it closes the obvious escape route::

    even if those features are considered optional

So the usual defence, that the call was wrapped in try/except and degraded to
None when git was absent, does not apply. Shelling out at all is the problem.

Nothing in the review checklist I worked through beforehand would have caught
it either. I checked for network access, for ``__file__`` misuse and for
``sys.path`` manipulation, and never looked for a subprocess. This test is that
missing check, written so the next one fails here rather than in review.

What counts as a violation
--------------------------
Any means of starting another program: the ``subprocess`` module, the older
``os.system`` and ``os.popen``, ``os.exec*`` and ``os.spawn*``, and
``shutil.which``, which has no purpose except to look for an executable that
may not be there.

The source is parsed rather than searched for text, so the same words in a
docstring or a comment, where this one is discussed at length, are not
findings.
"""

import ast
import os

import pytest

PACKAGE_ROOT = os.path.join(os.path.dirname(__file__), "..", "blendiff")

#: Modules that exist to run another program.
FORBIDDEN_MODULES = {"subprocess"}

#: Callables that start or locate an external program.
FORBIDDEN_CALLS = {
	"os.system",
	"os.popen",
	"os.spawnl", "os.spawnle", "os.spawnlp", "os.spawnlpe",
	"os.spawnv", "os.spawnve", "os.spawnvp", "os.spawnvpe",
	"os.execl", "os.execle", "os.execlp", "os.execlpe",
	"os.execv", "os.execve", "os.execvp", "os.execvpe",
	"shutil.which",
}


def _python_files():
	for dirpath, dirnames, filenames in os.walk(PACKAGE_ROOT):
		dirnames[:] = [d for d in dirnames if d != "__pycache__"]
		for filename in sorted(filenames):
			if filename.endswith(".py"):
				yield os.path.join(dirpath, filename)


def _dotted(node):
	"""Render an attribute chain such as os.path.isdir back into a string."""
	parts = []
	while isinstance(node, ast.Attribute):
		parts.append(node.attr)
		node = node.value
	if isinstance(node, ast.Name):
		parts.append(node.id)
		return ".".join(reversed(parts))
	return None


def _violations(path):
	with open(path, encoding="utf-8") as handle:
		tree = ast.parse(handle.read(), filename=path)

	found = []
	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			for alias in node.names:
				root = alias.name.split(".")[0]
				if root in FORBIDDEN_MODULES:
					found.append((node.lineno, f"import {alias.name}"))
		elif isinstance(node, ast.ImportFrom):
			root = (node.module or "").split(".")[0]
			if root in FORBIDDEN_MODULES:
				found.append((node.lineno, f"from {node.module} import ..."))
		elif isinstance(node, ast.Call):
			name = _dotted(node.func)
			if name in FORBIDDEN_CALLS:
				found.append((node.lineno, f"{name}(...)"))
	return found


class TestNothingRunsAnExternalProgram:

	def test_package_starts_no_subprocesses(self):
		offenders = []
		for path in _python_files():
			for lineno, what in _violations(path):
				rel = os.path.relpath(path, os.path.join(PACKAGE_ROOT, ".."))
				offenders.append(f"{rel}:{lineno}  {what}")

		assert not offenders, (
			"BlenDiff must depend on nothing but Blender. The Extensions "
			"Platform rejects an extension that needs other software "
			"installed, even for an optional feature:\n  "
			+ "\n  ".join(offenders)
		)

	def test_the_check_actually_detects_a_subprocess(self, tmp_path):
		"""A guard on the guard, so this cannot quietly start passing everything."""
		sample = tmp_path / "sample.py"
		sample.write_text(
			"import subprocess\n"
			"import os\n"
			"def f():\n"
			"    subprocess.run(['git', 'rev-parse', 'HEAD'])\n"
			"    os.system('git status')\n"
			'"""import subprocess in a docstring is not a finding"""\n'
		)
		found = _violations(str(sample))
		kinds = {what for _lineno, what in found}
		assert "import subprocess" in kinds
		assert "os.system(...)" in kinds

	def test_docstrings_and_comments_are_not_findings(self, tmp_path):
		sample = tmp_path / "clean.py"
		sample.write_text(
			'"""This module once called subprocess.run(["git", ...]) and no longer does."""\n'
			"# os.system was removed too\n"
			"import os\n"
			"def f():\n"
			"    return os.path.isdir('/tmp')\n"
		)
		assert _violations(str(sample)) == []
