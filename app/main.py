"""基石 · 本地化批量文档脱敏工具 入口。"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow

def _crash_log_path() -> Path:
    """打包版 crash.log 放 exe 同级，方便用户找到；源码运行仍在项目根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "crash.log"
    return Path(__file__).resolve().parent.parent / "crash.log"


_CRASH_LOG = _crash_log_path()


def _excepthook(exc_type, exc, tb) -> None:
    """未捕获异常写入 crash.log，避免静默闪退无处排查。"""
    _CRASH_LOG.write_text("".join(traceback.format_exception(exc_type, exc, tb)),
                          encoding="utf-8")


def main() -> int:
    sys.excepthook = _excepthook
    app = QApplication(sys.argv)
    app.setApplicationName("基石")
    app.setOrganizationName("Jishi")
    from app.ui.qss import APP_QSS
    app.setStyleSheet(APP_QSS)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
