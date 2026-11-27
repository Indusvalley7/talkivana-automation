# Talkivana Automated Language-Video System

Talkivana produces two German vocabulary Shorts and two five-minute Standard German
conversation videos per day. GitHub Actions provides the live workflow, deterministic quality
gates, publishing, cleanup, failure-only email alerts, and audience-timing experiment.

Production is disabled by default. In unattended mode, valid packs proceed automatically; any
failed content, media, upload, thumbnail, or scheduling gate stops closed and sends one email.

## Daily operating model

1. Content generation creates one daily pack: two Shorts and two linked conversations.
2. Standard German QA validates translations, spelling, simplified pronunciation, and links.
3. The candidate is checked against both the Excel history and all existing pack Issues; materially
   repeated topics or confusingly similar titles fail before media work.
4. Four voice jobs run in parallel, followed by parallel visual, thumbnail, and assembly/QA jobs.
5. Four exact completed files and their content-specific custom thumbnails are uploaded privately.
6. Only after every automated QA and manifest check passes are those exact files scheduled.
7. A GitHub Issue remains the audit record, but normal success requires no owner comment.
8. A one-day preparation buffer places Shorts before their linked conversations. Consecutive packs
   overlap into the stable 07:30 / 12:30 / 18:00 / 22:30 IST conveyor.
9. The timing agent collects equal-window performance samples but cannot rearrange the conveyor
   without an owner-approved configuration change.

If production completes after a same-day slot, that asset uses a near-immediate catch-up release
with a five-minute API safety buffer. Multiple missed assets remain at least 30 minutes apart.
Catch-up uploads still appear in the tracker, but their exceptional times do not influence the
stable four-slot timing baseline.

## Manual recovery commands

```text
APPROVE CONTENT
REVISE CONTENT
- <asset and line number>: <correction>
APPROVE VIDEO
RETRY VOICE: <correction>
RETRY VISUALS: <correction>
RETRY VIDEO: <correction>
RESUME VIDEO: rebuild only missing private files
REJECT: <reason>
```

These commands remain available for exceptional repairs and historical packs. They must be the
first non-empty line and come from `Indusvalley7`. Normal daily operation does not require them.

The daily GitHub Issue is an audit and recovery surface. It lists every Short and every numbered
conversation line. A manual revision creates a new validated proposal; visible Issue text is never
silently treated as a repair command.

## Safety properties

- Manual production commands require `config/channel.json` to keep `system.enabled=true`.
- Scheduled content, analytics, tracker, and cleanup jobs use separate repository variables:
  `TALKIVANA_CONTENT_AUTOMATION`, `TALKIVANA_ANALYTICS_AUTOMATION`,
  `TALKIVANA_TRACKER_AUTOMATION`, and `TALKIVANA_CLEANUP_AUTOMATION`. Each must explicitly equal
  `true`; all remain unset throughout the controlled dry run.
- `TALKIVANA_UNATTENDED_AUTOMATION=true` is a separate activation switch. Leave it unset until
  the three failure-email secrets have been configured and tested.
- While `system.dry_run_asset_id` is set, content approval renders only that asset as a temporary
  GitHub artifact. It does not upload to YouTube, and sample approval cannot schedule anything.
- Topic and title uniqueness are checked both during generation and again immediately before media
  production against the checked-in tracker plus current Issue history.
- Uploads remain private until all automated QA stages pass; a failed stage cannot schedule them.
- Seven unfinished daily packs across all open production states are allowed; the eighth pauses generation.
- Four daily publishing slots are distinct and separated by at least three hours.
- Future packs use fixed roles: Short 1 at 07:30, long 1 at 12:30, Short 2 at 18:00, and long 2
  at 22:30 IST. Existing YouTube schedules are never migrated automatically.
- Daily generation continues at 06:47 IST and keeps a one-day publication buffer so production time
  does not create an empty publishing day once the conveyor is filled.
- Rejected private previews are deleted after 14 days.
- Intermediate narration, scenes, and full MP4 transfers are deleted from Actions as soon as the
  run finishes; only 30-second convenience clips are retained for 3 days.
- Every pack embeds a content hash, and every upload has an idempotent manifest.
- `RESUME VIDEO` preserves completed private uploads and rebuilds only assets missing from a
  failed handoff; it never deletes the successful files first.
- Standard German is required and dialects are forbidden.
- The general-audience channel is family-safe and is not marked made-for-kids.
- Subtitles and closed captions are disabled.
- Failures stop closed, remain visible in Actions/the audit Issue, and trigger one concise SMTP
  email containing the failed job, extracted reason, and run link. Successful runs send no email.
- Simplified pronunciation remains visible on the lesson scene but is never spoken.
- The final whole conversation uses one stable approved Chatterbox reference voice per character.
- The checked-in YouTube-thumbnail skill creates distinct topic wording, focal artwork, and rotating
  palettes for every asset. It uses Pillow in GitHub Actions and no paid image-generation API.
- Thumbnail updates use YouTube's thumbnail-only endpoint and never alter scheduling or metadata.

## Local verification

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m language_video_automation render-demo --output build/demo-v3
```

On macOS, the legacy demo command uses installed English and German system voices for one-off
renderer checks. Daily automation does not use those voices. Continue with [SETUP.md](SETUP.md).

Production narration uses Chatterbox Multilingual V3 pinned to the tested upstream source commit
`65b1843`. To render
one sample without using the Mac, run the **Talkivana — one Chatterbox sample** GitHub workflow and
download its three-day artifact. The workflow never falls back to another voice.
