"""
modules/intelligence/dependencies.py

Responsibility
--------------
FastAPI dependency providers for the intelligence module, following the
same pattern as the inventory and orders modules. `get_today` is its own
dependency so tests can pin the clock with
`app.dependency_overrides[get_today] = lambda: date(...)`.
"""

from datetime import date

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.intelligence.repository import IntelligenceRepository
from app.modules.intelligence.service import IntelligenceService, utc_today


def get_today() -> date:
    """Current UTC date. Overridable in tests for deterministic results."""
    return utc_today()


def get_intelligence_repository(db: Session = Depends(get_db)) -> IntelligenceRepository:
    return IntelligenceRepository(db)


def get_intelligence_service(
    repository: IntelligenceRepository = Depends(get_intelligence_repository),
    today: date = Depends(get_today),
) -> IntelligenceService:
    return IntelligenceService(repository, today_provider=lambda: today)
