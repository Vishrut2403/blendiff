"""
tests/integration/test_blender_integration.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
pytest wrapper that runs the in-Blender integration suite.

The real tests live in ``run_in_blender.py`` and execute inside Blender's own
Python, which is the only place ``bpy`` exists. This module locates a Blender
binary, runs that script headlessly, and reports the outcome as ordinary pytest
results — so ``pytest tests/`` covers the extractor too when Blender is present,
and skips cleanly when it is not.

Point ``BLENDER_BINARY`` at a specific build to test against several versions.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPT = os.path.join(_HERE, "run_in_blender.py")
_ADDON_SCRIPT = os.path.join(_HERE, "run_addon_in_blender.py")
_REPO_ROOT = os.path.dirname(os.path.dirname(_HERE))

#: Markers the in-Blender runners print so results survive Blender's own noise.
_RESULT_PREFIX = "BLENDIFF_RESULT "
_ADDON_RESULT_PREFIX = "BLENDIFF_ADDON_RESULT "

#: Blender start-up plus scene building; generous so a slow CI runner does not
#: produce a flaky failure.
_TIMEOUT_SECONDS = 600


def _find_blender() -> str | None:
	"""Locate a Blender binary, preferring an explicit override."""
	explicit = os.environ.get("BLENDER_BINARY")
	if explicit:
		return explicit if os.path.exists(explicit) else None
	return shutil.which("blender")


BLENDER = _find_blender()

requires_blender = pytest.mark.skipif(
	BLENDER is None,
	reason="Blender not found; set BLENDER_BINARY to run integration tests",
)


def _run_suite(script: str = None, prefix: str = None) -> dict:
	"""Run one in-Blender suite and return its parsed result."""
	script = script or _SCRIPT
	prefix = prefix or _RESULT_PREFIX
	completed = subprocess.run(
		[
			BLENDER,
			"--background",
			"--factory-startup",  # ignore the user's addons and preferences
			"--python", script,
		],
		cwd=_REPO_ROOT,
		capture_output=True,
		text=True,
		timeout=_TIMEOUT_SECONDS,
	)

	for line in completed.stdout.splitlines():
		if line.startswith(prefix):
			payload = json.loads(line[len(prefix):])
			payload["output"] = completed.stdout
			return payload

	raise AssertionError(
		"Integration runner produced no result line.\n"
		f"exit code: {completed.returncode}\n"
		f"stdout:\n{completed.stdout[-4000:]}\n"
		f"stderr:\n{completed.stderr[-4000:]}"
	)


@pytest.fixture(scope="module")
def suite_result() -> dict:
	"""Run the in-Blender suite once and share the result across tests."""
	return _run_suite()


@pytest.mark.integration
@requires_blender
class TestBlenderIntegration:
	def test_suite_runs(self, suite_result):
		assert suite_result["passed"] > 0, "no integration tests ran"

	def test_no_failures(self, suite_result):
		failures = suite_result["failures"]
		assert not failures, (
			"in-Blender integration failures: "
			+ ", ".join(failures)
			+ "\n\n"
			+ suite_result["output"][-6000:]
		)

	def test_extractor_coverage_is_meaningful(self, suite_result):
		"""
		Guards against the suite silently shrinking.

		These tests are the only coverage the bpy-facing extractor has, so a
		drop in count is worth failing over rather than quietly accepting.
		"""
		total = suite_result["passed"] + suite_result["failed"]
		assert total >= 55, f"integration suite unexpectedly small: {total} tests"


@pytest.fixture(scope="module")
def addon_result() -> dict:
	"""Run the addon end-to-end suite once and share it across tests."""
	return _run_suite(_ADDON_SCRIPT, _ADDON_RESULT_PREFIX)


@pytest.mark.integration
@requires_blender
class TestAddonEndToEnd:
	"""
	The operators, panels, Applier and CLI, driven inside real Blender.

	This is the only place the merge Applier runs against actual bpy — every
	applier unit test uses a fake — so a regression here would otherwise reach
	users before anything caught it.
	"""

	def test_suite_runs(self, addon_result):
		assert addon_result["passed"] > 0, "no addon checks ran"

	def test_no_failures(self, addon_result):
		failures = addon_result["failures"]
		assert not failures, (
			"addon end-to-end failures: " + ", ".join(failures)
			+ "\n\n" + addon_result["output"][-6000:]
		)

	def test_coverage_is_meaningful(self, addon_result):
		total = addon_result["passed"] + addon_result["failed"]
		assert total >= 50, f"addon suite unexpectedly small: {total} checks"
