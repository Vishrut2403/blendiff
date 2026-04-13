"""
tests/test_html_exporter.py

Unit tests for export/html_exporter.py.
No bpy required — runs with plain pytest.
"""

import json
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blendiff.export.html_exporter import (
	generate_html,
	export_to_file,
	build_output_path,
	_format_value,
	_safe_id,
)


# Fixtures

EMPTY_RESULT = {
	"summary": "Added: 0  Removed: 0  Modified: 0  Collections: 0",
	"added_objects": [],
	"removed_objects": [],
	"modified_objects": [],
	"collection_diffs": [],
}

FULL_RESULT = {
	"summary": "Added: 1  Removed: 1  Modified: 1  Collections: 1",
	"added_objects": ["Sphere"],
	"removed_objects": ["Camera"],
	"modified_objects": [
		{
			"name": "Cube",
			"changes": [
				{
					"property_path": "transform.location",
					"old_value": [0.0, 0.0, 0.0],
					"new_value": [1.0, 2.0, 3.0],
				},
				{
					"property_path": "material[Material].nodes.Principled BSDF.inputs.Roughness",
					"old_value": 0.2,
					"new_value": 0.8,
				},
			],
		}
	],
	"collection_diffs": [
		{
			"path": "Scene Collection/Props",
			"kind": "modified",
			"changes": [
				{
					"property_path": "objects",
					"old_value": ["Cube"],
					"new_value": ["Cube", "Sphere"],
				}
			],
		}
	],
}


# generate_html — structure

class TestGenerateHTMLStructure:
	def test_returns_string(self):
		html = generate_html(EMPTY_RESULT, "Snapshot 1", "scene.blend")
		assert isinstance(html, str)

	def test_contains_doctype(self):
		html = generate_html(EMPTY_RESULT, "Snapshot 1", "scene.blend")
		assert "<!DOCTYPE html>" in html

	def test_contains_blend_filename(self):
		html = generate_html(EMPTY_RESULT, "Snapshot 1", "my_scene.blend")
		assert "my_scene.blend" in html

	def test_contains_snapshot_label(self):
		html = generate_html(EMPTY_RESULT, "Before rigging", "scene.blend")
		assert "Before rigging" in html

	def test_contains_summary(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		assert "Added: 1" in html

	def test_no_external_script_tags(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		# No src= on script tags — everything must be inline
		import re
		script_tags = re.findall(r'<script[^>]*src=', html)
		assert script_tags == []

	def test_no_external_link_tags(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		import re
		link_tags = re.findall(r'<link[^>]*href=(?!.*github)', html)
		assert link_tags == []

	def test_self_contained_single_file(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		# Must have both style and script inline
		assert "<style>" in html
		assert "<script>" in html


# generate_html — content

class TestGenerateHTMLContent:
	def test_added_object_present(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		assert "Sphere" in html

	def test_removed_object_present(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		assert "Camera" in html

	def test_modified_object_present(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		assert "Cube" in html

	def test_property_path_present(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		assert "transform.location" in html

	def test_material_node_path_present(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		assert "Roughness" in html

	def test_collection_diff_present(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		assert "Scene Collection" in html

	def test_no_changes_message_when_empty(self):
		html = generate_html(EMPTY_RESULT, "Snap", "scene.blend")
		assert "No changes detected" in html

	def test_annotation_textareas_present(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		assert 'class="annotation"' in html

	def test_download_annotations_button_present(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		assert "downloadAnnotations" in html

	def test_load_annotations_button_present(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend")
		assert "loadAnnotations" in html

	def test_exported_at_shown(self):
		html = generate_html(FULL_RESULT, "Snap", "scene.blend",
							 exported_at="2026-04-13 10:00:00")
		assert "2026-04-13 10:00:00" in html


# generate_html — HTML escaping

class TestHTMLEscaping:
	def test_xss_in_snapshot_label_escaped(self):
		html = generate_html(EMPTY_RESULT, "<script>alert(1)</script>", "scene.blend")
		assert "<script>alert(1)</script>" not in html
		assert "&lt;script&gt;" in html

	def test_xss_in_blend_filename_escaped(self):
		html = generate_html(EMPTY_RESULT, "Snap", "<evil>.blend")
		assert "<evil>" not in html

	def test_ampersand_in_label_escaped(self):
		html = generate_html(EMPTY_RESULT, "Before & After", "scene.blend")
		assert "&amp;" in html

	def test_quotes_in_object_name_escaped(self):
		result = {**EMPTY_RESULT, "added_objects": ['Object "Test"']}
		html = generate_html(result, "Snap", "scene.blend")
		assert '<script>' not in html.split('Object')[1][:50]


# export_to_file

class TestExportToFile:
	def test_creates_file(self):
		with tempfile.TemporaryDirectory() as tmpdir:
			output = os.path.join(tmpdir, "report.html")
			export_to_file(FULL_RESULT, "Snap", "/tmp/scene.blend", output)
			assert os.path.exists(output)

	def test_file_is_valid_html(self):
		with tempfile.TemporaryDirectory() as tmpdir:
			output = os.path.join(tmpdir, "report.html")
			export_to_file(FULL_RESULT, "Snap", "/tmp/scene.blend", output)
			with open(output, encoding="utf-8") as f:
				content = f.read()
			assert "<!DOCTYPE html>" in content
			assert "</html>" in content

	def test_file_contains_diff_content(self):
		with tempfile.TemporaryDirectory() as tmpdir:
			output = os.path.join(tmpdir, "report.html")
			export_to_file(FULL_RESULT, "Snap", "/tmp/scene.blend", output)
			with open(output, encoding="utf-8") as f:
				content = f.read()
			assert "Sphere" in content
			assert "Camera" in content

	def test_returns_output_path(self):
		with tempfile.TemporaryDirectory() as tmpdir:
			output = os.path.join(tmpdir, "report.html")
			returned = export_to_file(FULL_RESULT, "Snap", "/tmp/scene.blend", output)
			assert returned == output

	def test_file_encoded_utf8(self):
		with tempfile.TemporaryDirectory() as tmpdir:
			output = os.path.join(tmpdir, "report.html")
			result = {**FULL_RESULT, "added_objects": ["Würfel"]}
			export_to_file(result, "Spät", "/tmp/szene.blend", output)
			with open(output, encoding="utf-8") as f:
				content = f.read()
			assert "Würfel" in content


# build_output_path

class TestBuildOutputPath:
	def test_output_in_same_dir_as_blend(self):
		path = build_output_path("/myspace/scene.blend", "Before rigging")
		assert path.startswith("/myspace/")

	def test_output_is_html(self):
		path = build_output_path("/myspace/scene.blend", "Before rigging")
		assert path.endswith(".html")

	def test_blend_name_in_output(self):
		path = build_output_path("/myspace/scene.blend", "Before rigging")
		assert "scene" in os.path.basename(path)

	def test_label_in_output(self):
		path = build_output_path("/myspace/scene.blend", "Before rigging")
		assert "Before" in os.path.basename(path)

	def test_special_chars_in_label_sanitised(self):
		path = build_output_path("/myspace/scene.blend", "Test/Label:Bad")
		basename = os.path.basename(path)
		assert "/" not in basename
		assert ":" not in basename


# _format_value helper

class TestFormatValue:
	def test_none_returns_none_string(self):
		assert _format_value(None) == "(none)"

	def test_float_list_rounded(self):
		result = _format_value([0.123456789, 1.0, 0.0])
		assert "0.1235" in result

	def test_string_returned_as_is(self):
		assert _format_value("hello") == "hello"

	def test_int_returned_as_string(self):
		assert _format_value(42) == "42"

	def test_material_slot_dict_shows_name(self):
		slot = {"index": 0, "name": "Material.001", "use_nodes": True}
		assert _format_value(slot) == "Material.001"

	def test_empty_material_slot_shows_empty(self):
		slot = {"index": 0, "name": None, "use_nodes": None}
		assert _format_value(slot) == "(empty)"


# _safe_id helper

class TestSafeId:
	def test_alphanumeric_unchanged(self):
		assert _safe_id("hello123") == "hello123"

	def test_spaces_replaced(self):
		assert " " not in _safe_id("hello world")

	def test_slashes_replaced(self):
		assert "/" not in _safe_id("Scene Collection/Props")

	def test_dots_replaced(self):
		result = _safe_id("object.property")
		assert "." not in result