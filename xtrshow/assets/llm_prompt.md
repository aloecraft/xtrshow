# Agent Code Modification Format

## Reading the Extracted Context

Files arrive as fenced blocks under a `--- a/path` header:

- Content lines carry an `N:` prefix holding the file's real line numbers. **The prefix is not part of the file.** Strip it from every search and replace block, or the hunk will not match.
- An optional `# meta:` line records size, line count, timestamps, and `sha256` — the digest of the file's bytes on disk.
- Treat the digest as the file's identity. A file re-sent with the same `sha256` is byte-identical to the copy you already have; a different digest means it changed since you last saw it. Timestamps alone do not prove either.

## Writing Changes

- Output all changes as **Search/Replace Blocks**
- The entire response should be wrapped in one pair of **quadruple backticks** (````)
    + never triple backticks, even with multiple files or hunks.
- Hunk consists of,
    + a file header
    + comment
    + opening sequence w/ optional line hint
    + search block
    + replace block
    + optional tail context

**Operations:**

- **Modify:** search + replace.
- **Insert:** empty search + line hint (`<<<< 20`); add a tail line to anchor the spot.
- **Create file:** empty search block.
- **Delete section:** real search + empty replace.
- **Delete file:** `! DELETE FILE` on its own line (no block needed).

**Syntax (Illustration only. Not the output wrapper):**

    --- a/path/to/file.py
    @ optional: describe the change
    <<<< LINE_HINT
    [code to find]
    ====
    [code to replace it with]
    ====
    [optional tail: line that must follow the match]
    >>>>

**Worked Example (this is what a real response looks like):**

````
--- a/a.py
@ Add timeout to foo
<<<<
def foo():
====
def foo(timeout=30):
>>>>

--- a/a.py
@ Default msg param on bar
<<<< 11
def bar(msg):
====
def bar(msg=None):
>>>>

--- a/b.py
@ Set x to 2
<<<< 5:15
x = 1
====
x = 2
>>>>

--- a/b.py
@ Setup z in y builder
<<<<
# build y
y = builder.create_y() \
~~~~4
    .with_z() \
====
    .setup_z() \
>>>>


--- a/b.py
@ Setup j in i builder just before call to build()
<<<<
# build i
i = builder.create_i() \
    .with_j() \
    ~~~~=4
====
    .setup_j() \
====
    .build()
>>>>
````


Worked Example Notes:
- quadruple backticks ARE part of the example, but are NOT part of the patch format. Their function is to ensure that patch renders properly to LLM response window
- search blocks must be an exact match (careful for whitespace and comments)
- each hunk has a comment explaining the change
- response is wrapped in quadruple backticks
- output has multiple patches across multiple files
- search block w/o line hint: `<<<<`
- exact match: `<<<< 11`
- fuzzy match: `<<<< 5:15`
- exact wildcard: `~~~~=4` (exactly 4 lines)
- fuzzy wildcard: `~~~~4` (as many as 4 lines)

**Anchoring Tips:**
- Anchor on stable lines (e.g. function/class signatures, unique declarations)
- Keep search blocks minimal. (Avoid replacing entire functions just to tweak a few lines)
- If a block appears twice, add a neighboring line or set `LINE_HINT` to disambiguate.
- Indentation is normalized. Don't fret leading whitespace.
- `LINE_HINT` (e.g. `<<<< 50` or `<<<< 50:60`) is a fuzzy nudge; the content match decides.
- Each hunk — even a second one for the same file — needs its own `--- a/path` header. (use the real path found inside a code dump (e.g. `src/utils.py`), not the container filename.)
- For an absolute target, drop the `a/` prefix and write the path as-is: `--- /usr/local/lib/x.py` (or `File: /usr/local/lib/x.py`). `a/` is only for repo-relative paths.
- Tail context is useful for disambiguating hunks