# ./tests/test_patch_diagnostics.py
# License: Apache-2.0 (disclaimer at bottom of file)
"""Structural failures must be named and located, never silent."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import xtrshow
from xtrshow.repatch import (
    apply_changes,
    check_changes,
    count_hunk_openers,
    explain_match_failure,
    parse_multi_file_patch,
    report_hunk_drift,
)

UNTERMINATED = """\
--- a/multi.py
@ one
<<<<
def a():
====
def a(x):

--- a/multi.py
@ two
<<<<
def c():
====
def c(x):
>>>>
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


# Resolved from the imported package so the subprocess finds it whether or not
# the tree happens to be pip-installed.
REPO_ROOT = str(Path(xtrshow.__file__).resolve().parent.parent)


def run_cli(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [REPO_ROOT] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    return subprocess.run(
        [sys.executable, "-m", "xtrshow.repatch", *args],
        capture_output=True,
        text=True,
        env=env,
    )


# --- a header terminates an open hunk ---------------------------------------


def test_unterminated_hunk_does_not_swallow_the_next_one(project):
    """The core failure: one missing '>>>>' used to consume the hunk after it."""
    target = project / "multi.py"
    target.write_text("def a():\n    return 1\n\ndef c():\n    return 3\n")

    changes = parse_multi_file_patch(UNTERMINATED)
    hunks = changes["multi.py"]

    assert len(hunks) == 2
    assert hunks[0]["malformed"] == "missing >>>> terminator"
    # The surviving hunk parsed intact rather than being eaten as replace text.
    assert hunks[1].get("malformed") is None
    assert [l.strip() for l in hunks[1]["search"]] == ["def c():"]


def test_surviving_hunk_still_applies(project, capsys):
    target = project / "multi.py"
    target.write_text("def a():\n    return 1\n\ndef c():\n    return 3\n")

    apply_changes(parse_multi_file_patch(UNTERMINATED))
    capsys.readouterr()

    assert "def c(x):" in target.read_text()


def test_malformed_hunk_is_reported_not_dropped(project, capsys):
    target = project / "app.py"
    target.write_text("old\n")

    apply_changes(parse_multi_file_patch("--- a/app.py\n<<<<\nold\n====\nnew\n"))
    out = capsys.readouterr().out

    assert "Unparseable" in out
    assert "missing >>>> terminator" in out


def test_missing_separator_is_reported(project, capsys):
    target = project / "app.py"
    target.write_text("old\n")

    apply_changes(parse_multi_file_patch("--- a/app.py\n<<<<\nold\nnew\n>>>>\n"))
    out = capsys.readouterr().out

    assert "missing ==== separator" in out


def test_header_in_replacement_text_is_still_content(project, capsys):
    """A '--- a/' line only ends a hunk when a hunk opener actually follows it.

    xtrshow's own export format emits those markers, so replacement text that
    documents the format must survive intact.
    """
    target = project / "doc.md"
    target.write_text("placeholder\n")

    patch = """\
--- a/doc.md
<<<<
placeholder
====
Example output:
--- a/src/main.py
+++ b/src/main.py
done
>>>>
"""
    apply_changes(parse_multi_file_patch(patch))
    capsys.readouterr()

    assert "--- a/src/main.py" in target.read_text()
    assert "+++ b/src/main.py" in target.read_text()


# --- the truncation hazard ---------------------------------------------------


def test_truncated_patch_never_deletes_the_target(project, capsys):
    """An empty search + empty replace is also the whole-file delete signature.

    A hunk truncated mid-response leaves exactly that behind, so the delete
    path must require a clean parse. Losing the file here would be the worst
    possible outcome of a model running out of tokens.
    """
    target = project / "keep.py"
    target.write_text("important data\n")

    apply_changes(parse_multi_file_patch("--- a/keep.py\n<<<<\nimportant data\n====\n"))
    out = capsys.readouterr().out

    assert target.exists()
    assert target.read_text() == "important data\n"
    assert "DELETED" not in out


def test_explicit_delete_still_works(project, capsys):
    """The guard must not break the real whole-file delete."""
    target = project / "gone.py"
    target.write_text("bye\n")

    apply_changes(parse_multi_file_patch("--- a/gone.py\n! DELETE FILE\n"))
    capsys.readouterr()

    assert not target.exists()


def test_malformed_hunk_on_missing_file_is_reported(project, capsys):
    apply_changes(parse_multi_file_patch("--- a/nope.py\n<<<<\nfoo\n====\nbar\n"))
    out = capsys.readouterr().out

    assert "Unparseable" in out


# --- hunk-count drift --------------------------------------------------------


def test_count_hunk_openers_counts_both_spellings():
    assert count_hunk_openers("<<<<\n<< 12\n<<<< 5:15\nnot an opener\n") == 3


def test_drift_is_reported_when_hunks_go_missing(capsys):
    lines = []
    missing = report_hunk_drift(
        "<<<<\n<<<<\n<<<<\n", {"a.py": [{"search": []}]}, lines.append
    )

    assert missing == 2
    assert "2 hunk(s) went missing" in lines[0]


def test_no_drift_reported_when_counts_agree():
    lines = []
    assert report_hunk_drift("<<<<\n", {"a.py": [{}]}, lines.append) == 0
    assert lines == []


# --- --check -----------------------------------------------------------------


def test_check_writes_nothing(project):
    target = project / "app.py"
    target.write_text("old\n")
    (project / "p.txt").write_text("--- a/app.py\n<<<<\nold\n====\nnew\n>>>>\n")

    result = run_cli("--check", "p.txt")

    assert result.returncode == 0
    assert target.read_text() == "old\n"
    assert not (project / ".xtr").exists()
    assert "Nothing written" in result.stdout


def test_check_exits_nonzero_on_a_hunk_that_would_fail(project):
    (project / "app.py").write_text("old\n")
    (project / "p.txt").write_text("--- a/app.py\n<<<<\nabsent\n====\nnew\n>>>>\n")

    result = run_cli("--check", "p.txt")

    assert result.returncode == 1
    assert "Block Not Found" in result.stdout


def test_check_exits_nonzero_on_a_malformed_hunk(project):
    (project / "app.py").write_text("old\n")
    (project / "p.txt").write_text("--- a/app.py\n<<<<\nold\n====\nnew\n")

    result = run_cli("--check", "p.txt")

    assert result.returncode == 1
    assert "Unparseable" in result.stdout


def test_check_reports_a_would_be_creation(project):
    (project / "p.txt").write_text("--- a/new.py\n<<<<\n====\nhello\n>>>>\n")

    result = run_cli("--check", "p.txt")

    assert result.returncode == 0
    assert "WOULD CREATE" in result.stdout
    assert not (project / "new.py").exists()


def test_check_does_not_mutate_state_on_repeat(project):
    """Two identical dry runs must report the same thing."""
    (project / "app.py").write_text("old\n")
    (project / "p.txt").write_text("--- a/app.py\n<<<<\nold\n====\nnew\n>>>>\n")

    first = run_cli("--check", "p.txt")
    second = run_cli("--check", "p.txt")

    assert first.stdout == second.stdout


def test_check_and_apply_agree(project, capsys):
    (project / "app.py").write_text("old\n")
    changes = parse_multi_file_patch("--- a/app.py\n<<<<\nold\n====\nnew\n>>>>\n")

    problems = check_changes(changes, lambda _: None)
    apply_changes(changes)
    capsys.readouterr()

    assert problems == 0
    assert (project / "app.py").read_text() == "new\n"


# --- near-miss diagnostics ---------------------------------------------------


def test_diagnosis_names_interior_whitespace():
    msg = explain_match_failure(["    return  total\n"], ["    return total"])
    assert "interior whitespace differs" in msg
    assert "line 1" in msg


def test_diagnosis_names_capitalization():
    msg = explain_match_failure(["class Handler:\n"], ["class handler:"])
    assert "capitalization differs" in msg


def test_diagnosis_names_quote_style():
    msg = explain_match_failure(['x = "hi"\n'], ["x = 'hi'"])
    assert "quote style differs" in msg


def test_diagnosis_points_at_the_closest_line_for_a_typo():
    msg = explain_match_failure(
        ["import os\n", "def compute(value):\n"], ["def comptue(value):"]
    )
    assert "closest is line 2" in msg
    assert "def compute(value):" in msg


def test_diagnosis_reports_where_a_matched_block_diverged():
    msg = explain_match_failure(
        ["def f():\n", "    return 2\n"], ["def f():", "    return 3"]
    )
    assert "diverged at search line 2" in msg
    assert "line 2" in msg


def test_diagnosis_admits_when_nothing_is_close():
    msg = explain_match_failure(["import os\n"], ["frobnicate_the_widgets()"])
    assert "no line resembles" in msg


def test_diagnosis_handles_running_past_end_of_file():
    msg = explain_match_failure(["def f():\n"], ["def f():", "    return 1"])
    assert "ran past end of file" in msg


def test_diagnosis_is_none_for_an_empty_search():
    assert explain_match_failure(["x\n"], []) is None
    assert explain_match_failure(["x\n"], ["   ", ""]) is None


def test_diagnosis_reaches_the_report(project, capsys):
    (project / "app.py").write_text("    return  total\n")

    apply_changes(
        parse_multi_file_patch(
            "--- a/app.py\n<<<<\nreturn total\n====\nreturn x\n>>>>\n"
        )
    )
    out = capsys.readouterr().out

    assert "↳" in out
    assert "interior whitespace differs" in out


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
