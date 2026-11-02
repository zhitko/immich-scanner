import logging

import uvicorn

from app.config import get_settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = get_settings()
    uvicorn.run("app.main:create_app", factory=True, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
