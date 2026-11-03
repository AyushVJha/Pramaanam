# Pramaan (प्रमाण)

An open benchmark and verification pipeline for citations to Indian Supreme Court judgments. See [SPEC.md](SPEC.md) for the full specification.

**Status:** M3 (resolver + identity check) done: on the frozen test split 85.0% of SCC/AIR/SCC OnLine citations that carry a case name resolve to the right case and 0.7% to a wrong one (`make bench-test`). M2 labels are mostly Claude-labelled, not human gold (docs/DATA_NOTES.md section 10). M4 (quote and paragraph checks) next.
