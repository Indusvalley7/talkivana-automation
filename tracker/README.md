# Talkivana video tracker

The automation maintains two tracker views in this folder:

- `video_tracker.csv` is the analysis-ready dataset.
- `video_tracker.md` is the readable GitHub view of the newest 100 records. This keeps the page
  quick to open while the CSV retains the complete multi-year history.

The tracker joins each approved content asset to its GitHub review status, YouTube video ID,
scheduled date in `Asia/Kolkata`, public/private state, and the timing agent's 24-hour and
7-day views, viewing percentage, and subscriber measurements when those windows become available.

The content-description field stores the concise asset-specific lesson summary rather than
repeating the channel's long standard description template in every row.

`successfully_published` becomes `Yes` only after YouTube reports that the video is public.
Being scheduled is not treated as successful publication.

The tracker refreshes daily at approximately 9:11 AM `Asia/Kolkata` when the independent
`TALKIVANA_TRACKER_AUTOMATION` repository switch is enabled. It does not generate, approve,
schedule, or publish videos.
