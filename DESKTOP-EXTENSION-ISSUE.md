# Voice Mode: Stop hook fires in CLI but NOT in the VS Code extension (DESKTOP)

**Status:** OPEN. Voice mode works from the **terminal `claude` CLI** on this desktop,
but **does not fire at all from the VS Code extension chat panel** on this same desktop.
On the **laptop**, the exact same setup reportedly works fine *inside the VS Code
extension*. This doc is for the laptop's Claude instance to compare against and tell us
what's different / what it did to make the extension fire the hook.

---

## Symptom

- Typing to Claude in the **VS Code side-panel chat** on the desktop → reply is **never
  spoken**, and the Stop hook **never runs** (proven below — no debug log line is written).
- Running `claude -p "..."` in a **PowerShell terminal** on the same desktop → Stop hook
  fires immediately, text is cleaned and spoken aloud. **Works.**

So the pipeline (speak-response.ps1 → speak-worker.ps1 → Windows System.Speech) is 100%
functional. The gap is purely: **the VS Code extension is not invoking the `Stop` hook.**

---

## Environment (DESKTOP — the machine that FAILS in the extension)

| Item | Value |
|------|-------|
| Windows user | `desktop-jbu43pj\deskt` |
| `USERPROFILE` | `C:\Users\Deskt` |
| Hooks + settings live at | `C:\Users\Deskt\.claude\` |
| Repo / workspace `cwd` | `C:\Users\Claude\claude-voice-mode` (note: different user folder than USERPROFILE) |
| Claude CLI (`claude.exe` on PATH) | **2.1.92** at `C:\Users\Deskt\.local\bin\claude.exe` |
| VS Code extension | **anthropic.claude-code-2.1.207-win32-x64** |
| Running `claude` host processes | 3 (PIDs 2424, 23164, 29616) — spawned by the extension |

**Note the version split:** the extension bundles **2.1.207**, but the CLI on PATH is
**2.1.92**. The CLI (2.1.92) fires the hook; the extension (2.1.207) does not. Worth
checking what version the *laptop's extension* is — a version difference is a prime suspect.

---

## What was already found and FIXED on the desktop

1. **UTF-8 BOM in `settings.json` (fixed).** `install.ps1` wrote `settings.json` using
   Windows PowerShell 5.1 `Set-Content -Encoding UTF8`, which **prepends a BOM**
   (bytes `EF BB BF`). Claude Code (Node.js) refuses to parse a JSON file that starts with
   a BOM and then **silently ignores the entire settings.json** — so no hooks loaded at all.
   - Fixed the live file (rewrote BOM-less via `System.Text.UTF8Encoding($false)`).
   - Patched `install.ps1` to write BOM-less going forward.
   - **After this fix the CLI started firing the hook.** But the extension still does not.

2. Confirmed the hook config, paths, and toggle are all correct (see below).

---

## Current desktop config (verified correct)

`C:\Users\Deskt\.claude\settings.json` (BOM-free, valid JSON):

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command",
        "command": "powershell -NoProfile -File \"C:\\Users\\Deskt\\.claude\\hooks\\speak-response.ps1\"",
        "timeout": 10 } ] }
    ],
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command",
        "command": "powershell -NoProfile -File \"C:\\Users\\Deskt\\.claude\\hooks\\voice-guard.ps1\"" } ] }
    ]
  }
}
```

- Hook scripts present: `C:\Users\Deskt\.claude\hooks\{speak-response,speak-worker,voice-guard}.ps1`
- Toggle flag present (voice ON): `%TEMP%\claude-voice-enabled` exists.
- No project-level `.claude/settings.json` or `settings.local.json` overriding it.

---

## Proof the CLI fires it but the extension does not

A temporary debug line was added to the very top of `speak-response.ps1` (before the toggle
gate) that appends every invocation + raw stdin to `%TEMP%\claude-voice-debug.log`.

- **After multiple full VS Code / extension restarts**, completing turns in the **sidebar
  chat**: `claude-voice-debug.log` was **never created** → the Stop hook never ran.
- **One `claude -p` call in a terminal**: log created instantly. Actual captured payload:

```json
{"session_id":"8edee84d-...","transcript_path":"C:\\Users\\Deskt\\.claude\\projects\\...jsonl",
 "cwd":"C:\\Users\\Claude\\claude-voice-mode","permission_mode":"default",
 "hook_event_name":"Stop","stop_hook_active":false,
 "last_assistant_message":"Yo Tommy, voice mode is working in the terminal..."}
```

So on the desktop: **CLI = Stop hook fires. Extension = Stop hook never fires.**

---

## Open questions for the LAPTOP instance (where the extension WORKS)

Please report back on each so we can diff desktop vs laptop:

1. **Extension version** on the laptop (`anthropic.claude-code-x.y.z`) — same 2.1.207 or different?
2. **CLI version** on the laptop (`claude --version`) — does it match the extension, unlike our 2.1.92 vs 2.1.207 split?
3. **Where does the laptop's settings.json live**, and is its `hooks` block byte-for-byte the
   same shape as above? Is it BOM-free?
4. Did the laptop need a **full quit of VS Code (all windows) + reopen**, versus just a
   "Reload Window" / new chat, before the extension picked up the hook? (Suspecting the
   desktop extension host cached a no-hooks snapshot from when settings.json still had the BOM,
   and a soft reload did not re-read it.)
5. Is there anything in the laptop's `settings.json` we're missing on the desktop —
   e.g. an `enableAllProjectMcpServers`, a permissions/hooks trust setting, an
   `--agent` config, or an explicit hooks-enable flag?
6. On the laptop, does `%TEMP%\claude-voice-debug.log` get written when you reply **in the
   extension panel** (add the same debug line to confirm the extension there truly invokes
   the Stop hook)?
7. Anything else the laptop instance changed to make the **extension** (not the CLI) speak.

---

## Leading theory

The desktop extension host process was started while `settings.json` still had the BOM
(so it loaded **zero** hooks), and the "restarts" done since were soft reloads that did not
re-read settings. A **full VS Code shutdown (kill all `Code`/`claude` processes) + relaunch**
after the BOM fix may be all that's needed. The laptop may simply have been started *after*
a clean, BOM-free settings.json existed. **Needs confirmation** — hence this doc.

---

*Written by the desktop Claude instance for cross-machine diff. Debug logging is currently
still enabled at the top of `speak-response.ps1`; remove it once the extension is confirmed firing.*
