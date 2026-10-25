# Thumbnail guardrails

Every uploaded Talkivana asset receives a content-specific custom thumbnail generated from the
approved content pack. The checked-in `skills/youtube-thumbnail-design/SKILL.md` profile is loaded
on every render and is the controlling design specification.

- Thumbnail generation is deterministic, local to GitHub Actions, and must not call a paid image
  service or introduce a second content-generation approval surface.
- Headlines must be truthful, concise, and different from the supplied reference's example copy.
- The pack ID, asset ID, lesson title, and topic determine the palette and composition so daily
  videos retain a recognizable brand without looking identical.
- A thumbnail failure blocks the private upload. It must never silently fall back to the first
  presentation slide.
- A YouTube upload is recorded before its thumbnail is applied, allowing a safe retry without
  creating a duplicate video.
- Backfills may change only the thumbnail of an existing video. They must not alter title,
  description, visibility, publishing time, playlist membership, or audience settings.
