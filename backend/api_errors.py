from collections.abc import Callable
from typing import TypeVar

from fastapi import HTTPException

T = TypeVar("T")


def handle_api_errors(
    action: Callable[[], T],
    *,
    value_error_status: int,
    runtime_error_status: int | None = None,
    fallback_status: int = 500,
    fallback_message: str | None = None,
) -> T:
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(status_code=value_error_status, detail=str(exc)) from exc
    except RuntimeError as exc:
        if runtime_error_status is None:
            raise
        raise HTTPException(status_code=runtime_error_status, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        detail = fallback_message.format(error=exc) if fallback_message else str(exc)
        raise HTTPException(status_code=fallback_status, detail=detail) from exc
