from dataclasses import dataclass

STAGES = ("read", "layout", "fix", "epub", "optimize", "xtc")


@dataclass(frozen=True)
class Finding:
    page: int
    kind: str
    level: str  # "info" or "warning"
    message: str


@dataclass(frozen=True)
class StageEvent:
    stage: str
    status: str


@dataclass(frozen=True)
class PageEvent:
    done: int
    total: int


@dataclass(frozen=True)
class FindingEvent:
    finding: Finding


Event = StageEvent | PageEvent | FindingEvent


class Cancelled(Exception):
    pass
