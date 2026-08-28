# xtrshow

<div align="center">

<img src="https://github.com/Aloecraft-org/xtrshow/blob/main/doc/icon.png" style="height:96px; width:96px;"/>

**Code Extraction & Patching Made Easy**

[![PyPI Version](https://img.shields.io/pypi/v/xtrshow.svg)](https://pypi.org/project/xtrshow/)
[![Python Versions](https://img.shields.io/pypi/pyversions/xtrshow.svg)](https://pypi.org/project/xtrshow/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[![CI Status](https://github.com/Aloecraft-org/xtrshow/actions/workflows/main.yml/badge.svg)](https://github.com/Aloecraft-org/xtrshow/actions/workflows/main.yml)
[![Downloads](https://static.pepy.tech/badge/xtrshow)](https://pepy.tech/project/xtrshow)

</div>

`xtrshow` is a CLI suite that closes the loop between your local codebase and AI coding assistants (ChatGPT, Claude, Gemini, etc.). It removes the two biggest points of friction in AI-assisted development:

1. **Getting code INTO the LLM** — interactively select files and format them with line numbers so the model can anchor edits to exact locations.
2. **Getting code OUT of the LLM** — apply the model's changes safely, atomically, and reversibly, without copy-pasting dozens of snippets.

No API keys, no agents, no daemons. It works with any chat interface — including free tiers — because the "protocol" is just text.

## Installation

```bash
pip install xtrshow
```

Installs two commands: `xtrshow` (the extractor) and `xtrpatch` (the patcher).

## Quickstart: Extract → Prompt → Apply

**1. Extract context.** Select files in the TUI; the formatted output goes to stdout:

```bash
xtrshow | pbcopy        # macOS
xtrshow | xclip -sel c  # Linux
xtrshow | clip          # Windows
```

**2. Prompt.** Paste the context into your LLM along with the patch-format instructions:

```bash
xtrshow -p   # prints a copy-pasteable instruction block
```

**3. Apply.** Save the LLM's reply to a file and apply it:

```bash
xtrpatch changes.txt
```

Made a mistake? `xtrpatch --revert changes.txt` unwinds every file the patch touched.

> **Tip:** Iterating on the same files? `xtrshow --update` re-exports your last selection without opening the TUI.

👉 **[Read the Full Getting Started Guide](doc/GETTING_STARTED.md)**

## Why not just use git diffs?

LLMs are unreliable at producing valid unified diffs — line numbers drift, context lines get hallucinated, and one bad hunk poisons the file. `xtrpatch` uses a **Search & Replace block** format designed around how models actually fail:

* **Fuzzy whitespace matching** absorbs the indentation errors models constantly make.
* **Wildcard anchors** (`~~~~`) let the model match on stable signatures and skip volatile interior lines.
* **Tail context** disambiguates near-duplicate blocks with a lookahead check.
* **Per-hunk annotations** (`@ why this change`) surface in the apply report, so failures are self-describing and feed straight back into the LLM for self-correction.

## Features

### `xtrshow` (The Extractor)

* **Interactive TUI:** fast, keyboard-driven file selection with directory expand/collapse and live size stats.
* **LLM-optimized output:** line-numbered content with `--- a/path` headers the patcher can target.
* **File metadata:** each export block carries a `# meta:` line with size, line count, modified/created dates, and a SHA-256 digest so the model can tell at a glance whether it has already seen a file (`--no-meta` to omit the line, `--no-hash` for just the digest).
* **Smart filtering:** ignores `node_modules`, `.git`, build artifacts, and friends by default (`--no-ignore` to disable).
* **Re-export:** `--update` replays your last selection from the saved manifest.
* **Multi-file export:** `--multi` writes one file per selection — useful for RAG pipelines.
* **Prompt printer:** `-p` emits the LLM instruction block for the patch format.

### `xtrpatch` (The Patcher)

* **Safety first:** automatic, versioned backups in `.xtrpatch/` before every modification.
* **Checksum verification:** warns when a file was edited outside the patch loop since the last apply.
* **Conflict detection:** overlapping hunks are caught pre-flight and skipped, never blindly stacked.
* **Full lifecycle:** modify, insert, create files, delete sections, delete whole files (`! DELETE FILE`), replace a file wholesale (`! DELETE FILE` + a create block).
* **Idempotent:** re-applying a patch detects already-applied hunks and skips them.
* **Error reports:** failed applies generate a `.rpterr` bundle (original + patch + log) you can paste straight back to the LLM.
* **Undo button:** `--revert` restores the most recent backup — per file, or for every file in a patch.

## License

Apache 2.0