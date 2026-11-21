import os

# Draw windows offscreen so the Qt tests don't flash windows up or need a display. Set before Qt is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path):
    """Give every test its own settings file, so tests never see or change the real recent files."""
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
