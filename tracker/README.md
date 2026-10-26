# Talkivana video tracker

The automation maintains three synchronized tracker views in this folder:

- `video_tracker.csv` is the analysis-ready dataset.
- `video_tracker.md` is the readable GitHub view of the newest 100 records. This keeps the page
  quick to open while the CSV retains the complete multi-year history.
- `publishing_schedule.xlsx` is the Excel slot matrix. Its first sheet places a tick under each
  asset's assigned time. Its second sheet shows occupied and available seed slots for the next
  14 days.

The tracker joins each approved content asset to its GitHub review status, YouTube video ID,
scheduled date in `Asia/Kolkata`, public/private state, and the timing agent's 24-hour and
7-day views, viewing percentage, and subscriber measurements when those windows become available.

The content-description field stores the concise asset-specific lesson summary rather than
repeating the channel's long standard description template in every row.

`successfully_published` becomes `Yes` only after YouTube reports that the video is public.
Being scheduled is not treated as successful publication.

The trackers refresh immediately after final scheduling and approximately hourly while the
independent `TALKIVANA_TRACKER_AUTOMATION` repository switch is enabled. This allows the workbook
to notice when a scheduled video becomes public, including catch-up releases. Tracker refreshes do
not generate, approve, schedule, or publish videos.

The scheduler checks the authoritative scheduled-video manifests before it assigns any normal or
catch-up time. The Excel file is regenerated from that same registry. Manual spreadsheet edits do
not change YouTube; rescheduling must use the approved GitHub workflow so the manifest, tracker,
workbook, and channel cannot drift apart.
