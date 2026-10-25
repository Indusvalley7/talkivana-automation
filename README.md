# Talkivana Automated Language-Video System

Talkivana produces two German vocabulary Shorts and two five-minute Standard German
conversation videos per day. GitHub Actions provides the live workflow, logs, approval gates,
private previews, publishing, cleanup, and audience-timing experiment.

Production is disabled by default. No content is made public without both approvals.

## Daily operating model

1. Content generation creates one daily pack: two Shorts and two linked conversations.
2. Standard German QA validates translations, spelling, simplified pronunciation, and links.
3. A GitHub Issue acts as the temporary daily review sheet and requests `APPROVE CONTENT`.
4. After approval, four voice jobs run in parallel, followed by parallel visual, thumbnail, and assembly/QA jobs.
5. Four exact completed files and their content-specific custom thumbnails are uploaded privately to YouTube.
6. The Issue contains the full private links; the Actions run contains 30-second clips.
7. Only `APPROVE VIDEO` schedules the exact reviewed files.
8. Shorts publish one day before their linked conversations.
9. The timing agent collects equal-window performance samples and updates the four-slot plan.

## Approval commands

```text
APPROVE CONTENT
REVISE CONTENT
- <asset and line number>: <correction>
APPROVE VIDEO
RETRY VOICE: <correction>
RETRY VISUALS: <correction>
RETRY VIDEO: <correction>
REJECT: <reason>
```

Commands must be the first non-empty line and come from `Indusvalley7`. Casual language,
emoji, silence, and the old one-stage `APPROVE` command do nothing.

The daily GitHub Issue is the single review surface. It lists every Short and every numbered
conversation line, so corrections can be dictated or typed there without returning to Codex.
Multi-line correction bullets are accepted up to 4,000 characters. The automation generates a
new revision and updates the review sheet; visible Issue text is never silently treated as approval.

## Safety properties

- Manual production commands require `config/channel.json` to keep `system.enabled=true`.
- Scheduled content, analytics, tracker, and cleanup jobs use separate repository variables:
  `TALKIVANA_CONTENT_AUTOMATION`, `TALKIVANA_ANALYTICS_AUTOMATION`,
  `TALKIVANA_TRACKER_AUTOMATION`, and `TALKIVANA_CLEANUP_AUTOMATION`. Each must explicitly equal
  `true`; all remain unset throughout the controlled dry run.
- While `system.dry_run_asset_id` is set, content approval renders only that asset as a temporary
  GitHub artifact. It does not upload to YouTube, and sample approval cannot schedule anything.
- Content and final-video approval are independent.
- Uploads remain private until final approval.
- Seven unfinished daily packs across either approval gate are allowed; the eighth pauses generation.
- Four daily publishing slots are distinct and separated by at least three hours.
- Rejected private previews are deleted after 14 days.
- Intermediate narration, scenes, and full MP4 transfers are deleted from Actions as soon as the
  run finishes; only 30-second convenience clips are retained for 3 days.
- Every pack embeds a content hash, and every upload has an idempotent manifest.
- Standard German is required and dialects are forbidden.
- The general-audience channel is family-safe and is not marked made-for-kids.
- Subtitles and closed captions are disabled.
- Failures stop closed and are visible in the controlling Issue and Actions logs.
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
