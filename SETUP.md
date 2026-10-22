# Talkivana Setup

Production must remain disabled until the dry run succeeds.

## 1. Create the repository

Create a private repository under `Indusvalley7` and push this folder so `.github`, `config`,
`guardrails`, and `src` are at its root. Enable GitHub Issues and Actions.

## 2. Create the German playlist

Create the Talkivana German playlist in YouTube Studio. Copy its playlist ID into
`config/channel.json → playlists[0].youtube_playlist_id`.

## 3. Add the Gemini key

Create a Google AI Studio key, then use the hidden GitHub CLI prompt:

```bash
gh secret set GEMINI_API_KEY --repo Indusvalley7/REPOSITORY_NAME
```

Free-tier availability and rate limits can change. The workflow fails closed when quota is
exhausted.

## 4. Configure Google OAuth

In Google Cloud Console:

1. Enable YouTube Data API v3 and YouTube Analytics API.
2. Configure the OAuth consent screen.
3. Create a Desktop-app OAuth client.
4. Download its JSON outside this repository.
5. Run:

```bash
python -m pip install -r requirements.txt
python scripts/setup_youtube_secrets.py \
  --client-secrets /absolute/path/client_secret.json \
  --repo Indusvalley7/REPOSITORY_NAME
```

The helper requests YouTube management and read-only analytics access and writes credentials
directly into GitHub secrets without printing them.

## 5. Enable notifications

Watch the repository with **All Activity** and enable email notifications for assigned Issues.
Email replies become Issue comments only when GitHub email reply handling is available. The
GitHub Issue remains the authoritative approval surface.

## 6. Test while locked

Run the Tests workflow and render the offline demo locally. Manually run content generation and
confirm that it reports the production lock. A production preflight is expected to fail while the
lock is active or the playlist ID and secrets are absent.

## 7. Dry run

1. Set a real German playlist ID and, if known, the timing-agent launch date.
2. Set `system.enabled=true`.
3. Run System preflight and require a clean pass.
4. Manually run Talkivana — content generation.
5. Request a content revision and verify the replacement.
6. Approve content and review all four private full videos.
7. Retry one video pack and verify old private previews are replaced.
8. Approve the final videos.
9. Confirm the two Shorts are scheduled one day before the linked long lessons.
10. Confirm the Audience Timing Agent Issue exists.

Only after this sequence should the daily schedules remain enabled.
