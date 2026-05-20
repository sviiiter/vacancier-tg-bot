from bot.db.base import DatabaseDriver
from bot.db.sqlite import SQLiteDriver
from bot.db.postgres import PostgresDriver
from bot.db.mysql import MySQLDriver


def get_driver(driver_name: str, dsn: str) -> DatabaseDriver:
    drivers = {
        "sqlite": SQLiteDriver,
        "postgres": PostgresDriver,
        "mysql": MySQLDriver,
    }
    cls = drivers.get(driver_name.lower())
    if cls is None:
        raise ValueError(f"Unknown DB driver '{driver_name}'. Choose from: {', '.join(drivers)}")
    return cls(dsn)
