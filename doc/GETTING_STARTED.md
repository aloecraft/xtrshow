# Getting Started

**xtrshow** is a CLI suite for extracting codebase context and applying surgical patches. It installs two commands: `xtrshow` (extraction) and `xtrpatch` (application).

## Installation

```bash
pip install xtrshow
```

Requires Python ≥ 3.8. Windows is supported (curses is bundled automatically).

---

## 1. Extracting Code (`xtrshow`)

`xtrshow` opens a Terminal User Interface (TUI) to select files, then formats them into a dense, line-numbered Markdown block on stdout.

### Interactive Mode

```bash
xtrshow              # browse current directory
xtrshow path/to/dir  # browse a specific directory
```

**Keys:**

| Key | Action |
| --- | --- |
| `↑` / `↓` | Move cursor |
| `←` / `→` | Collapse/expand directory (or jump to parent/first child) |
| `Space` | Toggle selection |
| `a` / `A` | Select / deselect everything under the cursor |
| `p` or `Enter` | Confirm and export |
| `q` | Quit without output |

The status bar shows the running count and total size of your selection — useful for staying inside a model's context budget.

### CLI Flags

```bash
xtrshow --pattern ".py"     # filter by filename substring
xtrshow --max-depth 2       # limit recursion depth
xtrshow --clean             # omit line numbers (raw content)
xtrshow -o context.md       # write to a file instead of stdout
xtrshow --no-ignore         # show ignored dirs (.git, node_modules, ...)
xtrshow --no-meta           # omit the per-file metadata line
```

### File Metadata

Each exported file block includes a `# meta:` line under its header with the file's size, line count, and modification date (plus creation date on platforms that track it — macOS and Windows; Linux doesn't expose true creation time):

```
--- a/src/main.py
+++ b/src/main.py
# meta: 4.2 KB | 128 lines | modified 2026-08-26T10:32:11-04:00
```

This gives the LLM a sense of which files are freshest without costing more than a line of context. Pass `--no-meta` to omit it. The line starts with `#`, so it's inert if it ever ends up inside a patch file.

### Re-Exporting (`--update`)

Every export saves your selection to `.xtrshow_manifest`. When you've changed code and want to send the same files back to the LLM, skip the TUI:

```bash
xtrshow --update > context.md
```

### Multi-File Export (`--multi`)

For pipelines that want one file per source file (e.g., RAG ingestion, or project-file uploads to a chat UI):

```bash
xtrshow --multi                 # writes to .xtrshow/
xtrshow --multi ./my_export_dir # custom directory
```

Paths are flattened (`src/main.py` → `src__main.py.xtr.md`).

### Printing the LLM Instructions (`-p`)

```bash
xtrshow -p
```

Prints the instruction block that teaches the model to reply in the Search & Replace format below. Paste it into your prompt once per session.

---

## 2. Applying Changes (`xtrpatch`)

`xtrpatch` reads a text file containing Search & Replace blocks and applies them. Matching is whitespace-normalized ("fuzzy"), so common LLM indentation errors don't cause failures.

### Basic Usage

```bash
# Save the LLM's reply to a file, then:
xtrpatch changes.patch

# If the patch has no file headers, supply the target explicitly:
xtrpatch target_file.py changes.patch
```

### Reading the Report

Each file gets a summary line and a per-hunk breakdown:

```
📄 src/app.py           ✅ SUCCESS (Δ+3 lines)
   1. ✅ @ Add timeout to foo      [Rep: 1, New: 1, Δ+0]
   2. 🧠 @ Default msg param       [Already Applied]
   3. ❌ @ Rename handler          [Block Not Found] ~Line 42
```

| Icon | Meaning |
| --- | --- |
| ✅ APPLIED | Hunk matched and was written |
| 🧠 SKIPPED | Replacement already present (patch re-run) |
| 🛑 BLOCKED | Tail context didn't match — wrong location, aborted |
| ⚡ CONFLICT | Overlaps an earlier hunk — skipped |
| ❌ FAILED | Search block not found |

On any failure, an **error report** (`.rpterr`) is written next to the backup, bundling the original file, the patch, and the log — paste it back to the LLM for self-correction.

### Safety & Versioning

`xtrpatch` never modifies a file without backing it up first.

* **Backups:** `.xtrpatch/<relative_path>/<filename>.orig`, then `.1.orig`, `.2.orig`, … on subsequent patches.
* **Patch archive:** the applied patch is stored alongside each backup (`<filename>.patch`).
* **External-edit detection:** a checksum of the post-patch state is recorded; if the file changes outside the patch loop, the next apply warns you.

Add `.xtrpatch/`, `.xtrshow/`, and `.xtrshow_manifest` to your `.gitignore`.

### Reverting Changes

```bash
xtrpatch --revert src/main.py    # restore a file from its latest backup
xtrpatch --revert changes.patch  # revert every file targeted by a patch
```

Revert restores the **most recent** backup — run it repeatedly to walk further back.

---

## 3. Patch File Specification

### Standard Block (Modify)

```text
--- a/path/to/target.py
@ optional one-line description of the change
<<<< LINE_HINT
[content to find]
====
[content to replace it with]
>>>>
```

* **Header:** `--- a/path/to/file`. Each hunk needs its own header — even a second hunk for the same file.
* **Annotation (optional):** `@ description`. Echoed in the apply report; strongly recommended, since it makes failures self-describing.
* **Start:** `<<<<`, optionally with a line hint: `<<<< 50` (near line 50) or `<<<< 50:60` (range). The hint is a disambiguation nudge — content matching decides. `<<` is accepted as a lenient opener; the closer must always be `>>>>`.
* **Search:** must match content exactly, but leading/trailing whitespace and blank lines are normalized.
* **Divider:** `====`.

If a search block matches more than one place and no hint is given, the hunk fails safe rather than guessing.

### Insertion

Empty search block + a line hint inserts at that line:

```text
--- a/app.py
@ Insert header comment at top
<<<< 1
====
# New header
>>>>
```

A hint past the end of file appends. Add a tail section (below) to anchor the spot robustly.

### File Creation

Empty search block, no hint, file doesn't exist:

```text
--- a/src/new_file.py
<<
====
print("Hello World")
>>>>
```

### File Deletion

Preferred shorthand:

```text
--- a/src/deprecated.py
! DELETE FILE
```

(The legacy form — empty search **and** empty replace — still works.) A backup is taken first, so deletion is revertable.

### Whole-File Replacement

To port a file to a new implementation, delete it and create it again in the
same patch. Both hunks name the same path, delete first:

```text
--- a/src/bootstrap.sh
! DELETE FILE

--- a/src/bootstrap.sh
<<<<
====
#!/bin/bash
apt-get update
>>>>
```

This reports ♻️ REWRITTEN and backs up the original, so it is revertable like
any other change. A create block on its own against a file that already exists
is refused instead: that shape is also what a hunk that lost its search text
looks like, and truncating the file to the replace body on that guess would
throw work away.

### Section Deletion

Real search block, empty replace block.

### Tail Context (Lookahead)

A second `====` section declares lines that must appear **after** the match. If they don't, the hunk is 🛑 BLOCKED instead of applying in the wrong place:

```text
--- a/config.py
<<
version = 1
====
version = 2
====
debug = True
>>>>
```

### Wildcard Anchors (`~~~~`)

Inside a search block, `~~~~` skips interior lines so the model only has to reproduce stable anchors:

```text
--- a/app.py
@ Add timeout param without reciting the body
<<
def process(items):
~~~~
    return result
====
def process(items, timeout=30):
    return result
>>>>
```

| Form | Meaning |
| --- | --- |
| `~~~~` | Skip any number of lines |
| `~~~~4` | Skip up to 4 content lines |
| `~~~~=4` | Skip exactly 4 content lines |

Note: the matched span — anchors *and* skipped interior — is replaced by the replace block, so include everything you want to keep.