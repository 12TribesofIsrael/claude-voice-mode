# Claude Voice Mode 🔊

Make **Claude Code read its replies out loud** on Windows, using the free
text-to-speech voice already built into Windows. No API keys, no accounts,
no internet — it all runs on your own PC.

Flip it on when you want to code hands-free and just *listen* to Claude's
answers. Flip it off and it's silent again.

---

## Quick start (copy-paste)

Open **PowerShell** and run this one line — it downloads the project and sets
everything up:

```powershell
git clone https://github.com/12TribesofIsrael/claude-voice-mode.git; cd claude-voice-mode; .\install.ps1
```

Then **restart Claude Code**, turn the voice on with `.\voice-on.ps1`, and
start talking. That's the whole setup.

---

## What this actually is (in plain terms)

Claude Code lets you run a little script every time it finishes answering.
That "run something when Claude finishes" trigger is called a **hook**.

This project is three tiny scripts wired into that hook:

| File | What it does (plain English) |
|------|------------------------------|
| `hooks/speak-response.ps1` | The main one. When Claude finishes talking, this grabs Claude's reply, cleans out the code, links, and symbols (so it doesn't read gibberish), shortens it, and hands it off to be spoken. |
| `hooks/speak-worker.ps1` | The mouth. It takes the cleaned-up text and actually says it through your speakers using Windows' built-in voice. |
| `hooks/voice-guard.ps1` | The manners. When voice mode is on, it quietly tells Claude "keep your answer short and plain" so you get 1–3 spoken sentences instead of a wall of text. |

There's also an **on/off switch**: a tiny marker file in your temp folder.
- Marker file **exists** → Claude talks.
- Marker file **gone** → Claude is silent.

That's the whole trick. `voice-on.ps1` creates the marker, `voice-off.ps1`
deletes it.

---

## Install (one time)

1. Open **PowerShell** and go to this folder:
   ```powershell
   cd C:\Users\Owner\repos\claude-voice-mode
   ```
2. Run the installer:
   ```powershell
   .\install.ps1
   ```
   This copies the three scripts into your Claude settings folder and wires
   up the hook. It backs up your existing settings first, and keeps any
   other hooks you already have.
3. **Restart Claude Code** so it picks up the new hook.

That's it. You only do this once.

---

## Daily use

**Turn the voice ON:**
```powershell
.\voice-on.ps1
```

**Turn the voice OFF:**
```powershell
.\voice-off.ps1
```

(If you'd rather not `cd` into the folder every time, the raw one-liners are:)
```powershell
# ON
New-Item -ItemType File -Force "$env:TEMP\claude-voice-enabled" | Out-Null
# OFF
Remove-Item -Force "$env:TEMP\claude-voice-enabled" -ErrorAction SilentlyContinue
```

When it's ON, just talk to Claude like normal. Every time it finishes a
reply, you'll hear it. When it's OFF, nothing is spoken and Claude behaves
exactly as it did before.

### Works in every repo and every window

You install once. The switch is machine-wide, so it applies to **every repo
and every VS Code / Claude Code window** on your PC at the same time — you
don't set it up again per project. (A Claude session that was already open
before you installed needs a restart to pick up the hook.)

### Type `voice-on` / `voice-off` from anywhere

So you don't have to `cd` into this folder, run this once:

```powershell
.\add-shortcuts.ps1
```

It adds two commands to your PowerShell profile. Open a new terminal and you
can now type `voice-on` or `voice-off` in **any** folder or VS Code terminal.

---

## When does it stay quiet on purpose?

- When voice mode is **off** (no marker file).
- On `/clear`, `/compact`, and `/resume` — those aren't real answers, so
  they never trigger the voice.
- When a reply is empty.

---

## The Norton gotcha (important on this PC)

Norton's behavioral protection is twitchy about *any* PowerShell that
launches more PowerShell. The first version of this script used a couple of
tricks (a scrambled/encoded command and a system-level launcher) that Norton
flagged as `IDP.HELU.PSE80` and killed mid-sentence — the voice would cut off
after a few words.

The current version was rewritten to look completely ordinary: plain text in
a temp file, a normal script launch, no scrambling, no `Bypass` flag. That
alone stopped the false alarm on this machine.

**If Norton ever interrupts the voice again**, whitelist the folder:

1. Open Norton → **Settings** → **Antivirus** → **Scans and Risks** tab.
2. Find **Exclusions / Low Risks**.
3. Next to *"Items to Exclude from Auto-Protect, Script Control, SONAR and
   Download Intelligence Detection"* click **Configure** → **Add** →
   **Folders** → pick `C:\Users\<you>\.claude\hooks` → **OK** → **Apply**.
4. Do the same under *"Items to Exclude from Scans"*.

To get back anything Norton already quarantined: Norton → **Security
History** → filter to **Quarantine** → find the `powershell.exe` /
`IDP.HELU.PSE80` entry → **Restore & Exclude this file**.

---

## Troubleshooting

**I hear nothing.**
- Is voice mode on? Run `.\voice-on.ps1`.
- Did you restart Claude Code after installing? The hook loads at startup.
- Test your speakers + Windows voice directly:
  ```powershell
  Add-Type -AssemblyName System.Speech
  (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('test')
  ```

**It cuts off partway.** That's almost always Norton — see the section above.

**It reads too fast/slow.** Open `hooks/speak-worker.ps1` and change
`$s.Rate = 1` (range is -10 slowest to 10 fastest, 0 is normal), then re-run
`.\install.ps1`.

**It talks too much.** It already trims to ~500 characters. Lower that number
in `hooks/speak-response.ps1` if you want shorter.

---

## How it fits together (the 10-second version)

```
You send a message
      │
Claude answers  ─────────────►  voice-guard.ps1  (asks Claude to keep it short, if voice is ON)
      │
Claude finishes  ────────────►  speak-response.ps1  (clean + shorten the text)
                                      │
                                      ▼
                                speak-worker.ps1  (Windows voice says it out loud)
```

Runs 100% locally. Free. Windows only.
