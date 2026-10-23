import unittest

from language_video_automation.analytics import YouTubeAnalyticsClient
from language_video_automation.youtube import YouTubeError, YouTubeUploader


class _Request:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class _Resource:
    def __init__(self, response):
        self.response = response

    def list(self, **_kwargs):
        return _Request(self.response)

    def query(self, **_kwargs):
        return _Request(self.response)


class _YouTubeService:
    def __init__(self, *, channel_title="Talkivana", playlist_channel="channel-1"):
        self.channel_response = {
            "items": [{"id": "channel-1", "snippet": {"title": channel_title}}]
        }
        self.playlist_response = {
            "items": [{
                "id": "playlist-1",
                "snippet": {"title": "Learn German with Talkivana", "channelId": playlist_channel},
            }]
        }

    def channels(self):
        return _Resource(self.channel_response)

    def playlists(self):
        return _Resource(self.playlist_response)


class _AnalyticsService:
    def reports(self):
        return _Resource({"rows": []})


class YouTubeAccessTests(unittest.TestCase):
    def test_preflight_confirms_the_expected_channel_and_playlist(self):
        uploader = YouTubeUploader.__new__(YouTubeUploader)
        uploader.service = _YouTubeService()
        identity = uploader.validate_access(
            expected_channel_name="Talkivana",
            playlist_id="playlist-1",
        )
        self.assertEqual(identity["channel_id"], "channel-1")
        self.assertEqual(identity["playlist_title"], "Learn German with Talkivana")

    def test_preflight_rejects_a_different_authorized_channel(self):
        uploader = YouTubeUploader.__new__(YouTubeUploader)
        uploader.service = _YouTubeService(channel_title="Another Channel")
        with self.assertRaises(YouTubeError):
            uploader.validate_access(
                expected_channel_name="Talkivana",
                playlist_id="playlist-1",
            )

    def test_analytics_preflight_accepts_an_empty_report(self):
        analytics = YouTubeAnalyticsClient.__new__(YouTubeAnalyticsClient)
        analytics.service = _AnalyticsService()
        analytics.validate_access()


if __name__ == "__main__":
    unittest.main()
