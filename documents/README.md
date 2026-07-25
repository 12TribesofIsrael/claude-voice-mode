# documents/

Drop PDFs here to have them read out loud by the voice reader.

- The actual PDF files are **git-ignored** — this is a public repo and the books
  are personal, so only this README is tracked. Your PDFs stay local.
- `.read-progress.json` (also ignored) remembers the last page read per file so you
  can resume where you left off.

## How to read one

Double-click **`Read Document.bat`** in the repo root — it reads the newest PDF in
this folder with the free Windows voice (unlimited, offline).

Or from a terminal:

```powershell
# newest PDF, resume where you left off
powershell -NoProfile -File scripts\read-document.ps1

# a specific file, starting at page 12
powershell -NoProfile -File scripts\read-document.ps1 -File documents\my-book.pdf -StartPage 12

# list what's here
powershell -NoProfile -File scripts\read-document.ps1 -List

# natural ElevenLabs voice (SHORT docs only — uses your paid quota)
powershell -NoProfile -File scripts\read-document.ps1 -Premium
```

While it's reading (free voice):  **p** = pause/resume, **n** = next page, **q** = quit.
