import json
import unittest
from datetime import date, datetime, timedelta, timezone

from language_video_automation.scheduling import (
    PerformanceSample,
    build_timing_plan,
    next_publish_time,
    timing_stage,
)
from language_video_automation.config import load_config, project_root
from language_video_automation.github_api import Issue, write_upload_manifest
from language_video_automation.models import ContentPackRecord
from language_video_automation.pipeline import (
    _build_earliest_pack_schedule,
    _reserved_slots_by_date,
)


class _NoScheduledPacks:
    def list_issues(self, **_kwargs):
        return []


class _OneReservedSlot:
    def list_issues(self, **_kwargs):
        body = write_upload_manifest("", {
            "assets": {
                "short-1": {
                    "scheduled_at": "2026-10-24T12:30:00+05:30",
                    "slot_local": "12:30",
                }
            }
        })
        return [Issue(
            number=99,
            title="Scheduled pack",
            body=body,
            state="closed",
            labels=("talkivana", "pack-scheduled"),
            html_url="https://example.test/issues/99",
        )]


class _ExistingSchedules:
    def __init__(self, manifests):
        self.manifests = manifests

    def list_issues(self, **_kwargs):
        return [
            Issue(
                number=100 + index,
                title=f"Scheduled pack {index}",
                body=write_upload_manifest("", {"assets": assets}),
                state="closed",
                labels=("talkivana", "pack-scheduled"),
                html_url=f"https://example.test/issues/{100 + index}",
            )
            for index, assets in enumerate(self.manifests)
        ]


class SchedulingTests(unittest.TestCase):
    def test_moves_to_next_slot_when_lead_time_requires_it(self):
        now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        scheduled = next_publish_time(
            timezone_name="Asia/Kolkata",
            local_time="18:00",
            minimum_lead_hours=18,
            now=now,
        )
        self.assertEqual(scheduled, datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc))

    def test_three_timing_stages(self):
        launch = date(2026, 1, 1)
        self.assertEqual(timing_stage(launch_date=launch, on_date=date(2026, 1, 30))[0], 1)
        self.assertEqual(timing_stage(launch_date=launch, on_date=date(2026, 1, 31))[0], 2)
        self.assertEqual(timing_stage(launch_date=launch, on_date=date(2026, 3, 2))[0], 3)

    def test_stage_one_balances_four_unique_slots(self):
        plan = build_timing_plan(
            launch_date=date(2026, 1, 1),
            on_date=date(2026, 1, 10),
            slots=["07:30", "12:30", "18:00", "22:30"],
            samples=[],
        )
        self.assertEqual(plan.stage, 1)
        self.assertEqual(len({slot for _, slot in plan.assignments}), 4)
        assignments = dict(plan.assignments)
        self.assertNotEqual(assignments["long-1"], assignments["long-2"])

    def test_stable_conveyor_disables_automatic_rotation(self):
        assignments = {
            "short-1": "07:30",
            "long-1": "12:30",
            "short-2": "18:00",
            "long-2": "22:30",
        }
        plan = build_timing_plan(
            launch_date=date(2026, 1, 1),
            on_date=date(2026, 4, 1),
            slots=["07:30", "12:30", "18:00", "22:30"],
            samples=[],
            stable_assignments=assignments,
            automatic_reassignment=False,
        )
        self.assertEqual(dict(plan.assignments), assignments)
        self.assertEqual(plan.exploration_ratio, 0.0)
        self.assertIn("owner approval", plan.explanation)

    def test_later_stage_scores_formats_separately(self):
        samples = [
            PerformanceSample(
                asset_id=f"s{index}", format="short", slot_local="07:30",
                published_at=datetime.now(timezone.utc), views_24h=1000, views_7d=2000,
                average_percentage_viewed=90,
            )
            for index in range(4)
        ]
        plan = build_timing_plan(
            launch_date=date(2026, 1, 1),
            on_date=date(2026, 4, 1),
            slots=["07:30", "12:30", "18:00", "22:30"],
            samples=samples,
        )
        short_score = next(item for item in plan.scores if item.format == "short" and item.slot_local == "07:30")
        self.assertEqual(short_score.confidence, "sufficient")

    def test_missed_same_day_slot_uses_near_immediate_catch_up_instead_of_next_day(self):
        record = ContentPackRecord.from_dict(json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        ))
        config = load_config()
        config.raw["approval"]["rolling_buffer_days"] = 0
        short_date, long_date, slots, publish_times, catch_up_assets = (
            _build_earliest_pack_schedule(
                github=_NoScheduledPacks(),
                config=config,
                record=record,
                slot_by_asset={
                    "short-1": "22:30",
                    "short-2": "12:30",
                    "long-1": "07:30",
                    "long-2": "18:00",
                },
                now=datetime(2026, 10, 24, 11, 15, tzinfo=timezone.utc),
            )
        )
        self.assertEqual(short_date, date(2026, 10, 24))
        self.assertEqual(long_date, date(2026, 10, 25))
        self.assertEqual(len(set(slots.values())), 4)
        self.assertEqual(
            publish_times["short-2"],
            datetime(2026, 10, 24, 11, 20, tzinfo=timezone.utc),
        )
        self.assertEqual(slots["short-2"], "16:50")
        self.assertEqual(catch_up_assets, {"short-2"})
        self.assertEqual(
            publish_times["long-1"],
            datetime(2026, 10, 25, 2, 0, tzinfo=timezone.utc),
        )

    def test_multiple_missed_slots_are_not_released_together(self):
        record = ContentPackRecord.from_dict(json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        ))
        config = load_config()
        config.raw["approval"]["rolling_buffer_days"] = 0
        _, _, _, publish_times, catch_up_assets = _build_earliest_pack_schedule(
            github=_NoScheduledPacks(),
            config=config,
            record=record,
            slot_by_asset={
                "short-1": "07:30",
                "short-2": "12:30",
                "long-1": "18:00",
                "long-2": "22:30",
            },
            now=datetime(2026, 10, 24, 12, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(catch_up_assets, {"short-1", "short-2"})
        self.assertEqual(
            publish_times["short-2"] - publish_times["short-1"],
            timedelta(minutes=30),
        )

    def test_scheduler_checks_existing_schedule_before_assigning_a_slot(self):
        reservations = _reserved_slots_by_date(_OneReservedSlot())
        self.assertEqual(reservations[date(2026, 10, 24)], {"12:30"})

    def test_future_conveyor_starts_after_legacy_schedules_without_moving_them(self):
        record = ContentPackRecord.from_dict(json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        ))
        legacy = {
            "short-1": {"scheduled_at": "2026-10-27T12:30:00+05:30", "slot_local": "12:30"},
            "short-2": {"scheduled_at": "2026-10-27T22:30:00+05:30", "slot_local": "22:30"},
            "long-1": {"scheduled_at": "2026-10-28T18:00:00+05:30", "slot_local": "18:00"},
            "long-2": {"scheduled_at": "2026-10-28T07:30:00+05:30", "slot_local": "07:30"},
        }
        assignments = {
            "short-1": "07:30",
            "long-1": "12:30",
            "short-2": "18:00",
            "long-2": "22:30",
        }
        short_date, long_date, actual_slots, _, catch_up = _build_earliest_pack_schedule(
            github=_ExistingSchedules([legacy]),
            config=load_config(),
            record=record,
            slot_by_asset=assignments,
            strict_slot_assignments=True,
            now=datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(short_date, date(2026, 10, 29))
        self.assertEqual(long_date, date(2026, 10, 30))
        self.assertEqual(actual_slots, assignments)
        self.assertEqual(catch_up, set())

    def test_next_pack_overlaps_prior_longs_to_fill_all_four_daily_slots(self):
        record = ContentPackRecord.from_dict(json.loads(
            (project_root() / "tests" / "fixtures" / "sample_pack.json").read_text(
                encoding="utf-8"
            )
        ))
        previous = {
            "short-1": {"scheduled_at": "2026-10-29T07:30:00+05:30", "slot_local": "07:30"},
            "short-2": {"scheduled_at": "2026-10-29T18:00:00+05:30", "slot_local": "18:00"},
            "long-1": {"scheduled_at": "2026-10-30T12:30:00+05:30", "slot_local": "12:30"},
            "long-2": {"scheduled_at": "2026-10-30T22:30:00+05:30", "slot_local": "22:30"},
        }
        assignments = {
            "short-1": "07:30",
            "long-1": "12:30",
            "short-2": "18:00",
            "long-2": "22:30",
        }
        short_date, long_date, actual_slots, _, catch_up = _build_earliest_pack_schedule(
            github=_ExistingSchedules([previous]),
            config=load_config(),
            record=record,
            slot_by_asset=assignments,
            strict_slot_assignments=True,
            now=datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(short_date, date(2026, 10, 30))
        self.assertEqual(long_date, date(2026, 10, 31))
        self.assertEqual(actual_slots, assignments)
        self.assertEqual(catch_up, set())


if __name__ == "__main__":
    unittest.main()
