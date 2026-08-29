# ./tests/test_cli_hash.py
# License: Apache-2.0 (disclaimer at bottom of file)
import hashlib
import re
from unittest.mock import patch

from xtrshow.cli import main, compute_sha256, format_file_meta
from xtrshow.repatch import _compute_checksum, parse_multi_file_patch

SHA256_RE = re.compile(r"sha256 ([0-9a-f]{64})")


def run_export(tmp_path, monkeypatch, capsys, target_file, extra_argv=None):
    """Run main() with the TUI mocked out, returning captured stdout."""
    monkeypatch.chdir(tmp_path)
    argv = ["xtrshow", "."] + (extra_argv or [])
    with patch("xtrshow.cli.curses.wrapper", return_value=[str(target_file)]), patch(
        "sys.argv", argv
    ):
        main()
    return capsys.readouterr().out


def test_meta_line_carries_sha256_by_default(tmp_path, monkeypatch, capsys):
    f1 = tmp_path / "app.py"
    f1.write_text("line1\nline2\n")

    out = run_export(tmp_path, monkeypatch, capsys, f1)

    meta = [l for l in out.splitlines() if l.startswith("# meta: ")][0]
    match = SHA256_RE.search(meta)
    assert match, meta
    assert match.group(1) == hashlib.sha256(f1.read_bytes()).hexdigest()


def test_sha256_is_last_field_of_meta(tmp_path, monkeypatch, capsys):
    f1 = tmp_path / "app.py"
    f1.write_text("x = 1\n")

    out = run_export(tmp_path, monkeypatch, capsys, f1)

    meta = [l for l in out.splitlines() if l.startswith("# meta: ")][0]
    assert meta.split(" | ")[-1].startswith("sha256 ")


def test_no_hash_flag_keeps_rest_of_meta(tmp_path, monkeypatch, capsys):
    f1 = tmp_path / "app.py"
    f1.write_text("a\nb\n")

    out = run_export(tmp_path, monkeypatch, capsys, f1, ["--no-hash"])

    meta = [l for l in out.splitlines() if l.startswith("# meta: ")][0]
    assert "sha256" not in meta
    assert "2 lines" in meta
    assert "modified " in meta


def test_no_meta_flag_also_drops_the_hash(tmp_path, monkeypatch, capsys):
    f1 = tmp_path / "app.py"
    f1.write_text("a\n")

    out = run_export(tmp_path, monkeypatch, capsys, f1, ["--no-meta"])

    assert "sha256" not in out
    assert "# meta:" not in out


def test_hash_covers_raw_bytes_not_normalized_content(tmp_path, monkeypatch, capsys):
    """CRLF files export normalized, but the digest must describe the disk bytes."""
    f1 = tmp_path / "crlf.py"
    f1.write_bytes(b"one\r\ntwo\r\n")

    out = run_export(tmp_path, monkeypatch, capsys, f1)

    meta = [l for l in out.splitlines() if l.startswith("# meta: ")][0]
    digest = SHA256_RE.search(meta).group(1)
    assert digest == hashlib.sha256(b"one\r\ntwo\r\n").hexdigest()
    assert digest != hashlib.sha256(b"one\ntwo\n").hexdigest()


def test_hash_matches_xtrpatch_checksum(tmp_path):
    """The exported digest is the same value xtrpatch records in .xtr/backup/."""
    f1 = tmp_path / "app.py"
    f1.write_text("shared value\n")

    assert compute_sha256(str(f1)) == _compute_checksum(str(f1))


def test_hash_changes_when_file_changes(tmp_path):
    f1 = tmp_path / "app.py"
    f1.write_text("before\n")
    first = compute_sha256(str(f1))
    f1.write_text("after\n")

    assert compute_sha256(str(f1)) != first


def test_hash_survives_large_files(tmp_path):
    """Files bigger than the 64 KiB read chunk hash correctly."""
    f1 = tmp_path / "big.txt"
    payload = b"x" * (65536 * 2 + 17)
    f1.write_bytes(payload)

    assert compute_sha256(str(f1)) == hashlib.sha256(payload).hexdigest()


def test_compute_sha256_missing_file(tmp_path):
    assert compute_sha256(str(tmp_path / "nope.py")) is None


def test_meta_line_still_builds_when_hash_unavailable(tmp_path, monkeypatch):
    """A digest that can't be read drops the field, it doesn't kill the line."""
    f1 = tmp_path / "app.py"
    f1.write_text("a\n")
    monkeypatch.setattr("xtrshow.cli.compute_sha256", lambda path: None)

    meta = format_file_meta(str(f1), 1)

    assert meta.startswith("# meta: ")
    assert "1 lines" in meta
    assert "sha256" not in meta


def test_hashed_meta_line_is_ignored_by_patch_parser(tmp_path, monkeypatch, capsys):
    """The exported block must not register hunks if fed back to xtrpatch."""
    f1 = tmp_path / "app.py"
    f1.write_text("x = 1\n")

    out = run_export(tmp_path, monkeypatch, capsys, f1)

    changes = parse_multi_file_patch(out)
    assert all(not hunks for hunks in changes.values())


def test_hash_present_in_multi_export(tmp_path, monkeypatch, capsys):
    f1 = tmp_path / "app.py"
    f1.write_text("x = 1\n")

    run_export(tmp_path, monkeypatch, capsys, f1, ["--multi"])

    out_files = list((tmp_path / ".xtr" / "multi").iterdir())
    assert SHA256_RE.search(out_files[0].read_text())


# Copyright Michael Godfrey 2026 | aloecraft.org <michael@aloecraft.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
