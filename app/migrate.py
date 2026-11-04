from pathlib import Path

from alembic.config import Config

from alembic import command

_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def upgrade_database(url: str) -> None:
    configuration = Config(str(_INI))
    configuration.set_main_option("script_location", str(_INI.parent / "alembic"))
    configuration.set_main_option("sqlalchemy.url", url)
    command.upgrade(configuration, "head")
