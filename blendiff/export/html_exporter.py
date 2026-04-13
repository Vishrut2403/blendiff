"""
blendiff.export.html_exporter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Generates a self-contained HTML diff report from a BlenDiff result dict.

Design decisions
----------------
* Zero bpy imports — pure Python, fully testable without Blender.
* Single file output — inline CSS and JS, no external dependencies.
* Annotations: each diff entry has a comment textarea. The JS
  "Download Annotations" button saves them as a companion JSON file
  using the browser download API.
* Color convention: green = added, red = removed, yellow = modified.
* Input: the result dict produced by _run_diff_against_dict() in operators.py.
"""

from __future__ import annotations

import json
import os
from datetime import datetime


def generate_html(
	result: dict,
	snapshot_label: str,
	blend_filename: str,
	exported_at: str | None = None,
) -> str:
	"""
	Generate a self-contained HTML string from a diff result.

	Parameters
	----------
	result:
		The dict produced by _run_diff_against_dict() — keys:
		summary, added_objects, removed_objects, modified_objects,
		collection_diffs.
	snapshot_label:
		Label of the snapshot being diffed against (shown in the header).
	blend_filename:
		Basename of the .blend file (shown in the header).
	exported_at:
		ISO timestamp string for the export time. Defaults to now.

	Returns
	-------
	str
		Complete HTML document as a string.
	"""
	if exported_at is None:
		exported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

	summary = result.get("summary", "")
	added = result.get("added_objects", [])
	removed = result.get("removed_objects", [])
	modified = result.get("modified_objects", [])
	col_diffs = result.get("collection_diffs", [])

	body_parts: list[str] = []

	# Added objects
	if added:
		body_parts.append(_section_header("Added Objects", "added", len(added)))
		for name in added:
			entry_id = _safe_id(f"added_{name}")
			body_parts.append(_entry_card(
				entry_id=entry_id,
				kind="added",
				title=f"+ {name}",
				rows=[],
			))

	# Removed objects 
	if removed:
		body_parts.append(_section_header("Removed Objects", "removed", len(removed)))
		for name in removed:
			entry_id = _safe_id(f"removed_{name}")
			body_parts.append(_entry_card(
				entry_id=entry_id,
				kind="removed",
				title=f"- {name}",
				rows=[],
			))

	# Modified objects
	if modified:
		body_parts.append(_section_header("Modified Objects", "modified", len(modified)))
		for obj in modified:
			entry_id = _safe_id(f"modified_{obj['name']}")
			rows = [
				_change_row(c["property_path"], c["old_value"], c["new_value"])
				for c in obj.get("changes", [])
			]
			body_parts.append(_entry_card(
				entry_id=entry_id,
				kind="modified",
				title=f"~ {obj['name']}",
				rows=rows,
			))

	# Collection diffs 
	if col_diffs:
		body_parts.append(_section_header("Collection Changes", "collections", len(col_diffs)))
		for cd in col_diffs:
			kind_str = cd.get("kind", "modified")
			entry_id = _safe_id(f"col_{cd['path']}")
			prefix = {"added": "+", "removed": "-", "modified": "~"}.get(kind_str, "~")
			rows = [
				_change_row(c["property_path"], c["old_value"], c["new_value"])
				for c in cd.get("changes", [])
			]
			body_parts.append(_entry_card(
				entry_id=entry_id,
				kind=kind_str,
				title=f"{prefix} {cd['path']}",
				rows=rows,
			))

	if not body_parts:
		body_parts.append(
			'<div class="no-changes">No changes detected between snapshots.</div>'
		)

	body_html = "\n".join(body_parts)

	return _wrap_document(
		body_html=body_html,
		summary=summary,
		snapshot_label=_esc(snapshot_label),
		blend_filename=_esc(blend_filename),
		exported_at=_esc(exported_at),
	)


def export_to_file(
	result: dict,
	snapshot_label: str,
	blend_filepath: str,
	output_path: str,
) -> str:
	"""
	Write the HTML report to a file.

	Parameters
	----------
	result:
		Diff result dict.
	snapshot_label:
		Label of the snapshot.
	blend_filepath:
		Full path to the .blend file (used for display only).
	output_path:
		Full path where the .html file should be written.

	Returns
	-------
	str
		The output_path that was written.
	"""
	blend_filename = os.path.basename(blend_filepath)
	html = generate_html(
		result=result,
		snapshot_label=snapshot_label,
		blend_filename=blend_filename,
	)
	with open(output_path, "w", encoding="utf-8") as f:
		f.write(html)
	return output_path


def build_output_path(blend_filepath: str, snapshot_label: str) -> str:
	"""
	Derive the default output HTML path from the blend file path and
	snapshot label.

	Example:
		/myspace/scene.blend + "Before rigging"
		→ /myspace/scene_Before_rigging_20260413_143000.html
	"""
	base_dir = os.path.dirname(blend_filepath)
	blend_name = os.path.splitext(os.path.basename(blend_filepath))[0]
	safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in snapshot_label)
	timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
	filename = f"{blend_name}_{safe_label}_{timestamp}.html"
	return os.path.join(base_dir, filename)


# HTML building blocks

def _section_header(title: str, kind: str, count: int) -> str:
	return f'<h2 class="section-header {kind}">{_esc(title)} <span class="count">{count}</span></h2>'


def _entry_card(entry_id: str, kind: str, title: str, rows: list[str]) -> str:
	rows_html = "\n".join(rows) if rows else ""
	annotation_key = _esc(entry_id)
	return f"""
<div class="card {kind}" id="card-{_esc(entry_id)}">
  <div class="card-title">{_esc(title)}</div>
  {f'<div class="changes">{rows_html}</div>' if rows_html else ''}
  <div class="annotation-block">
	<label class="annotation-label">Note:</label>
	<textarea
	  class="annotation"
	  data-key="{annotation_key}"
	  placeholder="Add a note about this change…"
	  oninput="saveAnnotation(this)"
	></textarea>
  </div>
</div>"""


def _change_row(prop: str, old_val, new_val) -> str:
	old_str = _format_value(old_val)
	new_str = _format_value(new_val)
	return f"""
  <div class="change-row">
	<span class="prop-path">{_esc(prop)}</span>
	<span class="old-val">{_esc(old_str)}</span>
	<span class="arrow">→</span>
	<span class="new-val">{_esc(new_str)}</span>
  </div>"""


def _format_value(value) -> str:
	"""Convert a diff value to a readable string."""
	if value is None:
		return "(none)"
	if isinstance(value, list):
		if all(isinstance(x, (int, float)) for x in value):
			return "[" + ", ".join(f"{x:.4f}" if isinstance(x, float) else str(x) for x in value) + "]"
		return str(value)
	if isinstance(value, dict):
		if "name" in value and "index" in value:
			return value["name"] or "(empty)"
		return json.dumps(value)
	return str(value)


def _safe_id(s: str) -> str:
	"""Make a string safe for use as an HTML id / JS key."""
	return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


def _esc(s: str) -> str:
	"""HTML-escape a string."""
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
		.replace("'", "&#x27;")
	)


# Full document wrapper

def _wrap_document(
	body_html: str,
	summary: str,
	snapshot_label: str,
	blend_filename: str,
	exported_at: str,
) -> str:
	return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BlenDiff Report — {blend_filename}</title>
<style>
  /* ── Reset & base ── */
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
	font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
	background: #1a1a1a;
	color: #d4d4d4;
	line-height: 1.5;
	padding: 2rem;
  }}

  /* ── Header ── */
  .header {{
	border-bottom: 2px solid #333;
	padding-bottom: 1.5rem;
	margin-bottom: 2rem;
  }}
  .header h1 {{
	font-size: 1.6rem;
	color: #e8e8e8;
	margin-bottom: 0.4rem;
  }}
  .header .meta {{
	font-size: 0.85rem;
	color: #888;
  }}
  .header .meta span {{ margin-right: 1.5rem; }}

  /* ── Summary bar ── */
  .summary-bar {{
	display: flex;
	gap: 1rem;
	margin-bottom: 2rem;
	flex-wrap: wrap;
  }}
  .summary-pill {{
	padding: 0.4rem 1rem;
	border-radius: 999px;
	font-size: 0.85rem;
	font-weight: 600;
  }}
  .summary-pill.added   {{ background: #1a3a1a; color: #4caf50; border: 1px solid #4caf50; }}
  .summary-pill.removed {{ background: #3a1a1a; color: #f44336; border: 1px solid #f44336; }}
  .summary-pill.modified{{ background: #3a3000; color: #ffb300; border: 1px solid #ffb300; }}
  .summary-pill.collections {{ background: #1a2a3a; color: #42a5f5; border: 1px solid #42a5f5; }}

  /* ── Section headers ── */
  .section-header {{
	font-size: 1rem;
	font-weight: 700;
	text-transform: uppercase;
	letter-spacing: 0.08em;
	margin: 2rem 0 0.75rem;
	padding-bottom: 0.4rem;
	border-bottom: 1px solid #333;
  }}
  .section-header .count {{
	font-size: 0.8rem;
	background: #333;
	padding: 0.1rem 0.5rem;
	border-radius: 999px;
	margin-left: 0.5rem;
	vertical-align: middle;
  }}
  .section-header.added    {{ color: #4caf50; }}
  .section-header.removed  {{ color: #f44336; }}
  .section-header.modified {{ color: #ffb300; }}
  .section-header.collections {{ color: #42a5f5; }}

  /* ── Cards ── */
  .card {{
	background: #242424;
	border-radius: 8px;
	border-left: 4px solid #555;
	padding: 1rem 1.25rem;
	margin-bottom: 0.75rem;
  }}
  .card.added    {{ border-left-color: #4caf50; }}
  .card.removed  {{ border-left-color: #f44336; }}
  .card.modified {{ border-left-color: #ffb300; }}
  .card.collections {{ border-left-color: #42a5f5; }}

  .card-title {{
	font-weight: 600;
	font-size: 0.95rem;
	color: #e0e0e0;
	margin-bottom: 0.5rem;
  }}

  /* ── Change rows ── */
  .changes {{ margin: 0.5rem 0 0.75rem; }}
  .change-row {{
	display: grid;
	grid-template-columns: minmax(200px, 2fr) 1fr auto 1fr;
	gap: 0.5rem;
	align-items: start;
	padding: 0.35rem 0;
	border-bottom: 1px solid #2e2e2e;
	font-size: 0.82rem;
  }}
  .change-row:last-child {{ border-bottom: none; }}
  .prop-path  {{ color: #9e9e9e; font-family: monospace; word-break: break-all; }}
  .old-val    {{ color: #ef9a9a; font-family: monospace; word-break: break-all; }}
  .new-val    {{ color: #a5d6a7; font-family: monospace; word-break: break-all; }}
  .arrow      {{ color: #555; text-align: center; }}

  /* ── Annotations ── */
  .annotation-block {{ margin-top: 0.75rem; }}
  .annotation-label {{
	display: block;
	font-size: 0.75rem;
	color: #666;
	margin-bottom: 0.25rem;
	text-transform: uppercase;
	letter-spacing: 0.05em;
  }}
  .annotation {{
	width: 100%;
	background: #1a1a1a;
	border: 1px solid #333;
	border-radius: 4px;
	color: #ccc;
	font-size: 0.82rem;
	padding: 0.4rem 0.6rem;
	resize: vertical;
	min-height: 2.5rem;
	font-family: inherit;
	transition: border-color 0.2s;
  }}
  .annotation:focus {{
	outline: none;
	border-color: #555;
  }}

  /* ── Toolbar ── */
  .toolbar {{
	position: sticky;
	top: 0;
	background: #1a1a1a;
	border-bottom: 1px solid #2e2e2e;
	padding: 0.75rem 0;
	margin-bottom: 1.5rem;
	display: flex;
	gap: 0.75rem;
	z-index: 10;
  }}
  .btn {{
	padding: 0.4rem 1rem;
	border-radius: 6px;
	border: 1px solid #444;
	background: #2a2a2a;
	color: #ccc;
	font-size: 0.82rem;
	cursor: pointer;
	transition: background 0.15s, border-color 0.15s;
  }}
  .btn:hover {{ background: #333; border-color: #666; }}
  .btn.primary {{ background: #1a3a1a; border-color: #4caf50; color: #4caf50; }}
  .btn.primary:hover {{ background: #234a23; }}

  /* ── No changes ── */
  .no-changes {{
	text-align: center;
	color: #666;
	padding: 3rem;
	font-size: 1rem;
  }}

  /* ── Footer ── */
  .footer {{
	margin-top: 3rem;
	padding-top: 1rem;
	border-top: 1px solid #2e2e2e;
	font-size: 0.75rem;
	color: #555;
	text-align: center;
  }}
</style>
</head>
<body>

<div class="header">
  <h1>BlenDiff Report</h1>
  <div class="meta">
	<span>📄 {blend_filename}</span>
	<span>📌 vs. &quot;{snapshot_label}&quot;</span>
	<span>🕒 {exported_at}</span>
  </div>
</div>

<div class="toolbar">
  <button class="btn primary" onclick="downloadAnnotations()">⬇ Download Annotations</button>
  <button class="btn" onclick="loadAnnotations()">⬆ Load Annotations</button>
  <input type="file" id="annotation-file-input" accept=".json"
		 style="display:none" onchange="onAnnotationFileSelected(event)">
  <button class="btn" onclick="clearAllAnnotations()">✕ Clear Notes</button>
</div>

<div class="summary-bar">
  <span class="summary-pill added">   {summary}</span>
</div>

{body_html}

<div class="footer">
  Generated by BlenDiff · <a href="https://github.com/Vishrut2403/blendiff"
  style="color:#555">github.com/Vishrut2403/blendiff</a>
</div>

<script>
// ── Annotation storage (in-memory during session) ──────────────────────────
const annotations = {{}};

function saveAnnotation(el) {{
  const key = el.dataset.key;
  if (el.value.trim()) {{
	annotations[key] = el.value;
  }} else {{
	delete annotations[key];
  }}
}}

function downloadAnnotations() {{
  const payload = {{
	blendiff_annotations: true,
	exported_at: new Date().toISOString(),
	snapshot: "{snapshot_label}",
	blend_file: "{blend_filename}",
	annotations: annotations,
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type: "application/json"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "blendiff_annotations.json";
  a.click();
  URL.revokeObjectURL(a.href);
}}

function loadAnnotations() {{
  document.getElementById("annotation-file-input").click();
}}

function onAnnotationFileSelected(event) {{
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(e) {{
	try {{
	  const data = JSON.parse(e.target.result);
	  const loaded = data.annotations || {{}};
	  Object.entries(loaded).forEach(([key, value]) => {{
		annotations[key] = value;
		const el = document.querySelector(`textarea[data-key="${{key}}"]`);
		if (el) el.value = value;
	  }});
	}} catch(err) {{
	  alert("Could not load annotations: " + err.message);
	}}
  }};
  reader.readAsText(file);
  // Reset so the same file can be re-loaded
  event.target.value = "";
}}

function clearAllAnnotations() {{
  if (!confirm("Clear all notes?")) return;
  Object.keys(annotations).forEach(k => delete annotations[k]);
  document.querySelectorAll("textarea.annotation").forEach(el => el.value = "");
}}
</script>

</body>
</html>"""