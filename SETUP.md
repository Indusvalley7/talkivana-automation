# Talkivana Setup

Production must remain disabled until the dry run succeeds.

## 1. Create the repository

Use the public `Indusvalley7/talkivana-automation` repository with `.github`, `config`,
`guardrails`, and `src` at its root. Keep GitHub Issues and Actions enabled. The two approved
Chatterbox reference recordings are intentionally public in this repository; never commit API
keys, Google OAuth files, refresh tokens, or any unrelated personal recording.

GitHub supplies a short-lived `GITHUB_TOKEN` to every workflow automatically. A personal access
token is not required for this system.

## Credentials and settings checklist

| Item | Secret? | Where it is used |
| --- | --- | --- |
| `GEMINI_API_KEY` | Yes | Content generation and Standard German QA |
| Google Desktop OAuth client JSON | Yes | Used once by the local setup helper to create the three YouTube secrets below |
| `YOUTUBE_CLIENT_ID` | Yes | Private upload, scheduling, and analytics |
| `YOUTUBE_CLIENT_SECRET` | Yes | Private upload, scheduling, and analytics |
| `YOUTUBE_REFRESH_TOKEN` | Yes | Long-running YouTube authorization without daily sign-in |
| German YouTube playlist ID | No | Routes uploads into the German playlist |
| GitHub email notification setting | No | Sends approval and failure notices from GitHub |

Do not paste secret values into an Issue, commit, or chat. Enter them directly in GitHub Actions
secrets, or use the local helper below. Chatterbox uses its public open-source model and the
approved repository voice references, so it requires no Chatterbox or Hugging Face API key.

## 2. Create the German playlist

1. Sign into YouTube Studio with the Google account that owns Talkivana.
2. Open **Content → Playlists → New playlist**.
3. Name it `Learn German with Talkivana` and choose the desired visibility.
4. Open the playlist and copy the characters after `list=` in its URL. That is the playlist ID.
5. Put only that non-secret ID into
   `config/channel.json → playlists[0].youtube_playlist_id`.

## 3. Add the Gemini key

The key-name dialog shown in AI Studio is the correct screen. `Talkivana_automation` is a valid
name. Selecting **Default Gemini Project** works, but a dedicated project makes quota and future
billing easier to audit:

1. Sign into Google AI Studio with the Google account that owns Talkivana.
2. Optional but recommended: in Google Cloud Console, create a project named
   `Talkivana Automation`. In AI Studio open **Dashboard → Projects → Import projects** and
   import it.
3. Open **Dashboard → API Keys → Create API key**.
4. Name the key `Talkivana_automation`.
5. Select the dedicated project, or keep **Default Gemini Project** if using the simpler setup.
6. Click **Create key** and copy it once. Do not paste it into an Issue, commit, or chat.
7. In GitHub open
   **Indusvalley7/talkivana-automation → Settings → Secrets and variables → Actions**.
8. Choose **New repository secret**, name it exactly `GEMINI_API_KEY`, paste the value, and save.

Do not create a general YouTube API key. Talkivana's uploads and private analytics require OAuth,
which is configured separately below. If GitHub CLI is available, the Gemini key can instead be
entered through its hidden prompt:

```bash
gh secret set GEMINI_API_KEY --repo Indusvalley7/talkivana-automation
```

Free-tier availability and rate limits can change. The workflow fails closed when quota is
exhausted.

## 4. Configure Google OAuth

Use the same `Talkivana Automation` Cloud project and the Google account that owns the Talkivana
channel.

### Enable the two APIs

1. Open Google Cloud Console and select `Talkivana Automation` in the project selector.
2. Open **APIs & Services → Library**.
3. Search for **YouTube Data API v3**, open it, and click **Enable**.
4. Return to the Library, search for **YouTube Analytics API**, open it, and click **Enable**.
5. The YouTube Reporting API and a separate YouTube API key are not required.

### Configure Google Auth Platform

1. Open **Google Auth Platform → Overview** and choose **Get started** if prompted.
2. App name: `Talkivana Automation`.
3. User-support email: the Talkivana Google account.
4. Audience: choose **External** unless this is a managed Google Workspace organization and only
   its members will use the app.
5. Developer contact email: the Talkivana Google account.
6. Open **Data Access → Add or remove scopes** and add exactly:
   - `https://www.googleapis.com/auth/youtube`
   - `https://www.googleapis.com/auth/yt-analytics.readonly`
7. While initially testing, add the Talkivana Google account under **Audience → Test users**.
8. Before generating the long-lived refresh token, change the publishing status from **Testing**
   to **In production**. External apps left in Testing receive refresh tokens that expire after
   seven days. A personal-use app with fewer than 100 users can remain unverified, although Google
   may display an unverified-app warning during your own authorization.

### Create the desktop OAuth client

1. Open **Google Auth Platform → Clients → Create client**.
2. Application type: **Desktop app**.
3. Name: `Talkivana GitHub Automation`.
4. Click **Create**, then download the client JSON.
5. Keep the JSON outside this public repository, for example in Downloads. Never commit it.

### Generate the refresh token and save all three secrets

The repository helper requests offline access to YouTube management and read-only analytics. It
then writes `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` directly to
GitHub without printing their values. GitHub CLI must be installed and signed in once.

Check the GitHub CLI first:

```bash
gh --version
gh auth status
```

If either command is unavailable or reports that you are signed out, install GitHub CLI from
<https://cli.github.com/> and run `gh auth login`. Choose **GitHub.com**, **HTTPS**, and browser
authentication.

Run from the repository folder:

```bash
python -m pip install -r requirements.txt
python scripts/setup_youtube_secrets.py \
  --client-secrets /absolute/path/client_secret.json \
  --repo Indusvalley7/talkivana-automation
```

When the browser opens:

1. Select the Google account that owns Talkivana.
2. If that account owns multiple YouTube channels, make sure Talkivana is the channel being
   authorized.
3. Review the two requested permissions and approve them.
4. If Google shows an unverified-app warning, continue only because this is your own private
   automation project.
5. Return to the terminal and wait for the confirmation that all three GitHub secrets were saved.

Do not manually send the downloaded JSON or refresh token through chat or email.

## 5. Enable notifications

Watch the repository with **All Activity** and enable email notifications for assigned Issues.
Email replies become Issue comments only when GitHub email reply handling is available. The
GitHub Issue remains the authoritative approval surface. No email password or SMTP credential is
required because these messages are GitHub notifications, not mail sent by Talkivana itself.

## 6. Test while locked

Run the Tests workflow and render the offline demo locally. Manually run content generation and
confirm that it reports the production lock. A production preflight is expected to fail while the
lock is active or the playlist ID and secrets are absent.

## 7. Dry run

1. Set a real German playlist ID and, if known, the timing-agent launch date.
2. Set `system.enabled=true` for the controlled manual dry run. Leave the repository variable
   `TALKIVANA_DAILY_AUTOMATION` unset so scheduled jobs remain skipped.
3. Run System preflight and require a clean pass.
4. Manually run Talkivana — content generation.
5. Request a content revision and verify the replacement.
6. Keep `system.dry_run_asset_id=long-1`, approve content, and review the single downloadable
   controlled sample. `APPROVE VIDEO` records sample acceptance without uploading or scheduling.
7. Clear `system.dry_run_asset_id`, then approve a fresh content pack and review all four private
   full videos.
8. Retry one video pack and verify old private previews are replaced.
9. Approve the final videos.
10. Confirm the two Shorts are scheduled one day before the linked long lessons.
11. Confirm the Audience Timing Agent Issue exists.

Only after this sequence should the repository variable `TALKIVANA_DAILY_AUTOMATION` be set to
`true`, enabling daily schedules.
