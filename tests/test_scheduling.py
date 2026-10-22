import unittest
from datetime import date, datetime, timezone

from language_video_automation.scheduling import (
    PerformanceSample,
    build_timing_plan,
    next_publish_time,
    timing_stage,
)


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


if __name__ == "__main__":
    unittest.main()

