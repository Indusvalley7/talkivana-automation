# Operations and Recovery

## State machine

```text
daily generation
  → content + history validation
      → producing (voice / visuals / assembly)
          → four private uploads + thumbnails
              → automatic technical QA
                  → scheduled
                      → published
                      → analytics feedback
  → any failure: stop closed + send one diagnostic email
```

Normal daily operation has no human approval wait. Manual commands remain available for recovery.

## Live workflow categories

- Parent-agent safety preflight
- Content generation
- Standard German QA
- Topic/title history recheck
- Voice preparation
- Visual scene preparation
- Assembly and technical QA
- Private upload and manifest verification
- Automatic finalization
- Scheduling and publishing
- Audience timing agent
- Rejected-preview cleanup

Voice, visual, and assembly work use a four-asset matrix, so independent assets can run in
parallel. Assembly waits until the full voice and visual stages succeed. Actions logs identify the
asset and operation that failed, and a final cleanup job deletes full intermediate artifacts. The
GitHub Issue is the durable audit record. Success is silent by email; only a failed monitored
workflow sends the failed job, reason, and run link via Gmail SMTP.

## Timing stages

- Days 1–30: rotate formats through four separated slots.
- Days 31–60: 70% evidence-weighted scheduling and 30% controlled experiments.
- Day 61 onward: 85% evidence-weighted scheduling and 15% experiments.

Shorts and long videos are scored separately using comparable 24-hour and 7-day windows.
Insufficient samples remain provisional. The agent advises and assigns slots, but cannot bypass
the content, media, or scheduling safeguards.

## Failure and recovery

- Missing credentials: label `pack-setup-blocked`; nothing uploads.
- Invalid or repeated content: workflow fails before media work or publication.
- Rendering failure: label `pack-failed`; no public video exists.
- Partial upload: each returned YouTube ID is immediately persisted in the Issue manifest.
- Final scheduling failure: unscheduled files remain private and a failure email is sent.
- Retry: the owner uses a targeted retry command; the pack is fully rebuilt to preserve sync.
- Emergency stop: set `system.enabled` to `false`. Manually cancel already scheduled videos in
  YouTube Studio if necessary.
- Schedule stop: delete or set the applicable repository variable
  (`TALKIVANA_CONTENT_AUTOMATION`, `TALKIVANA_ANALYTICS_AUTOMATION`,
  `TALKIVANA_TRACKER_AUTOMATION`, or `TALKIVANA_CLEANUP_AUTOMATION`) to anything other than
  `true`. Set `TALKIVANA_UNATTENDED_AUTOMATION` to anything other than `true` to pause automatic
  production while leaving manual recovery available for an existing pack.

Rejected private previews remain recoverable for 14 days, then the authorized cleanup workflow
deletes them.
