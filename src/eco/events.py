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
    page: int | None = None  # the source page that just finished, when the stage knows it


@dataclass(frozen=True)
class BookEvent:
    """The pages of a PDF, sent once after the `read` stage: for the GUI's page map."""

    pages: int
    scanned: tuple[int, ...]
    blank: tuple[int, ...]


@dataclass(frozen=True)
class FindingEvent:
    finding: Finding


Event = StageEvent | PageEvent | FindingEvent | BookEvent


class Cancelled(Exception):
    pass
