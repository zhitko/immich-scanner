import secrets
from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Request
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


def require_scanner_token(
    services: Services = Depends(get_services),
    x_scanner_token: str = Header(default=""),
) -> None:
    expected = services.settings.scanner_api_token
    if not expected or not secrets.compare_digest(x_scanner_token, expected):
        raise HTTPException(status_code=401, detail="Invalid scanner token")
