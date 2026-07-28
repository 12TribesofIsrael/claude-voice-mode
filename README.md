# Claude Voice Mode 🔊

Make **Claude Code read its replies out loud** on Windows, using the free
text-to-speech voice already built into Windows. No API keys, no accounts,
no internet — it all runs on your own PC.

Flip it on when you want to code hands-free and just *listen* to Claude's
answers. Flip it off and it's silent again.

It also ships a **[Document Reader](#document-reader--listen-to-your-own-docs-)** —
drop in a Markdown, text or PDF file and it reads *that* aloud instead, with play,
pause, seek and resume. Double-click `Document Reader.bat`.

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

### Hear the last answer again — "repeat that"

Missed something or want it read back? Just say **"repeat that"** (or "say that
again", "read that back", "one more time"). Claude prints its previous answer
again word-for-word, and the voice hook speaks it right back to you — nothing is
re-generated, it's a literal replay of what you just heard.

This is a small **skill** (`skills/repeat-that/`) that the installer copies into
`%USERPROFILE%\.claude\skills`. It ships with voice mode, so after you run
`.\install.ps1` it just works. Restart Claude Code once so it's picked up.

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

Be warned that all of these are the same 2000s-era engine. They stitch together
recorded fragments and model nothing about the rhythm or emphasis of a sentence,
which is exactly why they sound robotic. Unlocking more of them gets you a
different robot, not a better voice. For that, see the next section.

---

## Free natural voices (no ElevenLabs bill)

There are two ways to sound natural without paying per character. Install both
with one command — it takes a few minutes and about 120 MB:

```powershell
.\install-voices.ps1
.\install.ps1            # refresh the installed hooks
```

Then pick an engine in the Voice Panel. The worker tries engines in order and
falls through on any failure, so the robotic Windows voice is always underneath
as the thing that cannot fail:

**ElevenLabs → Microsoft neural → Piper → Windows**

### Microsoft neural — natural, free, online

The same **Andrew** and **Ava** voices Windows offers for Narrator, reached
through Microsoft's free read-aloud service. No API key, no account, no credits.
47 English voices with distinct personalities.

> **Why not use the Narrator voices directly?** You can install them under
> **Settings → Accessibility → Narrator → Add natural voices**, but no app can
> drive them. The packages ship model data and nothing else: no speech engine,
> and the COM class their token points at is not registered anywhere on the
> machine. They are reachable by Narrator alone, by design. This engine gets you
> the same voices from the service instead.

Caveats worth knowing: it needs internet, and it is an undocumented endpoint
Microsoft could change without notice. Treat it as a convenience, not a
foundation — and think twice before building a paid product on it.

### Piper — natural, free, fully offline

Neural speech that runs on your CPU. No internet, no key, no cost per word, and
a permissive license, so it is the safe one to ship. On a plain desktop CPU it
synthesizes about ten times faster than real time, so it never makes you wait.

It is also the engine you would **fine-tune on your own recorded voice** later.
Record 30–60 minutes of clean audio, cut it into short clips, transcribe them,
train once, and the panel entry just starts sounding like you.

Pick a different voice model with:

```powershell
.\install-voices.ps1 -PiperVoice en_US-lessac-medium
```

### How the two stay fast

Loading a voice model costs about three quarters of a second, and starting
Python costs about half. The worker is launched fresh for every reply, so paying
those per reply would be very noticeable. Instead `hooks/tts-server.py` runs as a
small local server that keeps the model warm and answers over loopback. The
worker starts it on first use, and it shuts itself down after 30 idle minutes.
A warm sentence comes back in about half a second.

---

## Document Reader — listen to your own docs 📖

Everything above is about hearing **Claude's replies**. The Document Reader is the
other half: hand it a file *you* wrote and it reads that aloud instead, with a real
player.

**Double-click `Document Reader.bat`.** Drop in a `.md`, `.txt` or `.pdf` and press
play.

- **Play, pause, skip, seek.** Click any paragraph to jump straight there. Space
  bar plays and pauses, arrow keys move a part at a time.
- **Picks up where you left off.** Close the tab mid-document and it resumes at the
  same paragraph next time, per document.
- **Starts almost immediately.** The document is split into parts and only the
  first one is ever waited for; the rest are generated while you listen. On this
  machine the first words start in about **one second** on Piper, against roughly a
  minute if the whole document were generated up front.
- **Every voice the control panel offers** — all ~47 Microsoft neural voices, your
  ElevenLabs voices, any Piper model on disk, and the Windows voices. It tells you
  how long a document will take to listen to and to generate before you start, and
  what it will cost in ElevenLabs characters if you pick that one.
- **Generated audio is cached**, so replaying a document is instant and never bills
  you twice for the same paragraph.

### Its voice is separate from Claude's, on purpose

`voice-config.json` is machine-wide. If the reader shared the same setting, then
picking a voice to narrate a long document would silently change how Claude speaks
to you for the rest of the day. So the reader keeps its own engine and voice, and
the page shows you which engine Voice Mode is on so you can see they are
independent.

### What it does with Markdown

Code blocks and tables are skipped with a short spoken note, so you know something
was left out rather than losing it silently. Headings are read as headings with a
pause. Links become their label, bare URLs are dropped, and typographic punctuation
is converted so an em dash becomes a pause instead of the words "em dash". PDFs go
through `pdftotext`, which ships inside Git for Windows.

Documents, their audio, and your position are stored in `webapp/.reader/`, which is
git-ignored — nothing you read ends up in a commit.

> The older `scripts/read-document.ps1` still works and still reads PDFs in a
> console with keyboard controls. The reader is the same idea with a real player,
> Markdown support, and the natural voices.

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
