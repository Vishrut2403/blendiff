"""
blendiff.cli.__main__
~~~~~~~~~~~~~~~~~~~~~~
Entry point for:  python -m blendiff.cli <command> [args]

Commands
--------
  list     <sidecar>                        List all snapshots in a sidecar
  compare  <sidecar> <label_a> <label_b>   Diff two snapshots by label
  latest   <sidecar>                        Diff the two most recent snapshots

Global flags
------------
  --output <path>      Write HTML report to this path (default: print JSON)
  --json               Print result as JSON to stdout
  --fail-on-changes    Exit with code 1 if any changes detected (for CI gates)
  --quiet              Suppress all output except errors

Exit codes
----------
  0  — success, no changes (or changes detected but --fail-on-changes not set)
  1  — changes detected and --fail-on-changes is set
  2  — error (file not found, snapshot not found, parse failure, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		prog="python -m blendiff.cli",
		description="BlenDiff headless CLI — diff Blender scene snapshots without opening Blender.",
	)

	sub = parser.add_subparsers(dest="command", metavar="COMMAND")
	sub.required = True

	# ── list ──────────────────────────────────────────────────────────────
	p_list = sub.add_parser("list", help="List all snapshots in a .blendiff sidecar")
	p_list.add_argument("sidecar", help="Path to the .blendiff file")
	p_list.add_argument("--json", dest="as_json", action="store_true",
						help="Output as JSON")

	# ── compare ───────────────────────────────────────────────────────────
	p_compare = sub.add_parser(
		"compare",
		help="Diff two snapshots by label (most recent match used if duplicates exist)",
	)
	p_compare.add_argument("sidecar", help="Path to the .blendiff file")
	p_compare.add_argument("label_a", help="Label of the base snapshot (before)")
	p_compare.add_argument("label_b", help="Label of the target snapshot (after)")
	p_compare.add_argument("--output", metavar="PATH",
						   help="Write HTML report to this path")
	p_compare.add_argument("--json", dest="as_json", action="store_true",
						   help="Print result as JSON to stdout")
	p_compare.add_argument("--fail-on-changes", action="store_true",
						   help="Exit with code 1 if changes are detected")
	p_compare.add_argument("--quiet", action="store_true",
						   help="Suppress output except errors")

	# ── latest ────────────────────────────────────────────────────────────
	p_latest = sub.add_parser(
		"latest",
		help="Diff the two most recent snapshots",
	)
	p_latest.add_argument("sidecar", help="Path to the .blendiff file")
	p_latest.add_argument("--output", metavar="PATH",
						  help="Write HTML report to this path")
	p_latest.add_argument("--json", dest="as_json", action="store_true",
						  help="Print result as JSON to stdout")
	p_latest.add_argument("--fail-on-changes", action="store_true",
						  help="Exit with code 1 if changes are detected")
	p_latest.add_argument("--quiet", action="store_true",
						  help="Suppress output except errors")

	return parser


def _cmd_list(args) -> int:
	from .api import list_snapshots

	try:
		snapshots = list_snapshots(args.sidecar)
	except FileNotFoundError as e:
		print(f"Error: {e}", file=sys.stderr)
		return 2

	if args.as_json:
		print(json.dumps(snapshots, indent=2))
		return 0

	if not snapshots:
		print("No snapshots found.")
		return 0

	print(f"{'#':<4} {'Label':<30} {'Timestamp':<22} {'ID'}")
	print("-" * 80)
	for i, s in enumerate(snapshots, 1):
		print(f"{i:<4} {s['label']:<30} {s['timestamp_display']:<22} {s['id'][:8]}")

	return 0


def _cmd_compare(args, use_latest: bool = False) -> int:
	from .api import compare_snapshots_by_label, compare_latest_two
	from ..export.html_exporter import export_to_file, build_output_path

	quiet = getattr(args, "quiet", False)

	try:
		if use_latest:
			result = compare_latest_two(args.sidecar)
		else:
			result = compare_snapshots_by_label(
				args.sidecar, args.label_a, args.label_b
			)
	except FileNotFoundError as e:
		print(f"Error: {e}", file=sys.stderr)
		return 2
	except ValueError as e:
		print(f"Error: {e}", file=sys.stderr)
		return 2

	# JSON output
	if getattr(args, "as_json", False):
		print(json.dumps(result, indent=2, default=str))

	# HTML output
	elif getattr(args, "output", None):
		output_path = args.output
		snapshot_label = (
			f"{result['snapshot_a']['label']} → {result['snapshot_b']['label']}"
		)
		export_to_file(
			result=result,
			snapshot_label=snapshot_label,
			blend_filepath=args.sidecar,
			output_path=output_path,
		)
		if not quiet:
			print(f"HTML report written to: {output_path}")

	# Default: human-readable summary
	else:
		if not quiet:
			snap_a = result["snapshot_a"]
			snap_b = result["snapshot_b"]
			print(f"\nBlenDiff — comparing snapshots")
			print(f"  Before : '{snap_a['label']}' ({snap_a['timestamp']})")
			print(f"  After  : '{snap_b['label']}' ({snap_b['timestamp']})")
			print(f"\n  {result['summary']}\n")

			added = result["added_objects"]
			removed = result["removed_objects"]
			modified = result["modified_objects"]
			col_diffs = result["collection_diffs"]

			if added:
				print(f"  Added objects ({len(added)}):")
				for name in added:
					print(f"    + {name}")

			if removed:
				print(f"  Removed objects ({len(removed)}):")
				for name in removed:
					print(f"    - {name}")

			if modified:
				print(f"  Modified objects ({len(modified)}):")
				for obj in modified:
					print(f"    ~ {obj['name']}")
					for c in obj["changes"]:
						print(f"        {c['property_path']}")
						print(f"          {c['old_value']}  →  {c['new_value']}")

			if col_diffs:
				print(f"  Collection changes ({len(col_diffs)}):")
				for cd in col_diffs:
					print(f"    {cd['kind'].capitalize()}: {cd['path']}")

			if not result["has_changes"]:
				print("  No changes detected.")

			print()

	# Exit code
	if getattr(args, "fail_on_changes", False) and result["has_changes"]:
		return 1

	return 0


def main(argv=None) -> int:
	parser = _build_parser()
	args = parser.parse_args(argv)

	if args.command == "list":
		return _cmd_list(args)
	elif args.command == "compare":
		return _cmd_compare(args, use_latest=False)
	elif args.command == "latest":
		return _cmd_compare(args, use_latest=True)

	parser.print_help()
	return 2


if __name__ == "__main__":
	sys.exit(main())
