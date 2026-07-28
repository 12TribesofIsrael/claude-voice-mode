#!/usr/bin/env python3
"""
Claude Voice Mode - document reader: text extraction, cleanup and chunking.

Turning a written document into something worth listening to is three jobs, and
this module is all three:

  extract    Markdown, plain text or PDF in; a list of typed blocks out. A block
             is one heading, paragraph, list item or quote. Blocks are kept
             separate rather than flattened into one string because they are what
             the player seeks to - clicking a paragraph on screen has to mean
             something in the audio.

  normalize  Written punctuation is not speakable punctuation. An em dash read
             literally becomes the words "em dash", a word hyphenated across a
             line break becomes two nonsense words, and a bare page number in a
             PDF becomes a number shouted mid-sentence. This is a port of
             Format-Speakable from scripts/read-document.ps1, which already
             solved all of that for the console reader.

  chunk      Split into pieces small enough to synthesize quickly. The first
             chunk is deliberately tiny so audio starts within a second or two;
             later chunks are larger because by then we are generating ahead of
             the listener and per-request overhead matters more than latency.

Standard library only, on purpose: the webapp is dependency-free so it runs on a
fresh machine with nothing but Python installed.
"""
import hashlib
import os
import re
import shutil
import subprocess
import unicodedata

# Chunk sizes in characters. FIRST_MAX is small because it is the only chunk the
# listener actually waits for - everything after it is generated while the
# previous one plays.
FIRST_MAX = 240
MAX = 1200

# Hard ceiling per synthesis request. Matches MAX_CHARS in hooks/tts-server.py so
# a chunk can never be silently truncated on the far side.
HARD_MAX = 8000

BLOCK_KINDS = ("heading", "paragraph", "list-item", "quote", "code", "table")

# Kinds that are a notice about skipped content rather than content itself. The
# player dims these, and they always stand alone so they are easy to ignore.
NOTICE_KINDS = ("code", "table")


# --------------------------------------------------------------------------- #
# normalization
# --------------------------------------------------------------------------- #
# Written as escape sequences rather than literal glyphs on purpose. Several of
# these are invisible or indistinguishable in an editor - a non-breaking space
# looks exactly like a space, a minus sign looks exactly like a hyphen - and this
# repo has already lost time to punctuation that looked correct and was not.
_LIG = {
    "\ufb01": "fi", "\ufb02": "fl",
    "\ufb00": "ff", "\ufb03": "ffi", "\ufb04": "ffl",
}

_DASHES = "\u2014\u2013\u2015"    # em dash, en dash, horizontal bar
_SQUOTES = "\u2018\u2019\u2032"   # curly singles, prime
_DQUOTES = "\u201c\u201d\u2033"   # curly doubles, double prime
_ELLIPSIS = "\u2026"
_BULLET = "\u2022"
_NBSP = "\u00a0"
_MINUS = "\u2212"


def normalize(text):
    """Written text in, speakable text out.

    Kept deliberately close to Format-Speakable in scripts/read-document.ps1 so
    both readers pronounce the same document the same way.
    """
    if not text or not text.strip():
        return ""

    for lig, plain in _LIG.items():
        text = text.replace(lig, plain)

    # A bare URL read aloud is thirty seconds of "aitch tee tee pee colon slash
    # slash". Markdown links have already become their label by this point, so
    # what is left here is a raw address with no readable content to lose.
    text = re.sub(r"<?\bhttps?://\S+", " ", text)
    text = re.sub(r"<?\bwww\.\S+", " ", text)

    # "meta-\nbolism" is one word the typesetter broke, not two words.
    text = re.sub(r"-\s*\r?\n\s*", "", text)
    # A line that is nothing but a number is a page number, not a sentence.
    text = re.sub(r"(?m)^\s*\d{1,4}\s*$", " ", text)
    text = re.sub(r"\r?\n", " ", text)

    # A dash tight between two word characters is joining them (twenty-one,
    # 2013-2014) so it stays a hyphen. Every other dash is a clause break, and
    # becomes a comma so the pause survives instead of being read aloud.
    text = re.sub(r"(?<=\w)[" + _DASHES + r"](?=\w)", "-", text)
    text = re.sub(r"\s*[" + _DASHES + r"]\s*", ", ", text)

    text = re.sub(r"[" + _SQUOTES + r"]", "'", text)
    text = re.sub(r"[" + _DQUOTES + r"]", '"', text)
    text = text.replace(_ELLIPSIS, ". ")   # ellipsis -> full stop
    text = text.replace(_BULLET, " ")
    text = text.replace(_NBSP, " ")
    text = text.replace(_MINUS, "-")

    # Anything still non-speakable (emoji, box drawing, arrows) would either be
    # read out by name or swallowed. Drop symbol categories, keep letters,
    # numbers, punctuation and marks.
    text = "".join(
        c for c in text if unicodedata.category(c)[0] not in ("S", "C") or c in " \t"
    )

    text = re.sub(r" *, *(?=,)", "", text)          # collapse ", ,"
    text = re.sub(r"(?<=[.!?]) *,", "", text)       # drop a comma after a full stop
    text = re.sub(r"^\s*,\s*", "", text)
    text = re.sub(r"\s*,\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# --------------------------------------------------------------------------- #
# markdown
# --------------------------------------------------------------------------- #
_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_SETEXT_H1 = re.compile(r"^\s{0,3}=+\s*$")
_SETEXT_H2 = re.compile(r"^\s{0,3}-{2,}\s*$")
_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_ULI = re.compile(r"^\s*[-*+]\s+(.*)$")
_OLI = re.compile(r"^\s*\d{1,3}[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")


def _strip_inline(s):
    """Markdown inline syntax to plain words."""
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)     # image -> alt text
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)      # link -> label
    s = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", s)     # reference link -> label
    s = re.sub(r"`([^`]*)`", r"\1", s)                  # inline code -> contents
    s = re.sub(r"<[^>]+>", " ", s)                      # raw html tags
    s = re.sub(r"(\*\*|__)(.*?)\1", r"\2", s)           # bold
    s = re.sub(r"(?<!\w)([*_])(?!\s)(.+?)(?<!\s)\1(?!\w)", r"\2", s)  # italic
    s = re.sub(r"~~(.*?)~~", r"\1", s)                  # strikethrough
    s = s.replace("\\", "")                             # escapes
    return s


def _from_markdown(raw):
    """Markdown source -> (title, blocks)."""
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # YAML front matter: skip it, but keep a title if it declares one.
    fm_title = ""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                m = re.search(r"(?mi)^title:\s*(.+?)\s*$", "\n".join(lines[1:i]))
                if m:
                    fm_title = m.group(1).strip().strip("\"'")
                lines = lines[i + 1:]
                break

    blocks = []
    para = []

    def flush(kind="paragraph"):
        if para:
            text = normalize(_strip_inline(" ".join(para)))
            if text:
                blocks.append({"kind": kind, "text": text})
            para.clear()

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # Fenced code: swallow to the closing fence and leave one notice behind,
        # so you know something was skipped rather than silently losing it.
        m = _FENCE.match(line)
        if m:
            flush()
            fence = m.group(1)
            i += 1
            while i < n and not lines[i].lstrip().startswith(fence):
                i += 1
            i += 1
            blocks.append({"kind": "code", "text": "Code block omitted."})
            continue

        if not line.strip():
            flush()
            i += 1
            continue

        if _RULE.match(line):
            flush()
            i += 1
            continue

        m = _HEADING.match(line)
        if m:
            flush()
            text = normalize(_strip_inline(m.group(2)))
            if text:
                blocks.append({"kind": "heading", "text": text, "level": len(m.group(1))})
            i += 1
            continue

        # Setext headings: the underline belongs to the line above it.
        if para and i + 0 < n and (_SETEXT_H1.match(line) or _SETEXT_H2.match(line)):
            text = normalize(_strip_inline(" ".join(para)))
            para.clear()
            if text:
                level = 1 if _SETEXT_H1.match(line) else 2
                blocks.append({"kind": "heading", "text": text, "level": level})
            i += 1
            continue

        # Table: a header row followed by a separator row. Announce and skip -
        # read aloud, a table is noise.
        if "|" in line and i + 1 < n and _TABLE_SEP.match(lines[i + 1]) and "|" in lines[i + 1]:
            flush()
            while i < n and lines[i].strip() and "|" in lines[i]:
                i += 1
            blocks.append({"kind": "table", "text": "Table omitted."})
            continue

        m = _QUOTE.match(line)
        if m:
            flush()
            text = normalize(_strip_inline(m.group(1)))
            if text:
                blocks.append({"kind": "quote", "text": text})
            i += 1
            continue

        m = _ULI.match(line) or _OLI.match(line)
        if m:
            flush()
            item = [m.group(1)]
            i += 1
            # Continuation lines are indented and are not themselves a new item.
            while i < n and lines[i].strip() and not _ULI.match(lines[i]) \
                    and not _OLI.match(lines[i]) and not _HEADING.match(lines[i]) \
                    and lines[i].startswith((" ", "\t")):
                item.append(lines[i].strip())
                i += 1
            text = normalize(_strip_inline(" ".join(item)))
            if text:
                blocks.append({"kind": "list-item", "text": text})
            continue

        para.append(line.strip())
        i += 1

    flush()

    title = fm_title
    if not title:
        for b in blocks:
            if b["kind"] == "heading":
                title = b["text"]
                break
    return title, blocks


# --------------------------------------------------------------------------- #
# plain text
# --------------------------------------------------------------------------- #
def _from_text(raw):
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    blocks = []
    for para in re.split(r"\n\s*\n", raw):
        text = normalize(para)
        if text:
            blocks.append({"kind": "paragraph", "text": text})
    title = blocks[0]["text"][:60] if blocks else ""
    return title, blocks


# --------------------------------------------------------------------------- #
# pdf
# --------------------------------------------------------------------------- #
def find_pdftotext():
    """Locate pdftotext.

    It ships inside Git for Windows under mingw64\\bin, which is not on
    PowerShell's or Python's PATH, so probe the usual spots and derive it from
    wherever git itself lives. Same search the console reader does.
    """
    found = shutil.which("pdftotext")
    if found:
        return found

    cands = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        cands.append(os.path.join(base, "Git", "mingw64", "bin", "pdftotext.exe"))
        cands.append(os.path.join(base, "Programs", "Git", "mingw64", "bin", "pdftotext.exe"))

    git = shutil.which("git")
    if git:
        root = os.path.dirname(os.path.dirname(git))
        cands.append(os.path.join(root, "mingw64", "bin", "pdftotext.exe"))

    for c in cands:
        if os.path.isfile(c):
            return c
    return None


def _from_pdf(path):
    exe = find_pdftotext()
    if not exe:
        raise RuntimeError(
            "pdftotext not found. It ships with Git for Windows; install Git or "
            "put Poppler on your PATH, then try again."
        )
    out = path + ".txt"
    try:
        subprocess.run(
            [exe, "-enc", "UTF-8", "-q", "--", path, out],
            check=True,
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with open(out, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    finally:
        try:
            os.remove(out)
        except OSError:
            pass

    blocks = []
    # pdftotext marks page breaks with a form feed, which is the only page
    # information we get - keep it so the player can say which page you are on.
    for page_no, page in enumerate(raw.split("\f"), start=1):
        for para in re.split(r"\n\s*\n", page):
            text = normalize(para)
            if text:
                blocks.append({"kind": "paragraph", "text": text, "page": page_no})
    return "", blocks


# --------------------------------------------------------------------------- #
# chunking
# --------------------------------------------------------------------------- #
_SENT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text):
    """Split into sentences, then hard-split anything still oversized.

    A single sentence longer than MAX is rare but real (a pasted log line, a
    wall of prose with no full stops). Left alone it would make one slow chunk
    and stall playback, so it gets broken on the nearest space.
    """
    out = []
    for s in _SENT.split(text):
        s = s.strip()
        if not s:
            continue
        while len(s) > MAX:
            cut = s.rfind(" ", 0, MAX)
            if cut < MAX // 2:
                cut = MAX
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            out.append(s)
    return out


def chunk_blocks(blocks):
    """Blocks -> chunks ready to synthesize.

    Rules that matter:
      * Headings and skip-notices always stand alone, so there is a real pause
        around them and the player can style them.
      * Prose merges across adjacent blocks up to MAX, because one request per
        list item on a forty-item list would be forty round trips.
      * The first chunk stays under FIRST_MAX. It is the only one anybody waits
        for.
    """
    chunks = []
    buf = []
    buf_len = 0
    buf_block = 0

    def limit():
        return FIRST_MAX if not chunks else MAX

    def flush():
        nonlocal buf, buf_len
        if buf:
            chunks.append({
                "i": len(chunks),
                "kind": "paragraph",
                "block": buf_block,
                "text": " ".join(buf),
            })
            buf = []
            buf_len = 0

    for bi, b in enumerate(blocks):
        kind = b.get("kind", "paragraph")
        text = (b.get("text") or "").strip()
        if not text:
            continue

        if kind in ("heading",) or kind in NOTICE_KINDS:
            flush()
            chunks.append({
                "i": len(chunks),
                "kind": kind,
                "block": bi,
                "text": text[:HARD_MAX],
                "level": b.get("level"),
                "page": b.get("page"),
            })
            continue

        for sent in _sentences(text):
            if buf and buf_len + len(sent) + 1 > limit():
                flush()
            if not buf:
                buf_block = bi
            buf.append(sent)
            buf_len += len(sent) + 1
            # A single sentence can already exceed FIRST_MAX; ship it rather
            # than growing the first chunk past the point of being fast.
            if buf_len >= limit():
                flush()

    flush()
    return chunks


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
_BOM = "\ufeff"

SUPPORTED = (".md", ".markdown", ".mdown", ".txt", ".text", ".pdf")


def load_document(path, filename=None):
    """Read a file from disk and return everything the reader needs.

    The id is a hash of the extracted text, not of the filename or the bytes, so
    reopening the same document - even renamed, even re-exported - lands on the
    same id and therefore the same saved position and the same cached audio.
    """
    filename = filename or os.path.basename(path)
    ext = os.path.splitext(filename)[1].lower()

    if ext == ".pdf":
        title, blocks = _from_pdf(path)
    else:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        # Stock Windows editors write a byte order mark; left in place it would
        # be spoken as a stray character at the top of the document.
        if raw.startswith(_BOM):
            raw = raw[1:]
        if ext in (".txt", ".text"):
            title, blocks = _from_text(raw)
        else:
            title, blocks = _from_markdown(raw)

    chunks = chunk_blocks(blocks)
    body = "\n".join(c["text"] for c in chunks)
    doc_id = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    return {
        "id": doc_id,
        "title": title or os.path.splitext(filename)[0],
        "filename": filename,
        "chars": len(body),
        "chunks": chunks,
    }
