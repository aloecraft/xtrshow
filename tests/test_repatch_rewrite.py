# ./tests/test_repatch_rewrite.py
# License: Apache-2.0 (disclaimer at bottom of file)
import os

from xtrshow.repatch import apply_changes, parse_multi_file_patch

START, MID, END = "<" * 4, "=" * 4, ">" * 4

ALPINE = "#!/bin/sh\napk add go\nrc-service nginx start\n"
DEBIAN = "#!/bin/bash\napt-get update\nsystemctl enable --now nginx\n"


def _rewrite_patch(name, body=DEBIAN):
    """`! DELETE FILE` followed by a create block, both naming one path."""
    return (
        f"--- a/{name}\n"
        "@ old version, replaced wholesale below\n"
        "! DELETE FILE\n"
        "\n"
        f"--- a/{name}\n"
        "@ new version\n"
        f"{START}\n"
        f"{MID}\n"
        f"{body}"
        f"{END}\n"
    )


def test_delete_then_create_rewrites_file(tmp_path):
    """`! DELETE FILE` + a create block on one path replaces it wholesale."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "bootstrap_remote.sh"
    target.write_text(ALPINE)

    changes = parse_multi_file_patch(_rewrite_patch("bootstrap_remote.sh"))
    apply_changes(changes)

    assert target.read_text() == DEBIAN


def test_rewrite_backs_up_the_original(tmp_path):
    """The replaced content is recoverable from .xtr/backup."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "app.py"
    target.write_text(ALPINE)

    changes = parse_multi_file_patch(_rewrite_patch("app.py"))
    apply_changes(changes)

    backup = project_dir / ".xtr" / "backup" / "app.py.orig"
    assert backup.exists()
    assert backup.read_text() == ALPINE


def test_rewrite_in_nested_directory(tmp_path):
    """A rewrite target under a subdirectory keeps its path."""
    project_dir = tmp_path / "proj"
    (project_dir / "lk_bootstrap").mkdir(parents=True)
    os.chdir(project_dir)

    target = project_dir / "lk_bootstrap" / "bootstrap_gate1_remote.sh"
    target.write_text(ALPINE)

    changes = parse_multi_file_patch(
        _rewrite_patch("lk_bootstrap/bootstrap_gate1_remote.sh")
    )
    apply_changes(changes)

    assert target.read_text() == DEBIAN


def test_rewrite_of_absent_file_creates_it(tmp_path):
    """Nothing to delete, so the pair degrades to a plain creation."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "brand_new.sh"
    assert not target.exists()

    changes = parse_multi_file_patch(_rewrite_patch("brand_new.sh"))
    apply_changes(changes)

    assert target.read_text() == DEBIAN


def test_create_then_delete_is_not_a_rewrite(tmp_path):
    """
    The inverse order is not honoured. Only delete-then-create carries an
    explicit statement of intent ahead of the replacement body.
    """
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "app.py"
    target.write_text(ALPINE)

    patch_content = (
        f"--- a/app.py\n{START}\n{MID}\n{DEBIAN}{END}\n--- a/app.py\n! DELETE FILE\n"
    )
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    assert target.read_text() == ALPINE, "file should be left untouched"


def test_lone_create_block_on_existing_file_is_refused(tmp_path, capsys):
    """
    An empty search block with no delete ahead of it is also what a block that
    lost its search text looks like. Refuse it rather than truncate the file.
    """
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "app.py"
    target.write_text(ALPINE)

    patch_content = f"--- a/app.py\n{START}\n{MID}\n{DEBIAN}{END}\n"
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    assert target.read_text() == ALPINE
    out = capsys.readouterr().out
    assert "Cannot Create, File Exists" in out
    assert "Block Not Found" not in out, "no search was supplied, so none failed"


def test_stray_delete_directive_reports_honestly(tmp_path, capsys):
    """A delete directive alongside unrelated hunks is named for what it is."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "app.py"
    target.write_text("alpha\nbeta\ngamma\n")

    patch_content = (
        "--- a/app.py\n"
        "! DELETE FILE\n"
        "--- a/app.py\n"
        f"{START}\n"
        "alpha\n"
        f"{MID}\n"
        "ALPHA\n"
        f"{END}\n"
    )
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    out = capsys.readouterr().out
    assert "Stray Delete Directive" in out
    assert "Block Not Found" not in out
    assert target.exists(), "a stray directive must not delete the file"


def test_rewrite_accepts_legacy_zero_hint_spelling(tmp_path):
    """doc/GEMINI.md teaches `<<<< 0` for create and delete; honour that pair."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "app.py"
    target.write_text(ALPINE)

    patch_content = (
        "--- a/app.py\n"
        f"{START} 0\n"
        f"{MID}\n"
        f"{END}\n"
        "--- a/app.py\n"
        f"{START} 0\n"
        f"{MID}\n"
        f"{DEBIAN}"
        f"{END}\n"
    )
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    assert target.read_text() == DEBIAN


def test_delete_then_insert_at_a_real_line_is_not_a_rewrite(tmp_path, capsys):
    """A hint past the top of the file contradicts the delete that precedes it."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "app.py"
    target.write_text(ALPINE)

    patch_content = (
        f"--- a/app.py\n! DELETE FILE\n--- a/app.py\n{START} 20\n{MID}\n{DEBIAN}{END}\n"
    )
    changes = parse_multi_file_patch(patch_content)
    apply_changes(changes)

    out = capsys.readouterr().out
    assert "REWRITTEN" not in out
    assert "Stray Delete Directive" in out


def test_rewrite_is_revertable(tmp_path):
    """--revert walks a rewrite back to the pre-patch content."""
    from xtrshow.repatch import revert_file

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    os.chdir(project_dir)

    target = project_dir / "app.py"
    target.write_text(ALPINE)

    changes = parse_multi_file_patch(_rewrite_patch("app.py"))
    apply_changes(changes)
    assert target.read_text() == DEBIAN

    revert_file(str(target))
    assert target.read_text() == ALPINE


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
