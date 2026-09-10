from .api import (
	list_snapshots,
	compare_snapshots,
	compare_snapshots_by_label,
	compare_latest_two,
)

# Named here so the re-export is deliberate rather than an unused import. The
# extension review guidelines have reviewers run ruff over the submission, and
# a package API that reads as dead code is the kind of thing they flag.
__all__ = [
	"list_snapshots",
	"compare_snapshots",
	"compare_snapshots_by_label",
	"compare_latest_two",
]
