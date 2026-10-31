import json

from pramaan.data import archive


def _fake_year(data_dir, year):
    for rel in archive.year_files(year):
        f = data_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(f"contents of {rel}".encode())


def test_archive_year_records_manifest_and_is_idempotent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(archive, "_rclone", lambda args, label: calls.append(args))
    _fake_year(tmp_path, 2023)

    archive.archive_year(2023, data_dir=tmp_path, remote="fake:x")

    entries = [json.loads(line) for line in (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert {e["file"] for e in entries} == set(archive.year_files(2023))
    assert all(len(e["sha256"]) == 64 and e["size"] > 0 for e in entries)
    assert archive.archived_years(tmp_path) == {2023}

    n_calls = len(calls)
    archive.archive_year(2023, data_dir=tmp_path, remote="fake:x")  # second run: nothing to do
    assert len(calls) == n_calls


def test_failed_upload_leaves_no_manifest_entry(tmp_path, monkeypatch):
    def boom(args, label):
        raise OSError("network down")

    monkeypatch.setattr(archive, "_rclone", boom)
    _fake_year(tmp_path, 2023)
    try:
        archive.archive_year(2023, data_dir=tmp_path, remote="fake:x")
    except OSError:
        pass
    assert archive.archived_years(tmp_path) == set()


def test_restore_skips_files_already_local(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(archive, "_rclone", lambda args, label: calls.append(args))
    _fake_year(tmp_path, 2023)
    archive.restore_year(2023, data_dir=tmp_path, remote="fake:x")
    assert calls == []
