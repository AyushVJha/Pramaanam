# DECISIONS.md

Each entry: choice, alternative considered, why, trade-off.

## M0

### Shell out to `aws` CLI with `--no-sign-request` instead of `boto3`
- **Alternative:** add `boto3` as a dependency and call the S3 API directly.
- **Why:** the bucket is public and anonymous; SPEC.md §3.1 already names the CLI as the supported path, and `aws s3 cp` handles retries/resuming for large tar files for free.
- **Trade-off:** adds a system dependency (`awscli`) outside the Python environment, so `make setup` alone isn't enough on a machine without it — `download.py` checks for the binary and fails with an actionable error instead of downloading silently via HTTPS.

### Plan to key `cases` on `cnr`/`path`, not `case_id` (M1 design note, decided now because M0 found it)
- **Alternative:** use `case_id` from the metadata as the primary key, since it looks like an identifier.
- **Why:** `docs/DATA_NOTES.md` §2 found `case_id` is actually just the neutral citation with spaces (`"2023 INSC 1043"`), and it's empty for 4.7% of 2024 rows. `cnr` and `path` are 100% non-empty and 100% unique across all 2655 inspected rows.
- **Trade-off:** none really — just don't trust a field's name over its measured contents. Recorded here so M1's `build_db.py` doesn't repeat the mistake.
