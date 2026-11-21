import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QIcon, QWindow
from PySide6.QtWidgets import QApplication

from editor import MENU_STYLE
from window import MainWindow

LOGO = Path(__file__).parent.parent / "assets" / "logo.svg"

if sys.platform == "win32":
    # Without its own app ID, Windows groups the window under python.exe and shows Python's taskbar icon.
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("stemgraph")


class MenuWindowStyle(QObject):
    """Windows 11 draws popup menus with a thin border and large rounded corners; use no border and small corners.

    Qt sets these itself when a menu's native window is shown, so they're re-applied whenever a popup window is
    exposed (drawn), which comes after that.
    """

    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWCP_ROUNDSMALL = 3
    DWMWA_BORDER_COLOR = 34
    DWMWA_COLOR_NONE = 0xFFFFFFFE

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Expose and isinstance(obj, QWindow) and obj.type() == Qt.Popup:
            hwnd = int(obj.winId())
            for attribute, value in [
                (self.DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.c_int(self.DWMWCP_ROUNDSMALL)),
                (self.DWMWA_BORDER_COLOR, ctypes.c_uint(self.DWMWA_COLOR_NONE)),
            ]:
                # Fails harmlessly before Windows 11.
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), 4)
        return False


app = QApplication(sys.argv)
app.setWindowIcon(QIcon(str(LOGO)))
app.setStyleSheet(MENU_STYLE)
if sys.platform == "win32":
    menu_window_style = MenuWindowStyle()
    app.installEventFilter(menu_window_style)
window = MainWindow()
window.resize(1200, 800)
window.show()
sys.exit(app.exec())
