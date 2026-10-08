import json
import os

import bpy

from ..extractor.scene_extractor import SceneExtractor
from ..serializer.scene_serializer import SceneSerializer
from ..diff_engine.diff_engine import DiffEngine
from ..data_model.scene import SerializedScene
from ..storage.sidecar import SidecarManager
from ..merge_engine.merge_engine import MergeEngine
from ..export.diff_result import diff_to_dict
from .registration import register_classes, unregister_classes


# Helpers

def _orphaned_history_warning(context, mgr) -> str | None:
	"""
	Detect a .blend that has been separated from its sidecar.

	Objects keep their BlenDiff id inside the .blend, so stamps present with no
	sidecar beside the file proves history existed and is not here — almost
	always a .blend moved or renamed without its .blendiff. Reporting that is
	the difference between "you have no snapshots yet" and "your snapshots are
	in the folder you moved this from", which otherwise look identical.
	"""
	from ..extractor.identity import scene_has_identities

	if mgr.sidecar_path and os.path.exists(mgr.sidecar_path):
		return None
	if not scene_has_identities(context.scene):
		return None

	return (
		"BlenDiff: this file has snapshot history, but no "
		f"{os.path.basename(mgr.sidecar_path or '.blendiff')} was found beside "
		"it. If you moved or renamed the .blend, bring its .blendiff along."
	)


def _unrelated_history_warning(context, mgr) -> str | None:
	"""
	Detect a sidecar whose history belongs to a different scene.

	The sidecar is keyed by the .blend's path, so saving a new scene over a
	name that was used before silently adopts that name's history. Saving an
	untitled scene as a file somebody already had is enough to do it, and the
	result looks entirely normal: a populated Snapshot History that has nothing
	to do with what is on screen. Diffing against it compares two unrelated
	scenes and reports every object as added and removed.

	Shared object identities are what tells the two apart. Every snapshot
	stamps the objects it captured, so a scene that has ever been part of this
	history carries at least one of its ids. No overlap at all means the
	history came from somewhere else.

	A warning rather than a refusal. Replacing every object in a scene is a
	legitimate thing to do, and it looks identical from here, so the user is
	told and left to decide.
	"""
	from ..extractor.identity import read_id

	known = mgr.latest_object_ids()
	if not known:
		return None

	recorded = {value for value in known.values() if value}
	if not recorded:
		return None

	try:
		present = {read_id(obj) for obj in context.scene.objects}
	except Exception:  # pragma: no cover - defensive
		return None

	if present & recorded:
		return None

	return (
		f"BlenDiff: the {os.path.basename(mgr.sidecar_path or '.blendiff')} "
		"beside this file holds snapshots of a different scene. Saving over a "
		"name that was used before adopts its history. Delete those snapshots "
		"or save under another name."
	)


def _extract_current_scene(
	context,
	stamp_identity: bool = False,
	known_ids: dict | None = None,
) -> tuple[dict, str]:
	"""
	Serialise the current scene.

	``stamp_identity`` writes a persistent BlenDiff id to objects that lack
	one, so renames stay traceable across snapshots. It marks the .blend as
	modified, so only snapshot capture — which the user explicitly asked for —
	enables it; running a diff must never dirty the file.
	"""
	extractor = SceneExtractor()
	serializer = SceneSerializer()
	raw = extractor.extract(
		context, stamp_identity=stamp_identity, known_ids=known_ids,
	)
	scene: SerializedScene = serializer.serialize(raw)
	return scene, context.scene.name


def _get_sidecar(context) -> SidecarManager:
	return SidecarManager(bpy.data.filepath)


def _store_diff(context, before: dict, after: dict, title: str) -> dict:
	"""
	Compare two scene dicts and cache the result for the panel to draw.

	The dict is built by the shared converter, so the panel, the HTML report
	and the CLI all describe the same diff.
	"""
	diff = DiffEngine().compare(before, after)
	result = diff_to_dict(diff)

	wm = context.window_manager
	wm["blendiff_result"] = json.dumps(result)
	wm["blendiff_result_title"] = title
	return result


def _refresh_panels(context) -> None:
	"""
	Force the sidebar to redraw after the snapshot list changes.

	Every row's buttons carry their snapshot id baked in at draw time. Change
	the list without redrawing and those buttons keep pointing at what used to
	be there: deleting one snapshot left the next row sitting under the cursor
	still carrying the deleted id, so a second click reported "Snapshot not
	found". It looked like Blender needed a pause between deletes. It did not,
	it needed the panel to be told the list had changed.

	Every area is tagged rather than just the current one, because the panel
	can be open in more than one viewport and the stale rows are equally wrong
	in all of them.
	"""
	try:
		for window in context.window_manager.windows:
			for area in window.screen.areas:
				area.tag_redraw()
	except AttributeError:
		# No window manager in background runs, where there is nothing to draw.
		pass


def _run_diff_against_dict(context, snapshot_dict: dict, title: str = "") -> dict:
	"""
	Diff a stored snapshot against the live scene.

	Extraction here never stamps identities: running a diff must not modify
	the .blend.
	"""
	current_dict, _ = _extract_current_scene(context)
	return _store_diff(context, snapshot_dict, current_dict, title)


# Existing operators (preserved exactly)

class BLENDIFF_OT_CaptureSnapshot(bpy.types.Operator):
	"""Capture the current scene as Snapshot A (in-memory)"""
	bl_idname = "blendiff.capture_snapshot"
	bl_label = "Capture Snapshot A"
	bl_description = "Serialise the current scene state as the base for diffing"

	def execute(self, context):
		try:
			scene_dict, _ = _extract_current_scene(context)
			context.window_manager["blendiff_snapshot_a"] = json.dumps(scene_dict)
			self.report({"INFO"}, "BlenDiff: Snapshot A captured.")
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_RunDiff(bpy.types.Operator):
	"""Diff Snapshot A (in-memory) against the current scene"""
	bl_idname = "blendiff.run_diff"
	bl_label = "Run Diff"
	bl_description = "Compare Snapshot A to the current scene state"

	def execute(self, context):
		wm = context.window_manager
		if "blendiff_snapshot_a" not in wm:
			self.report({"ERROR"}, "BlenDiff: No Snapshot A found. Capture one first.")
			return {"CANCELLED"}

		try:
			snapshot_dict = json.loads(wm["blendiff_snapshot_a"])
			result = _run_diff_against_dict(
				context, snapshot_dict, "Snapshot A vs. the current scene",
			)
			self.report({"INFO"}, f"BlenDiff: {result['summary']}")
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_ClearResults(bpy.types.Operator):
	"""Clear all BlenDiff in-memory data"""
	bl_idname = "blendiff.clear_results"
	bl_label = "Clear Results"
	bl_description = "Clear snapshot A and diff results from memory"

	def execute(self, context):
		wm = context.window_manager
		for key in ("blendiff_snapshot_a", "blendiff_result", "blendiff_result_title"):
			if key in wm:
				del wm[key]
		self.report({"INFO"}, "BlenDiff: Cleared.")
		return {"FINISHED"}


# New sidecar operators

class BLENDIFF_OT_SaveSnapshot(bpy.types.Operator):
	"""Save current scene as a named snapshot to the .blendiff sidecar"""
	bl_idname = "blendiff.save_snapshot"
	bl_label = "Save Snapshot"
	bl_description = "Save a named, timestamped snapshot to the .blendiff file next to your .blend"

	label: bpy.props.StringProperty(
		name="Label",
		description="A short name for this snapshot (e.g. 'Before rigging')",
		default="",
	)

	def invoke(self, context, event):
		self.label = f"Snapshot {_get_sidecar(context).snapshot_count() + 1}"
		return context.window_manager.invoke_props_dialog(self)

	def draw(self, context):
		self.layout.prop(self, "label")

	def execute(self, context):
		mgr = _get_sidecar(context)

		if not mgr.is_available:
			self.report(
				{"ERROR"},
				"BlenDiff: Please save your .blend file before using snapshot history.",
			)
			return {"CANCELLED"}

		for warning in (
			_orphaned_history_warning(context, mgr),
			_unrelated_history_warning(context, mgr),
		):
			if warning:
				self.report({"WARNING"}, warning)

		label = self.label.strip() or f"Snapshot {mgr.snapshot_count() + 1}"

		try:
			# Capture is the one moment BlenDiff may write to the .blend:
			# stamping identities here is what lets later snapshots survive
			# a rename. Ids from the previous snapshot are reused where an
			# object has lost its stamp, so identity survives a session that
			# was closed without saving.
			scene_dict, scene_name = _extract_current_scene(
				context,
				stamp_identity=True,
				known_ids=mgr.latest_object_ids(),
			)
			snap = mgr.save_snapshot(label, scene_name, scene_dict)
			_refresh_panels(context)
			self.report({"INFO"}, f"BlenDiff: Saved snapshot '{snap.label}' ({snap.id[:8]})")
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_DiffAgainstSnapshot(bpy.types.Operator):
	"""Diff a sidecar snapshot against the current scene"""
	bl_idname = "blendiff.diff_against_snapshot"
	bl_label = "Diff Against This Snapshot"
	bl_description = "Compare this saved snapshot to the current scene"

	snapshot_id: bpy.props.StringProperty()

	def execute(self, context):
		if not self.snapshot_id:
			self.report({"ERROR"}, "BlenDiff: No snapshot ID provided.")
			return {"CANCELLED"}

		mgr = _get_sidecar(context)
		snap = mgr.get_snapshot(self.snapshot_id)

		if snap is None:
			self.report({"ERROR"}, f"BlenDiff: Snapshot {self.snapshot_id[:8]} not found.")
			return {"CANCELLED"}

		try:
			context.window_manager["blendiff_active_snapshot_label"] = snap.label
			context.window_manager["blendiff_active_snapshot_id"] = snap.id

			result = _run_diff_against_dict(
				context, snap.data, f"{snap.label} vs. the current scene",
			)
			self.report({"INFO"}, f"BlenDiff [{snap.label}]: {result['summary']}")
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_DiffTwoSnapshots(bpy.types.Operator):
	"""Compare two saved snapshots against each other"""
	bl_idname = "blendiff.diff_two_snapshots"
	bl_label = "Compare Snapshots"
	bl_description = (
		"Compare two saved snapshots, without involving the current scene"
	)

	def execute(self, context):
		wm = context.window_manager
		before_label = wm.blendiff_compare_from.strip()
		after_label = wm.blendiff_compare_to.strip()

		if not before_label or not after_label:
			self.report({"ERROR"}, "BlenDiff: Pick two snapshots to compare.")
			return {"CANCELLED"}
		if before_label == after_label:
			self.report({"ERROR"}, "BlenDiff: Pick two different snapshots.")
			return {"CANCELLED"}

		mgr = _get_sidecar(context)
		by_label = {snap.label: snap for snap in mgr.list_snapshots()}
		missing = [l for l in (before_label, after_label) if l not in by_label]
		if missing:
			self.report({"ERROR"}, f"BlenDiff: Snapshots not found: {', '.join(missing)}")
			return {"CANCELLED"}

		try:
			title = f"{before_label} to {after_label}"
			result = _store_diff(
				context,
				by_label[before_label].data,
				by_label[after_label].data,
				title,
			)
			# The per-snapshot highlight in the history list means "compared
			# against the scene", which this is not, so it is cleared.
			wm["blendiff_active_snapshot_id"] = ""
			wm["blendiff_active_snapshot_label"] = title
			self.report({"INFO"}, f"BlenDiff [{title}]: {result['summary']}")
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_RestoreSnapshot(bpy.types.Operator):
	"""Put the scene back the way this snapshot recorded it"""
	bl_idname = "blendiff.restore_snapshot"
	bl_label = "Restore This Snapshot"
	bl_description = (
		"Write this snapshot's values back over the current scene. "
		"Objects are not created or deleted"
	)

	snapshot_id: bpy.props.StringProperty()

	def invoke(self, context, event):
		# This overwrites the scene, so it asks first.
		return context.window_manager.invoke_confirm(self, event)

	def execute(self, context):
		from ..merge_engine.applier import Applier
		from ..merge_engine.restore import build_restore, unrestorable_objects

		mgr = _get_sidecar(context)
		snap = mgr.get_snapshot(self.snapshot_id) if self.snapshot_id else None
		if snap is None:
			self.report({"ERROR"}, "BlenDiff: Snapshot not found.")
			return {"CANCELLED"}

		try:
			current_dict, _ = _extract_current_scene(context)

			# Current scene first, snapshot second, so every change's
			# new_value is the value the snapshot holds.
			scene_diff = DiffEngine().compare(current_dict, snap.data)

			three_way = build_restore(scene_diff, snap.label)
			result = Applier().apply_all(three_way, context)

			# A restore is one step to undo, not one per property.
			bpy.ops.ed.undo_push(message=f"BlenDiff: restore '{snap.label}'")

			level = "WARNING" if (result.failed or result.skipped) else "INFO"
			self.report({level}, f"BlenDiff [{snap.label}]: {result.report_line()}")

			stranded = unrestorable_objects(scene_diff)
			if stranded["missing"]:
				self.report({"WARNING"}, (
					f"BlenDiff: {len(stranded['missing'])} object(s) in the snapshot "
					f"no longer exist and cannot be rebuilt: "
					f"{', '.join(stranded['missing'][:5])}"
				))
			if stranded["extra"]:
				self.report({"WARNING"}, (
					f"BlenDiff: {len(stranded['extra'])} object(s) made since the "
					f"snapshot were left alone: {', '.join(stranded['extra'][:5])}"
				))

			for outcome in result.failed[:5]:
				self.report({"ERROR"}, f"BlenDiff: {outcome}")

			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_DeleteSnapshot(bpy.types.Operator):
	"""Delete a snapshot from the sidecar"""
	bl_idname = "blendiff.delete_snapshot"
	bl_label = "Delete Snapshot"
	bl_description = "Permanently delete this snapshot from the .blendiff file"

	snapshot_id: bpy.props.StringProperty()

	def invoke(self, context, event):
		return context.window_manager.invoke_confirm(self, event)

	def execute(self, context):
		if not self.snapshot_id:
			self.report({"ERROR"}, "BlenDiff: No snapshot ID provided.")
			return {"CANCELLED"}

		mgr = _get_sidecar(context)
		deleted = mgr.delete_snapshot(self.snapshot_id)

		if deleted:
			wm = context.window_manager
			if wm.get("blendiff_active_snapshot_id") == self.snapshot_id:
				for key in ("blendiff_active_snapshot_id", "blendiff_active_snapshot_label",
							"blendiff_result", "blendiff_result_title"):
					if key in wm:
						del wm[key]
			self.report({"INFO"}, "BlenDiff: Snapshot deleted.")
		else:
			# Almost always a second click on a row that had not redrawn yet.
			# The snapshot being gone is the state that was asked for, so this
			# is worth saying once, not worth calling a failure.
			self.report({"INFO"}, "BlenDiff: That snapshot was already deleted.")

		_refresh_panels(context)
		return {"FINISHED"}


class BLENDIFF_OT_ExportHTML(bpy.types.Operator):
	"""Export the current diff result as a self-contained HTML report"""
	bl_idname = "blendiff.export_html"
	bl_label = "Export HTML Report"
	bl_description = "Save the diff result as a shareable HTML file"

	# Reports are timestamped, so exporting repeatedly used to fill the
	# project directory with files the artist never chose to keep there.
	# Asking where to save makes it a deliberate act, like every other
	# export in Blender.
	filepath: bpy.props.StringProperty(subtype="FILE_PATH")
	filter_glob: bpy.props.StringProperty(default="*.html", options={"HIDDEN"})

	def invoke(self, context, event):
		if "blendiff_result" not in context.window_manager:
			self.report({"ERROR"}, "BlenDiff: No diff result to export. Run a diff first.")
			return {"CANCELLED"}
		if not bpy.data.filepath:
			self.report({"ERROR"}, "BlenDiff: Please save your .blend file first.")
			return {"CANCELLED"}

		from ..export.html_exporter import build_output_path

		label = context.window_manager.get("blendiff_active_snapshot_label", "Snapshot")
		self.filepath = build_output_path(bpy.data.filepath, label)
		context.window_manager.fileselect_add(self)
		return {"RUNNING_MODAL"}

	def execute(self, context):
		wm = context.window_manager

		if "blendiff_result" not in wm:
			self.report({"ERROR"}, "BlenDiff: No diff result to export. Run a diff first.")
			return {"CANCELLED"}

		if not bpy.data.filepath:
			self.report({"ERROR"}, "BlenDiff: Please save your .blend file first.")
			return {"CANCELLED"}

		try:
			from ..export.html_exporter import export_to_file, build_output_path

			result = json.loads(wm["blendiff_result"])
			snapshot_label = wm.get("blendiff_active_snapshot_label", "Snapshot")

			# Set by the file browser; falls back to the suggested path when
			# the operator is run directly, as scripts and tests do.
			output_path = self.filepath or build_output_path(
				bpy.data.filepath, snapshot_label
			)
			export_to_file(
				result=result,
				snapshot_label=snapshot_label,
				blend_filepath=bpy.data.filepath,
				output_path=output_path,
			)

			self.report({"INFO"}, f"BlenDiff: Exported to {output_path}")
			return {"FINISHED"}

		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_RunThreeWayDiff(bpy.types.Operator):
	"""Run a three-way diff between base, version A and version B snapshots"""
	bl_idname = "blendiff.run_threeway_diff"
	bl_label = "Run Three-Way Diff"
	bl_description = "Compare base vs version A vs version B to find conflicts"

	def execute(self, context):
		wm = context.window_manager

		if not bpy.data.filepath:
			self.report({"ERROR"}, "BlenDiff: Save your .blend file first.")
			return {"CANCELLED"}

		base_label = wm.blendiff_base_label.strip()
		a_label    = wm.blendiff_a_label.strip()
		b_label    = wm.blendiff_b_label.strip()

		if not all([base_label, a_label, b_label]):
			self.report({"ERROR"}, "BlenDiff: Pick a snapshot for Base, Version A and Version B.")
			return {"CANCELLED"}

		mgr = SidecarManager(bpy.data.filepath)
		all_snapshots = mgr.list_snapshots()

		def find(label, snaps):
			for s in snaps:
				if s.label == label:
					return s
			return None

		base  = find(base_label,  all_snapshots)
		ver_a = find(a_label,     all_snapshots)
		ver_b = find(b_label,     all_snapshots)

		missing = [l for l, s in [(base_label, base), (a_label, ver_a), (b_label, ver_b)] if s is None]
		if missing:
			self.report({"ERROR"}, f"BlenDiff: Snapshots not found: {', '.join(missing)}")
			return {"CANCELLED"}

		try:
			engine = MergeEngine()
			tw = engine.three_way_diff(
				base=base.data,
				version_a=ver_a.data,
				version_b=ver_b.data,
				base_label=base_label,
				label_a=a_label,
				label_b=b_label,
			)

			result = _serialize_threeway(tw)
			wm["blendiff_threeway_result"] = json.dumps(result)
			wm["blendiff_threeway_obj"] = json.dumps(result)

			s = tw.summary()
			self.report({"INFO"},
				f"BlenDiff: {s['total_conflicts']} conflict(s), "
				f"{s['auto_resolved']} auto-resolved, "
				f"{s['unresolved']} need resolution."
			)
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_SetResolution(bpy.types.Operator):
	"""Set the resolution for a specific conflict"""
	bl_idname = "blendiff.set_resolution"
	bl_label = "Set Resolution"

	object_name:   bpy.props.StringProperty()
	property_path: bpy.props.StringProperty()
	resolution:    bpy.props.StringProperty()

	def execute(self, context):
		wm = context.window_manager
		raw = wm.get("blendiff_threeway_result")
		if not raw:
			self.report({"ERROR"}, "BlenDiff: No three-way diff result found.")
			return {"CANCELLED"}

		try:
			result = json.loads(raw)

			for proposal in result.get("proposals", []):
				if proposal["object_name"] == self.object_name:
					for conflict in proposal.get("conflicts", []):
						if conflict["property_path"] == self.property_path:
							conflict["resolution"] = self.resolution
							break

			# Only applicable conflicts gate the merge. Conflicts BlenDiff
			# cannot write back are informational: requiring a decision there
			# would block the changes it *can* apply, in exchange for a choice
			# that would then be discarded.
			def _blocking(proposal):
				return [
					c for c in proposal.get("conflicts", [])
					if c.get("applicable", True)
				]

			unresolved = sum(
				sum(
					1 for c in _blocking(p)
					if c.get("resolution", "unresolved") == "unresolved"
				)
				for p in result.get("proposals", [])
			)
			result["summary"]["unresolved"] = unresolved
			result["summary"]["ready_to_apply"] = unresolved == 0

			wm["blendiff_threeway_result"] = json.dumps(result)
			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


class BLENDIFF_OT_ApplyMerge(bpy.types.Operator):
	"""Apply all resolved merge decisions to the current scene"""
	bl_idname = "blendiff.apply_merge"
	bl_label = "Apply Merge"
	bl_description = "Apply all resolved conflict decisions to the scene"

	def invoke(self, context, event):
		return context.window_manager.invoke_confirm(self, event)

	def execute(self, context):
		wm = context.window_manager
		raw = wm.get("blendiff_threeway_result")
		if not raw:
			self.report({"ERROR"}, "BlenDiff: No three-way diff result.")
			return {"CANCELLED"}

		result = json.loads(raw)
		if not result.get("summary", {}).get("ready_to_apply", False):
			self.report({"ERROR"}, "BlenDiff: Not all conflicts resolved yet.")
			return {"CANCELLED"}

		try:
			from ..merge_engine.applier import Applier

			tw = _deserialize_threeway(result)
			applier = Applier()
			apply_result = applier.apply_all(tw, context)

			if "blendiff_threeway_result" in wm:
				del wm["blendiff_threeway_result"]

			# Report per property, not per proposal. Counting proposals made a
			# merge that wrote nothing look like a success.
			level = "WARNING" if (apply_result.failed or apply_result.skipped) else "INFO"
			self.report({level}, f"BlenDiff: {apply_result.report_line()}")

			for outcome in apply_result.failed[:5]:
				self.report({"ERROR"}, f"BlenDiff: {outcome}")
			for outcome in apply_result.skipped[:5]:
				self.report({"WARNING"}, f"BlenDiff: {outcome}")

			return {"FINISHED"}
		except Exception as e:
			self.report({"ERROR"}, f"BlenDiff: {e}")
			return {"CANCELLED"}


# Serialization helpers for ThreeWayDiff ↔ JSON

def _serialize_threeway(tw) -> dict:
	"""Convert ThreeWayDiff to a plain JSON-safe dict."""
	return {
		"base_label": tw.base_label,
		"label_a":    tw.label_a,
		"label_b":    tw.label_b,
		"summary":    tw.summary(),
		"proposals": [
			{
				"object_name": p.object_name,
				"structural_conflict": p.structural_conflict,
				"target_kind": p.target_kind.value,
				"previous_name": p.previous_name,
				"conflicts": [
					{
						"property_path": c.property_path,
						"base_value":    c.base_value,
						"value_a":       c.value_a,
						"value_b":       c.value_b,
						"kind":          c.kind.value,
						"resolution":    c.resolution.value,
						"applicable":    c.applicable,
						"unsupported_reason": c.unsupported_reason,
					}
					for c in p.conflicts
				],
				"non_conflicting_from_a": [
					{"property_path": nc.property_path,
					 "base_value": nc.base_value,
					 "new_value": nc.new_value,
					 "source": nc.source,
					 "applicable": nc.applicable,
					 "unsupported_reason": nc.unsupported_reason}
					for nc in p.non_conflicting_from_a
				],
				"non_conflicting_from_b": [
					{"property_path": nc.property_path,
					 "base_value": nc.base_value,
					 "new_value": nc.new_value,
					 "source": nc.source,
					 "applicable": nc.applicable,
					 "unsupported_reason": nc.unsupported_reason}
					for nc in p.non_conflicting_from_b
				],
			}
			for p in tw.proposals
		],
	}


def _deserialize_threeway(d: dict):
	"""Reconstruct a ThreeWayDiff from a JSON dict."""
	from ..data_model.conflict import (
		ThreeWayDiff, MergeProposal, PropertyConflict,
		NonConflictingChange, Resolution, ConflictKind, TargetKind,
	)

	proposals = []
	for pd in d.get("proposals", []):
		conflicts = [
			PropertyConflict(
				property_path=c["property_path"],
				base_value=c["base_value"],
				value_a=c["value_a"],
				value_b=c["value_b"],
				kind=ConflictKind(c["kind"]),
				resolution=Resolution(c["resolution"]),
				applicable=c.get("applicable", True),
				unsupported_reason=c.get("unsupported_reason", ""),
			)
			for c in pd.get("conflicts", [])
		]
		nc_a = [
			NonConflictingChange(**nc)
			for nc in pd.get("non_conflicting_from_a", [])
		]
		nc_b = [
			NonConflictingChange(**nc)
			for nc in pd.get("non_conflicting_from_b", [])
		]
		proposals.append(MergeProposal(
			object_name=pd["object_name"],
			conflicts=conflicts,
			non_conflicting_from_a=nc_a,
			non_conflicting_from_b=nc_b,
			structural_conflict=pd.get("structural_conflict", False),
			target_kind=TargetKind(pd.get("target_kind", "object")),
			previous_name=pd.get("previous_name"),
		))

	tw = ThreeWayDiff(
		base_label=d["base_label"],
		label_a=d["label_a"],
		label_b=d["label_b"],
		proposals=proposals,
		auto_resolved_count=d.get("summary", {}).get("auto_resolved", 0),
	)
	return tw


# Registration

OPERATORS = [
	BLENDIFF_OT_CaptureSnapshot,
	BLENDIFF_OT_RunDiff,
	BLENDIFF_OT_ClearResults,
	BLENDIFF_OT_SaveSnapshot,
	BLENDIFF_OT_DiffAgainstSnapshot,
	BLENDIFF_OT_DiffTwoSnapshots,
	BLENDIFF_OT_RestoreSnapshot,
	BLENDIFF_OT_DeleteSnapshot,
	BLENDIFF_OT_ExportHTML,
	BLENDIFF_OT_RunThreeWayDiff,
	BLENDIFF_OT_SetResolution,
	BLENDIFF_OT_ApplyMerge,
]


def register():
	register_classes(OPERATORS)


def unregister():
	unregister_classes(OPERATORS)
