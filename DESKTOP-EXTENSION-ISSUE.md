# Voice Mode: why it went silent in the VS Code extension — RESOLVED

**Status: RESOLVED.** Voice mode now speaks in **both** the terminal CLI and the VS Code
extension panel. Two independent bugs were stacked on top of each other; both are fixed.

---

## Root causes (two separate bugs)

### Bug 1 — UTF-8 BOM in `settings.json` (blocked hooks entirely)

`install.ps1` wrote `settings.json` with Windows PowerShell 5.1
`Set-Content -Encoding UTF8`, which **prepends a UTF-8 BOM** (bytes `EF BB BF`).
Claude Code (Node.js) refuses to parse a JSON file that starts with a BOM and then
**silently ignores the whole settings file** — so no hooks loaded at all, in any surface.

**Fix:** `install.ps1` now writes BOM-less UTF-8 via `System.Text.UTF8Encoding($false)`.
The live `settings.json` was also rewritten BOM-free.

### Bug 2 — `last_assistant_message` isn't populated in the extension's Stop payload

This is the one that kept the **extension** silent even after the BOM was fixed.

- From the **terminal CLI**, the `Stop` hook payload **does** include
  `last_assistant_message` (verified live — the field held the exact spoken text).
- From the **VS Code extension**, the `Stop` payload does **not** populate that field
  (empty/absent). `speak-response.ps1` read only `last_assistant_message`, saw nothing,
  and quietly `exit 0`'d every turn — so the extension never spoke.

**This is exactly what the laptop instance diagnosed.** The reply text has to be pulled
from the **transcript file** whose path the hook is given (`transcript_path`), not from a
single field.

**Fix:** `speak-response.ps1` now prefers `last_assistant_message`, and when it's empty
falls back to reading `transcript_path`: it walks the JSONL **backward** to the most recent
`assistant` message that contains text and speaks that. Reads the transcript as UTF-8 so
em-dashes / smart quotes aren't garbled. This covers **both** surfaces:

- CLI → uses `last_assistant_message` (present).
- Extension → falls back to the transcript (works).

---

## How it was verified

- Fed the hook a **fake payload containing only `transcript_path`** (no
  `last_assistant_message`) via real child-process stdin — the fallback correctly extracted
  the most recent assistant reply from a 391-line transcript and reached the speak step.
- Confirmed live in the **extension**: replies are now spoken aloud.

---

## Files changed

- `install.ps1` — BOM-less settings write.
- `hooks/speak-response.ps1` — transcript fallback + UTF-8 transcript read.

Nothing else in the setup needed to change (toggle flag, worker, voice-guard, and the
settings hook shape were all already correct).

---

## Environment where this was fixed (desktop)

| Item | Value |
|------|-------|
| Windows user | `desktop-jbu43pj\deskt` (`USERPROFILE = C:\Users\Deskt`) |
| Hooks + settings | `C:\Users\Deskt\.claude\` |
| Claude CLI | 2.1.92 |
| VS Code extension | anthropic.claude-code-2.1.207 |

Credit: cross-machine diff with the laptop instance (where the extension already worked)
pinpointed Bug 2 — the transcript-vs-field difference.
