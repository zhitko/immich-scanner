from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.runtime import Services


def get_services(request: Request) -> Services:
    return request.app.state.services


def get_session(services: Services = Depends(get_services)) -> Iterator[Session]:
    session = services.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
