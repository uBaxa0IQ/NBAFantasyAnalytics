"""Serializable configuration and dataset records for draft ML."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TrainingConfig:
    format_name: str = "standard8"
    episodes: int = 1000
    seed: int = 2_609_021
    candidate_count: int = 10
    rollouts_per_candidate: int = 3
    team_count: int = 10
    rounds: int = 13
    workers: int = 1
    projection_gp_stddev: float = 0.12
    projection_stat_stddev: float = 0.08
    output_dir: str = "artifacts/draft_ml"
    policy_checkpoint: str | None = None
    behavior_policies: tuple[str, ...] = (
        "adaptive", "legacy_balanced", "legacy_fixed", "roto", "adp",
    )
    reward_weights: dict[str, float] = field(default_factory=lambda: {
        "category_wins": 1.0,
        "league_rank": -0.15,
        "downside": -0.20,
        "flexibility": 0.08,
    })

    def validate(self):
        categories_for_format(self.format_name)
        if self.episodes < 1:
            raise ValueError("episodes must be positive")
        if self.candidate_count < 2:
            raise ValueError("candidate_count must be at least 2")
        if self.rollouts_per_candidate < 1:
            raise ValueError("rollouts_per_candidate must be positive")
        if self.team_count < 2 or self.rounds < 1:
            raise ValueError("invalid league dimensions")
        if self.workers < 1:
            raise ValueError("workers must be positive")
        if not self.behavior_policies:
            raise ValueError("at least one behavior policy is required")
        supported = {"adaptive", "legacy_balanced", "legacy_fixed", "roto", "adp"}
        unknown = set(self.behavior_policies) - supported
        if unknown:
            raise ValueError(f"unsupported behavior policies: {sorted(unknown)}")
        required_rewards = {"category_wins", "league_rank", "downside", "flexibility"}
        if set(self.reward_weights) != required_rewards:
            raise ValueError(f"reward_weights must contain exactly {sorted(required_rewards)}")
        return self

    def to_dict(self):
        return asdict(self)

    @property
    def output_path(self):
        return Path(self.output_dir)


STANDARD_8_CATEGORIES = ("FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "PTS")
CUSTOM_11_CATEGORIES = ("FG%", "FT%", "3PM", "3PT%", "REB", "AST", "A/TO", "STL", "BLK", "DD", "PTS")


def categories_for_format(format_name):
    if format_name == "standard8":
        return STANDARD_8_CATEGORIES
    if format_name == "custom11":
        return CUSTOM_11_CATEGORIES
    raise ValueError(f"Unsupported format: {format_name}")
