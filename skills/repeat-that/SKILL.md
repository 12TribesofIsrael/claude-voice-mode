---
name: repeat-that
description: Speak the previous answer again in voice mode. Use when Thomas says "repeat that", "say that again", "repeat", "one more time", "read that back", or invokes /repeat-that. Re-emits the last spoken reply verbatim so the voice hook reads it out loud again — no regenerating the answer.
---

# Repeat that

## What this is for

Voice mode reads Claude's replies out loud through the Stop hook. That hook
always speaks Claude's **most recent** assistant message. This skill exploits
that: to hear the last answer again, Claude just prints the same words again,
and the hook speaks them. Nothing is re-derived, re-searched, or re-generated —
it is a literal re-play of what was already said.

## What to do when this skill fires

1. **Find the answer to repeat.** By default it is your **last spoken answer** —
   the most recent assistant turn that contained prose meant to be heard aloud.
   Skip over turns that were only tool calls or had no spoken prose, and skip
   this invocation itself. That earlier prose is what gets repeated.

2. **Print it back verbatim.** Output the exact same words as that answer. Do
   **not** summarize it, shorten it, rephrase it, or "clean it up." The whole
   point is that Thomas hears the identical answer again.

3. **No meta preamble.** Do not add lead-ins like "Sure, here it is again" or
   "Repeating what I said." Anything you print gets spoken, so a preamble just
   becomes noise before the real content. Output only the repeated words.

4. **Stay speakable.** Keep it as plain prose — full sentences, no tables, no
   code blocks, no bullet lists, no headers, no links, no file paths. If the
   original answer happened to contain any of those, render the same meaning as
   clean spoken sentences instead, because the voice hook strips that markup
   anyway.

## Variations Thomas might ask for

- **"Repeat the one before that" / "the last two"** — go further back: repeat the
  answer before the most recent one, or concatenate the last two spoken answers
  in the order he heard them.
- **"Repeat just the last part" / "the last sentence"** — repeat only the tail of
  the previous answer, the final sentence or two.
- **"Slower" / "say it again slower"** — you cannot change the voice's rate from
  here (that lives in the voice control panel), so just repeat the words again
  normally and, if helpful, tell him the speed is set in the Voice Panel.

## If there is nothing to repeat

If there is no prior spoken answer in this conversation — for example this is the
first turn — say briefly that there is nothing to repeat yet, in one short
spoken sentence.
