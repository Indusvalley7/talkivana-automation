# Operations and Recovery

## State machine

```text
daily generation
  → awaiting content approval
      → revise/reject
      → producing
          → four private uploads
          → awaiting final-video approval
              → retry/reject
              → approved and scheduled
                  → published
                  → analytics feedback
```

Human waiting never consumes a runner.

## Live workflow categories

- Parent-agent safety preflight
- Content generation
- Standard German QA
- Content approval
- Voice preparation
- Visual scene preparation
- Assembly and technical QA
- Private full preview
- Final approval
- Scheduling and publishing
- Audience timing agent
- Rejected-preview cleanup

Voice, visual, and assembly work use a four-asset matrix, so independent assets can run in
parallel. Assembly waits until the full voice and visual stages succeed. Actions logs identify the
asset and operation that failed, and a final cleanup job deletes full intermediate artifacts. The
GitHub Issue is the durable audit record.

## Timing stages

- Days 1–30: rotate formats through four separated slots.
- Days 31–60: 70% evidence-weighted scheduling and 30% controlled experiments.
- Day 61 onward: 85% evidence-weighted scheduling and 15% experiments.

Shorts and long videos are scored separately using comparable 24-hour and 7-day windows.
Insufficient samples remain provisional. The agent advises and assigns slots, but cannot approve
content or videos.

## Failure and recovery

- Missing credentials: label `pack-setup-blocked`; nothing uploads.
- Invalid content: workflow fails before creating an approval request.
- Rendering failure: label `pack-failed`; no public video exists.
- Partial upload: each returned YouTube ID is immediately persisted in the Issue manifest.
- Final scheduling failure: unscheduled files remain private.
- Retry: the owner uses a targeted retry command; the pack is fully rebuilt to preserve sync.
- Emergency stop: set `system.enabled` to `false`. Manually cancel already scheduled videos in
  YouTube Studio if necessary.
- Schedule stop: delete or set the repository variable `TALKIVANA_DAILY_AUTOMATION` to anything
  other than `true`. Manual approval handling remains available for an existing pack.

Rejected private previews remain recoverable for 14 days, then the authorized cleanup workflow
deletes them.
