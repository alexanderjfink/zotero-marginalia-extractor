"""Progress / cancellation protocol between the helper and the Zotero plugin.

The helper writes a small JSON status file after every page; the plugin polls
it while the process runs. A separate cancel file, written by the plugin, is
checked between pages so a long extraction can be stopped.
"""

from __future__ import annotations

import json
import os
from typing import Optional


class Progress:
    def __init__(self, path: Optional[str], cancel_path: Optional[str] = None):
        self.path = path
        self.cancel_path = cancel_path

    def write(
        self,
        status: str,
        done: int = 0,
        total: int = 0,
        message: str = "",
        page: Optional[int] = None,
    ) -> None:
        if not self.path:
            return
        payload = {
            "status": status,
            "done": done,
            "total": total,
            "message": message,
            "page": page,
        }
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def cancelled(self) -> bool:
        if not self.cancel_path:
            return False
        return os.path.exists(self.cancel_path)

    def clear_cancel(self) -> None:
        if self.cancel_path and os.path.exists(self.cancel_path):
            try:
                os.remove(self.cancel_path)
            except OSError:
                pass
