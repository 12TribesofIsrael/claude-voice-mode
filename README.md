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

1. Open **PowerShell** and go to the folder you cloned (the `git clone`
   above creates a `claude-voice-mode` folder wherever you ran it):
   ```powershell
   cd claude-voice-mode
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

### ⚠ Re-run the installer after every `git pull`

The hook scripts *run* from `%USERPROFILE%\.claude\hooks`, which is **outside
this repo**. `git pull` updates the repo — it does **not** update the copies
that actually speak. If you pull new code and skip the installer, you get an
old worker driven by a new control panel: the panel looks fine, but the
settings you change are written to a file the old worker never reads, so
premium silently never fires.

So after any `git pull`, just run:

```powershell
.\install.ps1
```

It's safe to re-run any time. The control panel also checks this for you and
shows a warning banner when your installed hooks don't match the repo.

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

It adds these commands to your PowerShell profile. Open a new terminal and
you can use them in **any** folder or VS Code terminal:

- `voice-on` / `voice-off` — turn spoken replies on or off
- `voice-list` — show the voices installed on your PC
- `voice-set <name>` — pick a voice, e.g. `voice-set Zira`

---

## Premium natural voices (ElevenLabs) — optional

The free Windows voices are robotic. If you want a genuinely human‑sounding
voice — for recording content, demos, or just nicer listening — Claude Voice
Mode can route replies through **ElevenLabs** instead. It's an **opt‑in toggle**:
the free Windows voice stays the default, and you flip premium on only when you
want it (so you don't burn credits during all‑day coding).

**A visual control panel** makes it easy — great to show on screen while you
record. The simplest way to open it is to **double-click `Voice Panel.bat`**
in this folder: it starts the local server in its own window and opens the
panel in your browser. From there you just click the on/off toggle — no
PowerShell and no scripts to run by hand.

Prefer the terminal? You can also launch it with:

```powershell
voice-panel          # after add-shortcuts.ps1, from any terminal
# or:  .\start-webapp.ps1
```

Whichever way you open it, the panel's on/off switch and the `voice-on.ps1`
script are two doors to the *same* setting — you don't need to run anything
before opening the panel. Just keep the little server window open while you
use it; closing it stops the panel (voice mode itself stays as you left it).

It opens a local dashboard (`http://127.0.0.1:8770`) where you can:

- toggle **voice on/off** and **free ⇄ premium**,
- paste your **ElevenLabs API key** (stored locally, never committed),
- **pick a voice** from your ElevenLabs library and preview it,
- choose the **model** (Turbo/Flash = ½ credits, Multilingual v2 = best quality),
- watch your **plan and remaining credits** in real time,
- **Test through Claude** to hear the exact pipeline before you record.

**How the pipeline chooses a voice:** when premium is on *and* a key + voice ID
are set, replies are synthesized by ElevenLabs and played back. On **any**
problem — offline, bad key, out of credits — it **automatically falls back** to
the free Windows voice, so you're never left silent.

**Your key** lives in `%USERPROFILE%\.claude\hooks\voice-config.json` (outside
this repo, gitignored). Get it from ElevenLabs → avatar → **API key**.

> **Cost reality:** ElevenLabs bills ~1 credit per character (½ on Turbo/Flash),
> and roughly 1,000 characters ≈ 1 minute of speech. Leaving premium on during a
> full day of coding can burn a monthly plan in a day or two — that's why it's a
> deliberate toggle. Use free Windows voice for marathons, premium for content.

The panel needs **Python 3** (already required by nothing else here) and only
talks to ElevenLabs using your own key. Nothing else leaves your machine.

---

## Changing the free Windows voice

List what you have, then pick one:

```powershell
voice-list
voice-set Zira      # or David, or a partial name — first match wins
```

The change takes effect on Claude's next reply. To go back to the default,
just delete the file `%USERPROFILE%\.claude\hooks\voice-name.txt`.

### Want more voices?

Windows hides some extra voices (like **Microsoft Mark**) from the classic
speech engine. To unlock them, run this once and click **Yes** at the
admin prompt:

```powershell
.\unlock-voices.ps1
```

Then restart your terminals and `voice-set Mark`. You can also download more
voices in **Windows Settings → Time & language → Speech → Manage voices**.

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
- Did you `git pull` without re-running `.\install.ps1`? See the warning above —
  this is the most common cause of "the panel does nothing".
- Test your speakers + Windows voice directly:
  ```powershell
  Add-Type -AssemblyName System.Speech
  (New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('test')
  ```

**It cuts off partway.** That's almost always Norton — see the section above.

**I toggled premium on but still hear the robotic Windows voice.**
- Most likely your installed hooks are stale — re-run `.\install.ps1` and
  restart Claude Code. The panel shows a warning banner when this is the cause.
- Premium only fires when a key **and** a voice ID are both set. Picking a voice
  in the panel is a separate step from saving the key.

**The panel says my key works but shows no plan or credits.** Your key is
scope-restricted and lacks **User: Read**. That only hides the billing view —
voices and speech still work normally. Enable that scope on the key in
ElevenLabs (or create an unrestricted key) if you want the credits meter.

**It reads too fast/slow.** Open `hooks/speak-worker.ps1` and change
`$s.Rate = 1` (range is -10 slowest to 10 fastest, 0 is normal), then re-run
`.\install.ps1`.

**It talks too much / gets cut off mid-sentence.** It trims spoken text to
~6000 characters on a word boundary. Raise or lower that number in
`hooks/speak-response.ps1` to taste. The `hooks/voice-guard.ps1` hook also
tells Claude how long spoken replies should be — it currently allows full,
clear prose; edit that reminder string if you want it terser.

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
