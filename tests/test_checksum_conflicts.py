# ./tests/test_checksum_conflicts.py
# License: Apache-2.0 (disclaimer at bottom of file)
import os
import hashlib
from pathlib import Path
from xtrshow.repatch import (
    apply_changes,
    parse_multi_file_patch,
    _compute_checksum,
    _verify_checksum,
    _detect_conflicts,
)


# ---------------------------------------------------------------------------
# Checksum helpers
# ---------------------------------------------------------------------------


def test_compute_checksum(tmp_path):
    """SHA256 output matches hashlib directly."""
    f = tmp_path / "data.txt"
    f.write_text("hello world\n")

    expected = hashlib.sha256(b"hello world\n").hexdigest()
    assert _compute_checksum(f) == expected


def test_backup_creates_sha256(tmp_path):
    """Applying a patch should leave a .sha256 file next to the .orig backup."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "app.py"
    target.write_text("v1\n")

    changes = {
        "app.py": [
            {
                "hint": None,
                "search": ["v1"],
                "replace": ["v2"],
                "tail": [],
                "annotation": None,
                "patch_line": 1,
            }
        ]
    }
    apply_changes(changes)

    backup = project_dir / ".xtr" / "backup" / "app.py.orig"
    checksum_file = project_dir / ".xtr" / "backup" / "app.py.orig.sha256"
    assert backup.exists()
    assert checksum_file.exists()
    assert checksum_file.read_text().strip() == _compute_checksum(backup)


def test_verify_checksum_passes_when_unchanged(tmp_path):
    """_verify_checksum returns True when file hasn't been touched since backup."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "mod.py"
    target.write_text("original\n")

    changes = {
        "mod.py": [
            {
                "hint": None,
                "search": ["original"],
                "replace": ["patched"],
                "tail": [],
                "annotation": None,
                "patch_line": 1,
            }
        ]
    }
    apply_changes(changes)

    # File is now "patched\n"; a state checksum of the PATCHED content was
    # saved after applying. No external edit happened, so verify passes.
    result = _verify_checksum("mod.py")
    assert result is True  # untouched since last patch -> clean


def test_verify_checksum_no_backup_returns_true(tmp_path):
    """_verify_checksum returns True (clean) when no prior backup exists."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "fresh.py"
    target.write_text("brand new\n")

    assert _verify_checksum("fresh.py") is True


def test_verify_checksum_warns_on_external_edit(tmp_path, capsys):
    """_verify_checksum prints a warning when file was edited externally."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "warn.py"
    target.write_text("original\n")

    changes = {
        "warn.py": [
            {
                "hint": None,
                "search": ["original"],
                "replace": ["patched"],
                "tail": [],
                "annotation": None,
                "patch_line": 1,
            }
        ]
    }
    apply_changes(changes)

    # Simulate external edit AFTER patching
    target.write_text("externally modified\n")

    result = _verify_checksum("warn.py")
    captured = capsys.readouterr()

    assert result is False
    assert "modified externally" in captured.out


# ---------------------------------------------------------------------------
# Block conflict detection
# ---------------------------------------------------------------------------


def test_no_conflict_non_overlapping(tmp_path, monkeypatch):
    """Two blocks targeting different lines should both apply cleanly."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "clean.py"
    target.write_text("line1\nline2\nline3\nline4\n")

    START, MID, END = "<" * 4, "=" * 4, ">" * 4
    patch_content = f"""
--- a/{target.name}
{START}
line1
{MID}
LINE1
{END}

{START}
line3
{MID}
LINE3
{END}
"""
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    content = target.read_text()
    assert "LINE1" in content
    assert "LINE3" in content


def test_conflict_overlapping_blocks(tmp_path, monkeypatch, capsys):
    """Two blocks targeting the same line: second should be skipped with a warning."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "conflict.py"
    target.write_text("shared_line\nother\n")

    START, MID, END = "<" * 4, "=" * 4, ">" * 4
    patch_content = f"""
--- a/{target.name}
@ Block A
{START}
shared_line
{MID}
replacement_a
{END}

@ Block B
{START}
shared_line
{MID}
replacement_b
{END}
"""
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    captured = capsys.readouterr()
    content = target.read_text()

    # Block A wins, Block B is skipped
    assert "replacement_a" in content
    assert "replacement_b" not in content
    assert "Conflict" in captured.out or "conflict" in captured.out.lower()


def test_conflict_status_in_report(tmp_path, monkeypatch, capsys):
    """CONFLICT status should appear in the hunk report output."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "report.py"
    target.write_text("same\nother\n")

    START, MID, END = "<" * 4, "=" * 4, ">" * 4
    patch_content = f"""
--- a/{target.name}
@ First
{START}
same
{MID}
new_a
{END}

@ Second
{START}
same
{MID}
new_b
{END}
"""
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    captured = capsys.readouterr()
    assert "Overlaps Earlier Block" in captured.out


def test_detect_conflicts_direct(tmp_path):
    """Unit test _detect_conflicts directly."""
    file_lines = ["line1\n", "line2\n", "line3\n"]

    blocks = [
        {
            "search": ["line1"],
            "hint": None,
            "replace": ["x"],
            "tail": [],
            "annotation": None,
            "patch_line": 1,
        },
        {
            "search": ["line1"],
            "hint": None,
            "replace": ["y"],
            "tail": [],
            "annotation": None,
            "patch_line": 5,
        },
    ]

    conflicts = _detect_conflicts(blocks, file_lines)
    assert 2 in conflicts  # second block conflicts
    assert 1 not in conflicts  # first block is fine


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
