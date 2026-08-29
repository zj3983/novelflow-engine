from __future__ import annotations

import os
import threading
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar


_PROJECT_UPDATE_LOCKS: dict[str, threading.RLock] = {}
_PROJECT_UPDATE_LOCKS_GUARD = threading.Lock()
_Method = TypeVar("_Method", bound=Callable[..., Any])


def project_update_lock(root: Path) -> threading.RLock:
    key = os.path.normcase(str(root.resolve()))
    with _PROJECT_UPDATE_LOCKS_GUARD:
        return _PROJECT_UPDATE_LOCKS.setdefault(key, threading.RLock())


def with_project_update_lock(method: _Method) -> _Method:
    @wraps(method)
    def locked(self: Any, *args: Any, **kwargs: Any) -> Any:
        with project_update_lock(self.root):
            return method(self, *args, **kwargs)

    return locked  # type: ignore[return-value]
