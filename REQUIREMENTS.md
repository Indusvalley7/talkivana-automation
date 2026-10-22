# One-Time Requirements

The code and offline demo require no credentials. Live generation and publishing require:

- GitHub account `Indusvalley7` and a private repository.
- Google AI Studio API key for Gemini structured text and TTS.
- Talkivana YouTube channel.
- Google Cloud project with YouTube Data API v3 and YouTube Analytics API enabled.
- OAuth Desktop application owned by the same Google account as the channel.

## GitHub secrets

| Secret | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Generates and reviews content, then creates narration. |
| `YOUTUBE_CLIENT_ID` | OAuth client identifier. |
| `YOUTUBE_CLIENT_SECRET` | OAuth client secret. |
| `YOUTUBE_REFRESH_TOKEN` | Private upload, scheduling, cleanup, playlists, and analytics. |

The OAuth grant requests both YouTube management and read-only YouTube Analytics scopes.

## Information still supplied during setup

- GitHub repository name under `Indusvalley7`.
- YouTube German playlist ID.
- Gemini key.
- Google OAuth client-secret JSON.
- The real channel launch date once known.

No production code needs the owner's passwords.

