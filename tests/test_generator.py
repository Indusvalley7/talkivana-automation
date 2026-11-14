import copy
import json
import unittest
from datetime import date

from language_video_automation.config import load_config, project_root
from language_video_automation.generator import ContentPackGenerator
from language_video_automation.models import _german_vocabulary_used


class _FakeGeminiClient:
    def __init__(self, pack):
        self.pack = pack
        self.calls = 0
        self.prompts = []

    def generate_json(self, **kwargs):
        self.calls += 1
        self.prompts.append(kwargs["prompt"])
        if self.calls == 1:
            return copy.deepcopy(self.pack)
        return {
            "approved": True,
            "problems": ["Restored configuration-owned metadata."],
            "corrected_pack": copy.deepcopy(self.pack),
        }


class _RepairingGeminiClient(_FakeGeminiClient):
    def generate_json(self, **kwargs):
        self.calls += 1
        self.prompts.append(kwargs["prompt"])
        if self.calls == 1:
            return copy.deepcopy(self.pack)
        if self.calls == 2:
            invalid = copy.deepcopy(self.pack)
            for turn in invalid["long_videos"][1]["dialogue"]:
                turn["german"] = turn["german"].replace("Kaffee", "Tee")
            return {
                "approved": False,
                "problems": [],
                "corrected_pack": invalid,
            }
        return {
            "approved": True,
            "problems": ["Restored the exact linked vocabulary in natural context."],
            "corrected_pack": copy.deepcopy(self.pack),
        }


class _FullPairRepairGeminiClient(_FakeGeminiClient):
    def __init__(self, invalid_pack, replacement_pack):
        super().__init__(invalid_pack)
        self.replacement_pack = replacement_pack
        self.repair_calls = 0

    def generate_json(self, **kwargs):
        self.calls += 1
        self.prompts.append(kwargs["prompt"])
        operation = kwargs["operation"]
        if operation == "initial content pack":
            return copy.deepcopy(self.pack)
        if operation == "deterministic validation repair":
            self.repair_calls += 1
            corrected = self.pack if self.repair_calls == 1 else self.replacement_pack
        elif operation == "conversation naturalness audit":
            corrected = self.replacement_pack
        else:
            corrected = self.pack
        return {
            "approved": True,
            "problems": [],
            "corrected_pack": copy.deepcopy(corrected),
        }


class _FreshPackFallbackGeminiClient(_FullPairRepairGeminiClient):
    def generate_json(self, **kwargs):
        if kwargs["operation"] == "fresh pack after collision":
            self.calls += 1
            self.prompts.append(kwargs["prompt"])
            return copy.deepcopy(self.replacement_pack)
        if kwargs["operation"] == "deterministic validation repair":
            self.calls += 1
            self.prompts.append(kwargs["prompt"])
            self.repair_calls += 1
            return {
                "approved": True,
                "problems": [],
                "corrected_pack": copy.deepcopy(self.pack),
            }
        return super().generate_json(**kwargs)


class GeneratorTests(unittest.TestCase):
    def test_natural_german_inflections_and_separable_verbs_count_as_linked_vocabulary(self):
        self.assertTrue(_german_vocabulary_used("frisch", "Wir kaufen frische Brötchen."))
        self.assertTrue(_german_vocabulary_used("abfahren", "Der Zug fährt um acht Uhr ab."))
        self.assertFalse(_german_vocabulary_used("abfahren", "Der Zug kommt um acht Uhr an."))

    def test_article_marked_nouns_accept_natural_german_plural_forms(self):
        self.assertTrue(_german_vocabulary_used("der Apfel", "Ich kaufe Äpfel."))
        self.assertTrue(_german_vocabulary_used("der Bahnhof", "Wo sind die Bahnhöfe?"))
        self.assertTrue(_german_vocabulary_used("die Ärztin", "Die Ärztinnen helfen uns."))
        self.assertFalse(_german_vocabulary_used("der Apfel", "Ich kaufe Birnen."))

    def test_unmarked_items_do_not_receive_article_marked_noun_expansion(self):
        self.assertFalse(_german_vocabulary_used("Apfel", "Ich kaufe Äpfel."))

    def test_configuration_owned_metadata_is_normalized_before_approval(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        fixture["source_language"] = "English (international)"
        fixture["target_language"] = "Deutsch"
        fixture["language_variety"] = "Hochdeutsch"
        fixture["level"] = "A1"
        config = load_config()
        client = _FakeGeminiClient(fixture)
        record = ContentPackGenerator(config, client).create(
            playlist=config.active_playlists[0],
            history=[],
            today=date(2026, 10, 23),
        )
        self.assertEqual(record.content["source_language"], "English")
        self.assertEqual(record.content["target_language"], "German")
        self.assertEqual(
            record.content["language_variety"],
            "Standard German used in Germany; no dialects",
        )
        self.assertEqual(record.content["level"], "absolute beginner")
        self.assertEqual(client.calls, 3)

    def test_tutor_skill_profile_is_applied_to_generation_and_review(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        config = load_config()
        client = _FakeGeminiClient(fixture)
        ContentPackGenerator(config, client).create(
            playlist=config.active_playlists[0],
            history=[],
            today=date(2026, 10, 25),
        )

        self.assertEqual(len(client.prompts), 3)
        for prompt in client.prompts[:2]:
            self.assertIn("Talkivana Language Learning Companion Profile", prompt)
            self.assertIn("complete opening-to-resolution arc", prompt)
            self.assertIn("Do not mix `du` and `Sie`", prompt)
        self.assertIn("spaced-repetition recycling", client.prompts[0])
        self.assertIn("No heading may duplicate or closely", client.prompts[0])
        self.assertIn("read the German dialogue from first to last", client.prompts[1])
        self.assertIn("final adversarial Talkivana conversation auditor", client.prompts[2])
        self.assertIn("specific role would naturally say", client.prompts[2])

    def test_existing_uploaded_titles_are_injected_into_generation(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        config = load_config()
        client = _FakeGeminiClient(fixture)
        ContentPackGenerator(config, client).create(
            playlist=config.active_playlists[0],
            history=[],
            reserved_titles=["Buying a Train Ticket at the Station"],
            today=date(2026, 10, 25),
        )
        self.assertIn("Buying a Train Ticket at the Station", client.prompts[0])

    def test_excel_topic_history_is_injected_into_generation(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        config = load_config()
        client = _FakeGeminiClient(fixture)
        ContentPackGenerator(config, client).create(
            playlist=config.active_playlists[0],
            history=[],
            existing_topics=["Video 1: Booking a Doctor's Appointment"],
            today=date(2026, 10, 25),
        )
        self.assertIn("checked-in Excel tracker", client.prompts[0])
        self.assertIn("Booking a Doctor's Appointment", client.prompts[0])

    def test_validation_failure_gets_one_bounded_tutor_repair(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        config = load_config()
        client = _RepairingGeminiClient(fixture)
        record = ContentPackGenerator(config, client).create(
            playlist=config.active_playlists[0],
            history=[],
            today=date(2026, 10, 25),
        )

        self.assertEqual(client.calls, 4)
        self.assertIn("does not use linked vocabulary word family", client.prompts[2])
        self.assertIn("recognisable natural word-family form", client.prompts[2])
        self.assertIn("final adversarial Talkivana conversation auditor", client.prompts[3])
        self.assertTrue(
            any("Deterministic validation repair" in item for item in record.qa_problems)
        )

    def test_final_topic_repair_replaces_the_complete_linked_pair(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        replacement = copy.deepcopy(fixture)
        replacement["shorts"][0]["topic"] = "checking into a hotel"
        replacement["shorts"][0]["title"] = "German Words for a Hotel Arrival"
        replacement["long_videos"][0]["title"] = "Checking Into a Hotel in German"
        replacement["long_videos"][0]["scenario"] = (
            "A hotel guest checks in at the reception desk."
        )
        replacement["long_videos"][0]["learning_objective"] = (
            "Understand and repeat a simple hotel check-in conversation."
        )
        replacement["shorts"][1]["topic"] = "borrowing a library book"
        replacement["shorts"][1]["title"] = "German Words for the Library Desk"
        replacement["long_videos"][1]["title"] = "Borrowing a Library Book in German"
        replacement["long_videos"][1]["scenario"] = (
            "A library visitor borrows a book at the service desk."
        )
        replacement["long_videos"][1]["learning_objective"] = (
            "Understand and repeat a simple library borrowing conversation."
        )
        config = load_config()
        client = _FullPairRepairGeminiClient(fixture, replacement)

        record = ContentPackGenerator(config, client).create(
            playlist=config.active_playlists[0],
            history=[],
            existing_topics=["Video 1: Meeting a New Neighbor for Morning Coffee in German"],
            today=date(2026, 11, 8),
        )

        self.assertEqual(
            record.content["long_videos"][0]["title"],
            "Checking Into a Hotel in German",
        )
        repair_prompts = [
            prompt
            for prompt in client.prompts
            if "failed deterministic validation" in prompt
        ]
        self.assertEqual(len(repair_prompts), 2)
        self.assertNotIn("final bounded repair attempt", repair_prompts[0])
        self.assertIn("replace the complete linked", repair_prompts[1])
        self.assertIn("Never solve a topic collision", repair_prompts[1])

    def test_ignored_collision_repairs_trigger_one_clean_slate_pack(self):
        fixture = json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        )["content"]
        replacement = copy.deepcopy(fixture)
        replacement["shorts"][0]["topic"] = "checking into a hotel"
        replacement["shorts"][0]["title"] = "German Words for a Hotel Arrival"
        replacement["long_videos"][0]["title"] = "Checking Into a Hotel in German"
        replacement["long_videos"][0]["scenario"] = "A guest checks in at a hotel desk."
        replacement["long_videos"][0]["learning_objective"] = (
            "Check in politely and understand the receptionist's basic questions."
        )
        replacement["shorts"][1]["topic"] = "borrowing a library book"
        replacement["shorts"][1]["title"] = "German Words for the Library Desk"
        replacement["long_videos"][1]["title"] = "Borrowing a Library Book in German"
        replacement["long_videos"][1]["scenario"] = "A visitor borrows a library book."
        replacement["long_videos"][1]["learning_objective"] = (
            "Borrow a book and understand a simple due-date response."
        )
        config = load_config()
        client = _FreshPackFallbackGeminiClient(fixture, replacement)

        record = ContentPackGenerator(config, client).create(
            playlist=config.active_playlists[0],
            history=[],
            existing_topics=["Video 1: Meeting a New Neighbor for Morning Coffee in German"],
            today=date(2026, 11, 8),
        )

        self.assertEqual(record.content["shorts"][0]["topic"], "checking into a hotel")
        fresh_prompts = [
            prompt for prompt in client.prompts if "clean slate" in prompt
        ]
        self.assertEqual(len(fresh_prompts), 1)
        self.assertIn("Rejected concepts that are forbidden", fresh_prompts[0])


if __name__ == "__main__":
    unittest.main()
