"""Data models for scraped volunteer opportunities."""

from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime


@dataclass
class Opportunity:
    """A volunteer opportunity from the search results."""

    title: str
    organization: str
    location: str
    date: Optional[str] = None
    time: Optional[str] = None
    duration: Optional[str] = None
    datetime_iso: Optional[str] = None  # from data-order attribute
    distance: Optional[str] = None
    opportunity_type: str = "Volunteer Opportunity"
    opportunity_url: Optional[str] = None
    opportunity_id: Optional[str] = None
    organization_url: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)
