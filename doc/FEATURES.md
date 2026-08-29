# Features

## `xtrshow` (Context Extractor)

**xtrshow** is a Terminal User Interface (TUI) designed to rapidly select, compress, and format code context for Large Language Models.

### 🖥️ Interactive Interface
* **Tree View Navigation:** Browse file hierarchies naturally using arrow keys (`↑`, `↓`, `←`, `→`).
* **Visual Feedback:** Clear indicators for files (`📄`) vs directories (`📁`), selection status (`[×]`), and expansion state.
* **Quick Selection:** Toggle individual files or select entire directories recursively with `Space` or `a`/`A`.
* **Size Preview:** Real-time summary of selected file count and total size (KB/MB) to help manage LLM context window limits.

### 📤 Optimized Output
* **LLM-Friendly Formatting:** Wraps content in Markdown code blocks with language identifiers.
* **Line Numbers:** Automatically prefixes lines with numbers (e.g., ` 12: def func():`) to allow precise referencing by LLMs.
* **Clean Mode:** Optional `--clean` flag to output raw text without line numbers.
* **Multi-File Export:** The `--multi` option splits output into individual files (e.g., `.xtrshow/src__main.py.xtr.md`) for RAG pipelines or specific upload requirements.

### 🔍 Filtering & Scope
* **Smart Ignores:** Automatically ignores common noise directories (`node_modules`, `.git`, `__pycache__`) via the `--ignore` flag.
* **Pattern Matching:** Filter visible files by name or extension using `--pattern` (e.g., `--pattern ".rs"`).
* **Depth Control:** Limit directory traversal depth with `--max-depth`.

---

## `xtrpatch` (Surgical Patcher)

**xtrpatch** is a robust patching tool designed specifically to handle the unpredictability of LLM-generated code.

### 🛡️ Safety & Versioning
* **Atomic Backups:** Every modification triggers a backup under the project's `.xtr/backup/` directory.
* **Versioning History:** Backups are versioned (e.g., `file.py.orig`, `file.py.1.orig`, `file.py.2.orig`), allowing you to step back through multiple changes.
* **Patch Archival:** The patch file used to create a change is archived alongside the backup (`file.py.1.patch`), linking the *cause* (the patch) to the *effect* (the backup).
* **Revert Capability:** Built-in `--revert` command to restore files to their previous state instantly.

### 🧩 Robust Patching
* **Whitespace Insensitivity:** Uses "fuzzy" matching to ignore differences in indentation or blank lines, which LLMs often get wrong.
* **Line Hints:** Supports `<<<< START~END` syntax (e.g., `<<<< 50~55`) to help disambiguate identical code blocks found in multiple places.
* **Tail Context (Lookahead):** Supports a secondary `====` block to verify the code *following* the insertion point, ensuring patches are applied in exactly the correct location.
* **Idempotency Checks:** Detects if a patch has already been applied and skips it gracefully instead of breaking the file.

### ⚡ Full Lifecycle Management
* **Multi-File Support:** Apply changes to multiple files in a single pass from a single response.
* **File Creation:** Detects intent to create new files (via empty Search blocks).
* **File Deletion:** Detects intent to delete files (via empty Search AND empty Replace blocks), while still backing them up first.