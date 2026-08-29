# ./tests/test_cli_meta.py
# License: Apache-2.0 (disclaimer at bottom of file)
import re
from unittest.mock import patch

from xtrshow.cli import main, format_file_meta
from xtrshow.repatch import parse_multi_file_patch


def run_export(tmp_path, monkeypatch, capsys, target_file, extra_argv=None):
    """Run main() with the TUI mocked out, returning captured stdout."""
    monkeypatch.chdir(tmp_path)
    argv = ["xtrshow", "."] + (extra_argv or [])
    with patch("xtrshow.cli.curses.wrapper", return_value=[str(target_file)]), patch(
        "sys.argv", argv
    ):
        main()
    return capsys.readouterr().out


def test_meta_line_present_by_default(tmp_path, monkeypatch, capsys):
    f1 = tmp_path / "app.py"
    f1.write_text("line1\nline2\nline3\n")

    out = run_export(tmp_path, monkeypatch, capsys, f1)

    meta_lines = [l for l in out.splitlines() if l.startswith("# meta: ")]
    assert len(meta_lines) == 1
    meta = meta_lines[0]

    assert "3 lines" in meta
    assert "modified " in meta
    # ISO 8601 timestamp with offset, e.g. 2026-08-26T10:32:11-04:00
    assert re.search(r"modified \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", meta)
    assert re.search(r"\d+(\.\d+)? (B|KB|MB|GB)", meta)

    # Meta sits between the +++ header and the code fence
    lines = out.splitlines()
    idx = lines.index(meta)
    assert lines[idx - 1].startswith("+++ b/")
    assert lines[idx + 1].startswith("```")


def test_no_meta_flag_omits_line(tmp_path, monkeypatch, capsys):
    f1 = tmp_path / "app.py"
    f1.write_text("hello\n")

    out = run_export(tmp_path, monkeypatch, capsys, f1, ["--no-meta"])

    assert "# meta:" not in out
    assert "--- a/" in out
    assert "hello" in out


def test_meta_line_with_clean_mode(tmp_path, monkeypatch, capsys):
    f1 = tmp_path / "app.py"
    f1.write_text("a\nb\n")

    out = run_export(tmp_path, monkeypatch, capsys, f1, ["--clean"])

    meta_lines = [l for l in out.splitlines() if l.startswith("# meta: ")]
    assert len(meta_lines) == 1
    assert "2 lines" in meta_lines[0]


def test_meta_line_in_multi_export(tmp_path, monkeypatch, capsys):
    f1 = tmp_path / "app.py"
    f1.write_text("x = 1\n")

    run_export(tmp_path, monkeypatch, capsys, f1, ["--multi"])

    out_files = list((tmp_path / ".xtr" / "multi").iterdir())
    assert len(out_files) == 1
    assert "# meta: " in out_files[0].read_text()


def test_meta_line_is_ignored_by_patch_parser(tmp_path, monkeypatch, capsys):
    """The exported block must not register hunks if fed back to xtrpatch."""
    f1 = tmp_path / "app.py"
    f1.write_text("x = 1\n")

    out = run_export(tmp_path, monkeypatch, capsys, f1)

    changes = parse_multi_file_patch(out)
    assert all(not hunks for hunks in changes.values())


def test_format_file_meta_missing_file(tmp_path):
    assert format_file_meta(str(tmp_path / "nope.py"), 0) is None


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
