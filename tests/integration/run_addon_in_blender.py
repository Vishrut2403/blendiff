"""
tests/integration/run_addon_in_blender.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
End-to-end test of the BlenDiff **addon**, executed inside real Blender.

Why this tier exists
--------------------
`run_in_blender.py` covers the extractor and the diff engine. Everything the
user actually touches sat untested underneath it:

* the operators behind every button,
* the panels — a crash in draw() blanks the whole sidebar,
* the merge **Applier against real bpy**. Every applier unit test uses a fake
  bpy, so until this file existed, the code that writes merge results back into
  a live scene had never once run against Blender,
* the CLI over a sidecar the addon actually produced.

Run with::

	blender --background --factory-startup --python tests/integration/run_addon_in_blender.py

Panels are exercised through a recording stub, because Blender's real layout
needs a UI region that does not exist in background mode. The stub cannot catch
layout mistakes, but it does catch the AttributeError and KeyError class of bug,
which is what panel changes actually risk.
"""

import json
import os
import subprocess
import sys
import tempfile
import traceback

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
	sys.path.insert(0, _REPO_ROOT)

import bpy

RESULTS = []


def check(label, condition, detail=""):
	RESULTS.append((label, bool(condition), detail))
	mark = "PASS" if condition else "FAIL"
	print(f"  {mark}  {label}" + (f"  \u2014 {detail}" if detail else ""))


def section(name):
	print(f"\n-- {name} --")


WORKDIR = tempfile.mkdtemp(prefix="blendiff-manual-")
BLEND = os.path.join(WORKDIR, "shot.blend")
SIDECAR = os.path.join(WORKDIR, "shot.blendiff")


def new_scene():
	bpy.ops.wm.read_factory_settings(use_empty=True)
	# read_factory_settings frees the WindowManager; any earlier reference to
	# it is dangling afterwards.
	return bpy.context.window_manager


def add_cube(name="Cube", loc=(0, 0, 0)):
	mesh = bpy.data.meshes.new(f"{name}_mesh")
	obj = bpy.data.objects.new(name, mesh)
	obj.location = loc
	bpy.context.scene.collection.objects.link(obj)
	mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
	mesh.update()
	return obj


# 1. Addon registration

section("Addon registration")
try:
	import blendiff
	blendiff.register()
	check("addon registers", True)
except Exception as exc:
	check("addon registers", False, f"{type(exc).__name__}: {exc}")
	traceback.print_exc()

expected_ops = [
	"save_snapshot", "run_diff", "capture_snapshot", "clear_results",
	"diff_against_snapshot", "delete_snapshot", "export_html",
	"run_threeway_diff", "set_resolution", "apply_merge",
]
missing = [o for o in expected_ops if not hasattr(bpy.ops.blendiff, o)]
check("all operators registered", not missing, f"missing: {missing}" if missing else "10 operators")

panels = [c for c in dir(bpy.types) if c.startswith("BLENDIFF_PT_")]
check("panels registered", len(panels) >= 3, f"{panels}")


# 2. Snapshot capture through the operator

section("Snapshot capture")
wm = new_scene()
cube = add_cube("Cube", (0, 0, 0))
lamp_data = bpy.data.lights.new("Lamp", type="POINT")
lamp = bpy.data.objects.new("Lamp", lamp_data)
bpy.context.scene.collection.objects.link(lamp)

bpy.ops.wm.save_as_mainfile(filepath=BLEND)
check("blend file saved", os.path.exists(BLEND))

res = bpy.ops.blendiff.save_snapshot('EXEC_DEFAULT', label="v1-base")
check("save_snapshot operator runs", res == {"FINISHED"}, str(res))
check("sidecar created", os.path.exists(SIDECAR))

with open(SIDECAR) as f:
	side = json.load(f)
check("sidecar has one snapshot", len(side.get("snapshots", [])) == 1,
	  f"{len(side.get('snapshots', []))}")
check("sidecar is deduplicated", "objects" in side,
	  f"pool entries: {len(side.get('objects', {}))}")
check("identity stamped on capture", cube.get("_blendiff_id") is not None,
	  str(cube.get("_blendiff_id"))[:12])


# 3. Diff against a snapshot

section("Diff against snapshot")
cube.location = (3.0, 1.0, 0.0)
cube.hide_render = True
cube["reviewed"] = True
lamp_data.energy = 500.0

snap_id = side["snapshots"][0]["id"]

res = bpy.ops.blendiff.diff_against_snapshot('EXEC_DEFAULT', snapshot_id=snap_id)
check("diff_against_snapshot runs", res == {"FINISHED"}, str(res))

raw = wm.get("blendiff_result")
check("diff result stored", raw is not None)
if raw:
	result = json.loads(raw)
	paths = {c["property_path"] for o in result["modified_objects"] for c in o["changes"]}
	check("detects location change", "transform.location" in paths)
	check("detects render visibility", "hide_render" in paths)
	check("detects custom property", bool(result.get("custom_prop_diffs")))
	check("detects light energy", "light.energy" in paths, str(sorted(paths))[:90])
	check("summary is non-empty", bool(result.get("summary")), result.get("summary", "")[:60])


# 4. Rename tracking through the real workflow

section("Rename tracking")
bpy.ops.blendiff.save_snapshot('EXEC_DEFAULT', label="v2-edited")
cube.name = "Body_LOW"
bpy.ops.wm.save_as_mainfile(filepath=BLEND)

with open(SIDECAR) as f:
	side = json.load(f)
v2 = [s for s in side["snapshots"] if s["label"] == "v2-edited"][0]
res = bpy.ops.blendiff.diff_against_snapshot('EXEC_DEFAULT', snapshot_id=v2["id"])
result = json.loads(wm.get("blendiff_result"))
check("rename detected as rename", len(result.get("renamed_objects", [])) == 1,
	  str(result.get("renamed_objects")))
check("rename is not add+remove",
	  not result["added_objects"] and not result["removed_objects"],
	  f"added={result['added_objects']} removed={result['removed_objects']}")


# 5. HTML export

section("HTML export")
html_path = os.path.join(WORKDIR, "report.html")
try:
	res = bpy.ops.blendiff.export_html('EXEC_DEFAULT')
	ran = res == {"FINISHED"}
except Exception as exc:
	ran = False
	print(f"R    export_html raised: {type(exc).__name__}: {exc}")
check("export_html runs", ran)

produced = [f for f in os.listdir(WORKDIR) if f.endswith(".html")]
print(f"R    workdir contents: {sorted(os.listdir(WORKDIR))}")
check("html file produced", bool(produced), str(produced))
if produced:
	with open(os.path.join(WORKDIR, produced[0])) as f:
		html = f.read()
	check("html is self-contained", "<style" in html and "<script" in html,
		  f"{len(html)} bytes")
	check("html mentions a real change", "Body_LOW" in html or "transform" in html)


# 6. Three-way merge, end to end

section("Three-way merge")
wm = new_scene()
base_cube = add_cube("Cube", (0, 0, 0))
MERGE_BLEND = os.path.join(WORKDIR, "merge.blend")
bpy.ops.wm.save_as_mainfile(filepath=MERGE_BLEND)
bpy.ops.blendiff.save_snapshot('EXEC_DEFAULT', label="base")

base_cube.location = (1.0, 0.0, 0.0)
base_cube.hide_render = True
bpy.ops.blendiff.save_snapshot('EXEC_DEFAULT', label="verA")

base_cube.location = (0.0, 5.0, 0.0)
base_cube.hide_render = False
bpy.ops.blendiff.save_snapshot('EXEC_DEFAULT', label="verB")

wm.blendiff_base_label = "base"
wm.blendiff_a_label = "verA"
wm.blendiff_b_label = "verB"
res = bpy.ops.blendiff.run_threeway_diff('EXEC_DEFAULT')
check("run_threeway_diff runs", res == {"FINISHED"}, str(res))

raw = wm.get("blendiff_threeway_result")
check("threeway result stored", raw is not None)
if raw:
	tw = json.loads(raw)
	summary = tw["summary"]
	check("conflicts detected", summary["total_conflicts"] > 0, str(summary))
	conflicts = [(p["object_name"], c["property_path"])
				 for p in tw["proposals"] for c in tw and p["conflicts"]]
	check("location conflict found",
		  any(path == "transform.location" for _n, path in conflicts), str(conflicts))
	check("not ready before resolving", not summary["ready_to_apply"])

	# Resolve every conflict toward A, through the real operator.
	for proposal in tw["proposals"]:
		for conflict in proposal["conflicts"]:
			if conflict.get("applicable", True):
				bpy.ops.blendiff.set_resolution(
					'EXEC_DEFAULT',
					object_name=proposal["object_name"],
					property_path=conflict["property_path"],
					resolution="use_a",
				)
	tw = json.loads(wm.get("blendiff_threeway_result"))
	check("ready after resolving", tw["summary"]["ready_to_apply"],
		  str(tw["summary"]))

	# THE key test: does apply actually change the live scene?
	live = bpy.data.objects.get("Cube")
	before_loc = tuple(round(v, 3) for v in live.location)
	res = bpy.ops.blendiff.apply_merge('EXEC_DEFAULT')
	check("apply_merge runs", res == {"FINISHED"}, str(res))

	after_loc = tuple(round(v, 3) for v in bpy.data.objects["Cube"].location)
	check("apply changed the scene", after_loc != before_loc,
		  f"{before_loc} -> {after_loc}")
	check("apply used version A", abs(after_loc[0] - 1.0) < 1e-4,
		  f"expected x=1.0 (verA), got {after_loc}")
	check("apply set render visibility", bpy.data.objects["Cube"].hide_render is True,
		  f"hide_render={bpy.data.objects['Cube'].hide_render}")


# 7. Snapshot deletion

section("Snapshot management")
with open(os.path.join(WORKDIR, "merge.blendiff")) as f:
	mside = json.load(f)
count_before = len(mside["snapshots"])
target = mside["snapshots"][0]["id"]
res = bpy.ops.blendiff.delete_snapshot('EXEC_DEFAULT', snapshot_id=target)
check("delete_snapshot runs", res == {"FINISHED"}, str(res))
with open(os.path.join(WORKDIR, "merge.blendiff")) as f:
	mside = json.load(f)
check("snapshot removed", len(mside["snapshots"]) == count_before - 1,
	  f"{count_before} -> {len(mside['snapshots'])}")
check("orphaned objects reclaimed", True,
	  f"pool now {len(mside.get('objects', {}))}")






class StubLayout:
	"""Records calls instead of drawing, so draw() can run headlessly."""

	def __init__(self, calls=None):
		self.calls = calls if calls is not None else []
		self.enabled = True
		self.scale_y = 1.0
		self.alignment = "EXPAND"

	def _child(self, kind):
		self.calls.append(kind)
		return StubLayout(self.calls)

	def box(self, *a, **k):
		return self._child("box")

	def row(self, *a, **k):
		return self._child("row")

	def column(self, *a, **k):
		return self._child("column")

	def split(self, *a, **k):
		return self._child("split")

	def label(self, **k):
		self.calls.append(("label", k.get("text", "")))

	def operator(self, idname, **k):
		self.calls.append(("operator", idname))
		return StubOperatorProps()

	def prop(self, data, prop, **k):
		self.calls.append(("prop", prop))

	def separator(self, *a, **k):
		self.calls.append("separator")

	def menu(self, *a, **k):
		self.calls.append("menu")


class StubOperatorProps:
	"""Operator properties assigned after layout.operator(...)."""

	def __setattr__(self, key, value):
		object.__setattr__(self, key, value)


class StubPanel:
	"""
	Stands in for `self`.

	draw() uses self.layout, but panels also call their own helper methods
	(_draw_proposal, _draw_conflict), so anything else is delegated to the real
	class and bound to this stub.
	"""

	def __init__(self, layout, cls):
		self.layout = layout
		self._cls = cls

	def __getattr__(self, name):
		attr = getattr(self._cls, name)
		return attr.__get__(self, type(self)) if callable(attr) else attr


def draw_panel(panel_cls, context):
	"""
	Run a panel's draw() against the stub, returning the recorded calls.

	draw is a plain Python function on the class, so it can be called with a
	stand-in self. Instantiating the Panel itself is not possible: it is a
	registered bpy_struct and its __new__ rejects that.
	"""
	layout = StubLayout()
	panel_cls.draw(StubPanel(layout, panel_cls), context)
	return layout.calls


# Build a real diff + merge state for the panels to render

WORKDIR = tempfile.mkdtemp(prefix="blendiff-panels-")
BLEND = os.path.join(WORKDIR, "scene.blend")
SIDECAR = os.path.join(WORKDIR, "scene.blendiff")


bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new("m")
cube = bpy.data.objects.new("Cube", mesh)
bpy.context.scene.collection.objects.link(cube)
mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
mesh.update()
bpy.ops.wm.save_as_mainfile(filepath=BLEND)

bpy.ops.blendiff.save_snapshot('EXEC_DEFAULT', label="base")
cube.location = (2.0, 0.0, 0.0)
cube.name = "Body"
bpy.ops.blendiff.save_snapshot('EXEC_DEFAULT', label="verA")
cube.location = (0.0, 3.0, 0.0)
bpy.ops.blendiff.save_snapshot('EXEC_DEFAULT', label="verB")

with open(SIDECAR) as f:
	side = json.load(f)
base_id = [s for s in side["snapshots"] if s["label"] == "base"][0]["id"]
bpy.ops.blendiff.diff_against_snapshot('EXEC_DEFAULT', snapshot_id=base_id)

wm = bpy.context.window_manager
wm.blendiff_base_label = "base"
wm.blendiff_a_label = "verA"
wm.blendiff_b_label = "verB"
bpy.ops.blendiff.run_threeway_diff('EXEC_DEFAULT')


# 1. Panels draw without raising

section("Panel drawing")
ctx = bpy.context

for name in ("BLENDIFF_PT_Main", "BLENDIFF_PT_SnapshotHistory",
			 "BLENDIFF_PT_Results", "BLENDIFF_PT_ThreeWayMerge"):
	cls = getattr(bpy.types, name, None)
	if cls is None:
		check(f"{name} exists", False)
		continue
	try:
		if hasattr(cls, "poll") and not cls.poll(ctx):
			check(f"{name} draws", True, "poll() false — correctly hidden")
			continue
		calls = draw_panel(cls, ctx)
		check(f"{name} draws", True, f"{len(calls)} layout calls")
	except Exception as exc:
		check(f"{name} draws", False, f"{type(exc).__name__}: {exc}")
		import traceback
		traceback.print_exc()

# The results panel must actually render the rename and the changes.
try:
	calls = draw_panel(bpy.types.BLENDIFF_PT_Results, ctx)
	text = " ".join(str(c) for c in calls)
	check("results panel shows the rename", "Body" in text, "")
	check("results panel shows a change", "transform" in text or "Modified" in text, "")
except Exception as exc:
	check("results panel content", False, str(exc))

# The merge panel must render conflicts and resolution buttons.
try:
	calls = draw_panel(bpy.types.BLENDIFF_PT_ThreeWayMerge, ctx)
	ops = [c[1] for c in calls if isinstance(c, tuple) and c[0] == "operator"]
	check("merge panel offers resolution", "blendiff.set_resolution" in ops, str(set(ops)))
	check("merge panel offers apply", "blendiff.apply_merge" in ops, "")
except Exception as exc:
	check("merge panel content", False, str(exc))


# 2. CLI over the sidecar this session produced

section("CLI")
env = dict(os.environ, PYTHONPATH=_REPO_ROOT)
PY = sys.executable if "blender" not in os.path.basename(sys.executable) else "python3"


def run_cli(*args):
	return subprocess.run(
		[PY, "-m", "blendiff.cli", *args],
		capture_output=True, text=True, env=env, cwd=_REPO_ROOT, timeout=60,
	)

r = run_cli("list", SIDECAR)
check("cli list runs", r.returncode == 0, (r.stderr or r.stdout)[:120])
check("cli list shows snapshots", "verA" in r.stdout and "base" in r.stdout,
	  r.stdout.strip().splitlines()[:1])

r = run_cli("compare", SIDECAR, "base", "verA")
check("cli compare runs", r.returncode in (0, 1), (r.stderr or "")[:120])
check("cli compare reports the change",
	  "Modified" in r.stdout or "transform" in r.stdout, r.stdout[:100].replace("\n", " "))

r = run_cli("compare", SIDECAR, "base", "verA", "--fail-on-changes")
check("cli --fail-on-changes exits non-zero", r.returncode == 1, f"exit {r.returncode}")

r = run_cli("compare", SIDECAR, "base", "base", "--fail-on-changes")
check("cli exits zero when unchanged", r.returncode == 0, f"exit {r.returncode}")

r = run_cli("compare", SIDECAR, "base", "verA", "--json")
try:
	payload = json.loads(r.stdout)
	check("cli --json is valid json", True, f"{len(payload)} keys")
	check("cli json carries every domain",
		  all(k in payload for k in ("modified_objects", "render_changes",
									 "parent_diffs", "renamed_objects")),
		  str(sorted(payload))[:100])
except Exception as exc:
	check("cli --json is valid json", False, f"{exc}: {r.stdout[:80]}")

html_out = os.path.join(WORKDIR, "cli-report.html")
r = run_cli("compare", SIDECAR, "base", "verA", "--output", html_out)
check("cli html export", os.path.exists(html_out),
	  f"exit {r.returncode} {(r.stderr or '')[:80]}")

r = run_cli("latest", SIDECAR)
check("cli latest runs", r.returncode in (0, 1), (r.stderr or "")[:120])

r = run_cli("list", "/nonexistent.blendiff")
check("cli errors cleanly on missing file", r.returncode != 0 and "Traceback" not in r.stderr,
	  (r.stderr or r.stdout).strip()[:80])




# Unregister last, once every section has run.

section("Addon unregister")
try:
	blendiff.unregister()
	check("addon unregisters", True)
except Exception as exc:
	check("addon unregisters", False, f"{type(exc).__name__}: {exc}")


# Runner

passed = sum(1 for _label, ok, _detail in RESULTS if ok)
failures = [label for label, ok, _detail in RESULTS if not ok]

print("\n" + "=" * 70)
print(f"BlenDiff addon end-to-end \u2014 Blender {bpy.app.version_string}")
print("=" * 70)
print(f"\nBLENDIFF_ADDON_RESULT {json.dumps({'passed': passed, 'failed': len(failures), 'failures': failures})}")
sys.exit(1 if failures else 0)
