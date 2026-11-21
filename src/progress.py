"""The build progress window: the current step, "Step 3 of 7", and a log. The build runs on a background thread."""

import html
import threading

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

import build
import strings
from editor import FIELD_BACKGROUND, FIELD_BORDER, TEXT

LOG_COLORS = {
    build.INFO: TEXT.name(),
    build.WARNING: "#ffca16",  # amber-11 (Radix dark)
    build.ERROR: "#ff9592",    # red-11 (Radix dark)
}
LOG_STYLE = f"""
QPlainTextEdit {{
    background: {FIELD_BACKGROUND}; color: {TEXT.name()};
    border: 1px solid {FIELD_BORDER}; border-radius: 3px;
}}
"""
MARGIN = 16
TOP_MARGIN = 8  # the title bar already sets the dialog's contents apart


class BuildThread(QThread):
    step_started = Signal(int, str)
    logged = Signal(str, str)  # kind, text
    finished_build = Signal(bool)  # True if every file was written

    def __init__(self, plan: build.Plan, folder: str) -> None:
        super().__init__()
        self.plan = plan
        self.folder = folder
        self.cancel_requested = threading.Event()

    def run(self) -> None:
        ok = build.run(self.plan, self.folder, self.step_started.emit, self.logged.emit,
                       self.cancel_requested.is_set)
        self.finished_build.emit(ok)


class ProgressDialog(QDialog):
    """Runs a build and shows its progress. Esc and ✕ cancel while it runs, and close it afterwards."""

    def __init__(self, parent, plan: build.Plan, folder: str, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.folder = folder
        self.total = len(plan.steps)
        self.succeeded = False

        self.step = QLabel(strings.STARTING)
        font = self.step.font()
        font.setBold(True)
        self.step.setFont(font)
        self.count = QLabel()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(LOG_STYLE)
        self.log.setFont(QFont("Consolas"))
        self.log.setMinimumSize(560, 240)

        self.buttons = QDialogButtonBox()
        self.cancel_button = self.buttons.addButton(QDialogButtonBox.Cancel)
        self.cancel_button.clicked.connect(self.cancel)
        self.open_button = QPushButton(strings.OPEN_FOLDER)
        self.open_button.clicked.connect(self.open_folder)
        self.close_button = self.buttons.addButton(QDialogButtonBox.Close)
        self.close_button.clicked.connect(self.accept)
        self.open_button.hide()
        self.close_button.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN, TOP_MARGIN, MARGIN, MARGIN)
        layout.setSpacing(8)
        layout.addWidget(self.step)
        layout.addWidget(self.count)
        layout.addWidget(self.log, 1)
        layout.addSpacing(MARGIN - 8)
        layout.addWidget(self.buttons)
        self._show_count(0)

        self.thread = BuildThread(plan, folder)
        self.thread.step_started.connect(self._step_started)
        self.thread.logged.connect(self._logged)
        self.thread.finished_build.connect(self._finished)

    def exec(self) -> int:
        self.thread.start()
        return super().exec()

    def running(self) -> bool:
        return self.thread.isRunning() or self.close_button.isHidden()

    def _show_count(self, done: int) -> None:
        self.count.setText(strings.STEP_COUNT.format(done=done, total=self.total))

    def _step_started(self, index: int, label: str) -> None:
        self.step.setText(label)
        self._show_count(index + 1)

    def _logged(self, kind: str, text: str) -> None:
        color = LOG_COLORS[kind]
        self.log.appendHtml(f'<span style="color:{color}; white-space:pre-wrap">{html.escape(text)}</span>')

    def _finished(self, ok: bool) -> None:
        self.thread.wait()
        self.succeeded = ok
        if ok:
            self.step.setText(strings.DONE)
            self._show_count(self.total)
            self.buttons.addButton(self.open_button, QDialogButtonBox.ActionRole)
            self.open_button.show()
        elif self.thread.cancel_requested.is_set():
            self.step.setText(strings.CANCELLED)
        else:
            self.step.setText(strings.BUILD_FAILED)
        self.cancel_button.hide()
        self.close_button.show()
        self.close_button.setDefault(True)
        self.close_button.setFocus()

    def cancel(self) -> None:
        if not self.thread.cancel_requested.is_set():
            self.thread.cancel_requested.set()
            self.cancel_button.setEnabled(False)
            self._logged(build.INFO, strings.CANCELLING)

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder))

    def reject(self) -> None:  # Esc and ✕
        if self.running():
            self.cancel()
        else:
            super().reject()

    def closeEvent(self, event) -> None:
        if self.running():
            self.cancel()
            event.ignore()
        else:
            event.accept()
