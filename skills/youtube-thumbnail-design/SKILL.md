---
name: youtube-thumbnail-design
version: talkivana-1
source: https://github.com/inference-sh/skills/tree/main/guides/design/youtube-thumbnail-design
---

# Talkivana YouTube thumbnail design

This repository-owned profile applies the public `youtube-thumbnail-design` principles without
calling a paid image-generation service. GitHub Actions renders the artwork deterministically with
Pillow, so every approved video can receive a thumbnail at no additional API-generation cost.

## Required output

- Long videos: 1280 × 720 JPEG (16:9).
- Shorts: 1080 × 1920 JPEG (9:16).
- Keep every file below 2 MB.
- Use no more than six words in the main headline.
- Use a bold sans-serif face, strong foreground/background contrast, and a visible text stroke.
- Keep essential text and focal artwork away from the extreme edges and bottom-right duration area.
- The subject and headline must truthfully match the approved lesson content.
- Use one dominant focal symbol, one headline, and restrained brand identifiers.
- Verify that the message remains recognizable when reduced to a small mobile preview.

## Talkivana variation rules

- Derive the wording from the current lesson title, topic, scenario, and vocabulary; never reuse a
  fixed sample headline.
- Rotate high-contrast palettes deterministically from the pack and asset identity.
- Give Shorts a vocabulary-card composition and long lessons a situation/icon composition.
- Keep the TALKIVANA wordmark and A1 GERMAN marker consistent while allowing the background,
  focal word, icon, and headline to change.
- Do not copy wording from reference artwork and do not make unsupported speed or result claims.

The renderer must fail closed if this profile is missing or if its output violates the dimensions,
format, or file-size constraints above.
