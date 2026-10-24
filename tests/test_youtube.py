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


class _MetadataVideosResource:
    def __init__(self):
        self.update_call = None

    def list(self, **_kwargs):
        return _Request({
            "items": [{
                "snippet": {
                    "title": "Booking a Doctor's Appointment",
                    "description": "Old description",
                    "categoryId": "27",
                    "tags": ["German", "Talkivana"],
                    "defaultLanguage": "en",
                }
            }]
        })

    def update(self, **kwargs):
        self.update_call = kwargs
        return _Request({})


class _MetadataService:
    def __init__(self):
        self.resource = _MetadataVideosResource()

    def videos(self):
        return self.resource


class _StatusVideosResource:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        items = [
            {
                "id": video_id,
                "status": {"privacyStatus": "public", "uploadStatus": "processed"},
            }
            for video_id in kwargs["id"].split(",")
        ]
        return _Request({"items": items})


class _StatusService:
    def __init__(self):
        self.resource = _StatusVideosResource()

    def videos(self):
        return self.resource


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

    def test_description_update_preserves_other_snippet_metadata(self):
        uploader = YouTubeUploader.__new__(YouTubeUploader)
        uploader.service = _MetadataService()
        uploader.update_description(video_id="video-1", description="New description")
        body = uploader.service.resource.update_call["body"]
        self.assertEqual(body["id"], "video-1")
        self.assertEqual(body["snippet"]["description"], "New description")
        self.assertEqual(body["snippet"]["title"], "Booking a Doctor's Appointment")
        self.assertEqual(body["snippet"]["tags"], ["German", "Talkivana"])
        self.assertNotIn("status", body)

    def test_publication_status_lookup_batches_more_than_fifty_videos(self):
        uploader = YouTubeUploader.__new__(YouTubeUploader)
        uploader.service = _StatusService()
        statuses = uploader.publication_statuses([f"video-{index}" for index in range(51)])
        self.assertEqual(len(statuses), 51)
        self.assertEqual(len(uploader.service.resource.calls), 2)
        self.assertEqual(statuses["video-50"]["privacy_status"], "public")


if __name__ == "__main__":
    unittest.main()
