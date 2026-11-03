# Pramaan (प्रमाण)

An open benchmark and verification pipeline for citations to Indian Supreme Court judgments. See [SPEC.md](SPEC.md) for the full specification.

**Status:** M4 (quote and paragraph checks) done on a synthetic benchmark: altered quotes are caught, but real quotes between judgments rarely match word for word because old cases carry OCR noise (docs/DATA_NOTES.md section 12). M3 resolver: 85.0% of SCC/AIR/SCC OnLine citations that carry a case name resolve to the right case on test. M2 labels are mostly Claude-labelled, not human gold. M5 (support judge) next.
