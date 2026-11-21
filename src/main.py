import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from editor import EditorView
from graph import Graph

LOGO = Path(__file__).parent.parent / "assets" / "logo.svg"

if sys.platform == "win32":
    # Without its own app ID, Windows groups the window under python.exe and shows Python's taskbar icon.
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("stemgraph")

app = QApplication(sys.argv)
app.setWindowIcon(QIcon(str(LOGO)))
view = EditorView(Graph())
view.setWindowTitle("stemgraph")
view.resize(1200, 800)
view.show()
sys.exit(app.exec())
