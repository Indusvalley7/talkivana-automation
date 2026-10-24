import hashlib
import unittest

from language_video_automation.github_api import GitHubClient


class GitHubClientTests(unittest.TestCase):
    def test_issue_listing_reads_every_page(self):
        client = GitHubClient.__new__(GitHubClient)
        paths = []

        def request(_method, path, _payload=None, **_kwargs):
            paths.append(path)
            page = 2 if "page=2" in path else 1
            count = 1 if page == 2 else 100
            start = 101 if page == 2 else 1
            return [
                {
                    "number": start + index,
                    "title": "Pack",
                    "body": "",
                    "state": "closed",
                    "labels": [],
                    "html_url": "https://example.test",
                }
                for index in range(count)
            ]

        client._request = request
        issues = client.list_issues(labels=["talkivana"])
        self.assertEqual(len(issues), 101)
        self.assertEqual(len(paths), 2)

    def test_file_upsert_uses_blob_hash_for_large_file_safe_noop(self):
        client = GitHubClient.__new__(GitHubClient)
        client.repository = "owner/repo"
        text = "tracker data\n"
        content = text.encode("utf-8")
        sha = hashlib.sha1(
            f"blob {len(content)}\0".encode("ascii") + content,
            usedforsecurity=False,
        ).hexdigest()
        calls = []

        def request(method, path, payload=None, **_kwargs):
            calls.append((method, path, payload))
            return {"sha": sha, "encoding": "none"}

        client._request = request
        changed = client.upsert_file(path="tracker/video_tracker.csv", text=text, message="Update")
        self.assertFalse(changed)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
