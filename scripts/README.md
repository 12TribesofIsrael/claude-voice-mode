# scripts/

Helper scripts for claude-voice-mode.

| Script | What it does |
|--------|--------------|
| `read-document.ps1` | Reads a PDF from `documents/` out loud, page by page, like an audiobook. Defaults to the free/offline Windows voice (unlimited); `-Premium` routes through ElevenLabs for short docs. Remembers your place so you can resume. Controls while reading: `p` pause/resume, `n` next page, `q` quit. |

See `documents/README.md` for usage examples, or double-click `Read Document.bat` in
the repo root.
