from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from config import get_db_config


@contextmanager
def get_connection(*, dict_cursor: bool = False) -> Iterator[Connection]:
    connect_args = dict(get_db_config())
    if dict_cursor:
        connect_args["cursorclass"] = DictCursor

    connection = pymysql.connect(**connect_args)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def check_db() -> bool:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    return True
