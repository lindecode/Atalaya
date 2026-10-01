from __future__ import annotations

import winsound


class WindowsNotifier:
    def notify(self, title: str, message: str) -> None:
        print(f"[NOTIFICACIÓN] {title}: {message}")
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except RuntimeError:
            pass

