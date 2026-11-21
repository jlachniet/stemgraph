"""The start window shown at launch (New, Open…, recent projects) and the About window.

Both are panels floating over the middle of the main window, not separate windows: Esc or a click anywhere else in
the main window closes them, and Tab cycles through their own controls only.
"""

import html
import re
from pathlib import Path

from PySide6.QtCore import QByteArray, QDir, QEvent, QObject, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QKeySequence, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

import strings
from editor import (
    FIELD_BACKGROUND,
    FIELD_BORDER,
    FIELD_BORDER_ACTIVE,
    ICON_SIZE,
    MENU_BACKGROUND,
    MENU_HEADING,
    MENU_HOVER,
    PORT,
    TEXT,
    load_icon,
)

LOCKUP = Path(__file__).parent.parent / "assets" / "lockup.svg"
GITHUB_URL = "https://github.com/jlachniet/stemgraph"
LICENSE_URL = GITHUB_URL + "/blob/main/LICENSE"
# Links in strings.THIRD_PARTY, by field name, in the order they're shown
THIRD_PARTY_URLS = {
    "numpy": "https://numpy.org/",
    "soundfile": "https://github.com/bastibe/python-soundfile",
    "libsndfile": "https://libsndfile.github.io/libsndfile/",
    "qt": "https://doc.qt.io/qtforpython-6/",
    "radix_icons": "https://github.com/radix-ui/icons",
    "radix_colors": "https://www.radix-ui.com/colors",
    "paper": "https://arxiv.org/abs/2206.02125",
}

PANEL_MARGIN = 24
PANEL_RADIUS = 8
COLUMN_GAP = 24
LEFT_WIDTH = 240
RIGHT_WIDTH = 320
ABOUT_WIDTH = 400
LOCKUP_WIDTH = 200
LOCKUP_GAP = 14  # between the lockup and the version
BUTTON_HEIGHT = 32
ROW_PADDING = 12  # left/right inset of button and recent-row contents, like menu items
ROW_GAP = 2  # between a recent project's name and its folder
SMALL = 0.9  # size of secondary text (version, folders, credits), relative to the normal font

STYLE = f"""
QFrame#panel {{ background: {MENU_BACKGROUND}; border-radius: {PANEL_RADIUS}px; }}
QLabel {{ color: {TEXT.name()}; background: transparent; }}
QLabel#muted {{ color: {MENU_HEADING}; }}
QLabel#heading {{ color: {MENU_HEADING}; padding: 0 {ROW_PADDING}px; }}
QPushButton#row {{
    background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 0; outline: none;
}}
QPushButton#row:hover {{ background: {MENU_HOVER}; }}
QPushButton#row:focus {{ border-color: {FIELD_BORDER_ACTIVE}; }}
QPushButton#ok {{
    background: {FIELD_BACKGROUND}; color: {TEXT.name()};
    border: 1px solid {FIELD_BORDER}; border-radius: 4px; padding: 4px 20px; outline: none;
}}
QPushButton#ok:hover, QPushButton#ok:focus {{ border-color: {FIELD_BORDER_ACTIVE}; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
"""


def _small_font(widget: QWidget) -> QFont:
    font = QFont(widget.font())
    font.setPointSizeF(font.pointSizeF() * SMALL)
    return font


def _link(url: str) -> str:
    return f'<a href="{html.escape(url)}" style="color: {PORT.name()}; text-decoration: none;">'


def credits_html() -> str:
    license = _link(LICENSE_URL) + html.escape(strings.LICENSE_NAME) + "</a>"
    return html.escape(strings.CREDITS, quote=False).format(license=license, github=_link(GITHUB_URL), end="</a>")


def third_party_html(text: str) -> str:
    links = {key: _link(url) for key, url in THIRD_PARTY_URLS.items()}
    return html.escape(text, quote=False).format(end="</a>", **links)


def lockup_label(dpr: float) -> QLabel:
    """The logo and name, without the background and margins the SVG file has for social previews."""
    svg = LOCKUP.read_text()
    svg = re.sub(r'<path fill="#191919" d="M-48-48[^"]*"/>', "", svg)  # the background
    svg = svg.replace('viewBox="-48 -48 613.404 192"', 'viewBox="0 0 517.404 96"')  # the margins
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    size = renderer.defaultSize().scaled(round(LOCKUP_WIDTH * dpr), 10_000, Qt.KeepAspectRatio)
    pixmap = QPixmap(size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(dpr)
    label = QLabel()
    label.setPixmap(pixmap)
    return label


def fit_height(label: QLabel, width: int) -> None:
    """Fix a wrapping label's height to what its text needs at `width`; layouts otherwise leave extra space."""
    label.setFixedSize(width, label.heightForWidth(width))


class LinkLabel(QLabel):
    """Wrapping rich text whose links open in the browser, and which Tab moves through link by link."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setTextFormat(Qt.RichText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.LinksAccessibleByMouse | Qt.LinksAccessibleByKeyboard)
        self.setFocusPolicy(Qt.TabFocus)
        self.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        # Qt only picks a link on the next Tab; pick the first (or, going backwards, the last) right away, so
        # one Tab reaches it and Enter opens it.
        if event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason):
            super().focusNextPrevChild(event.reason() == Qt.TabFocusReason)


def muted_label(text: str, rich: bool = False) -> QLabel:
    label = LinkLabel(text) if rich else QLabel(text)
    label.setObjectName("muted")
    label.setFont(_small_font(label))
    if not rich:
        label.setTextFormat(Qt.PlainText)
    return label


class PanelButton(QPushButton):
    """A button that Enter also clicks, and that leaves Up/Down to the panel."""

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.click()
        elif event.key() in (Qt.Key_Up, Qt.Key_Down):
            event.ignore()
        else:
            super().keyPressEvent(event)


class Panel(QFrame):
    """A panel floating over the middle of the main window. Closed by Esc or a click elsewhere in the window."""

    closed = Signal()

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self.window_ = window
        self.setObjectName("panel")
        self.setStyleSheet(STYLE)
        self.setFocusPolicy(Qt.ClickFocus)  # holds focus when nothing in it is chosen, but isn't a Tab stop
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.setGraphicsEffect(shadow)
        self._watcher = _Watcher(self)
        window.installEventFilter(self._watcher)
        QApplication.instance().installEventFilter(self._watcher)

    def tab_order(self) -> list[QWidget]:
        """The controls Tab moves through, in order."""
        raise NotImplementedError

    def open(self) -> None:
        self.adjustSize()  # respects the height that wrapped text needs at the panel's width
        self.setFixedSize(self.size())
        self.place()
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)

    def place(self) -> None:
        """Center over the main window's canvas."""
        area = self.window_.centralWidget().geometry()
        rect = QRect(0, 0, self.width(), self.height())
        rect.moveCenter(area.center())
        self.move(rect.topLeft())

    def dismiss(self) -> None:
        if not self.isVisible():
            return
        app = QApplication.instance()
        app.removeEventFilter(self._watcher)
        self.window_.removeEventFilter(self._watcher)
        had_focus = self.isAncestorOf(app.focusWidget()) or app.focusWidget() is self
        self.hide()
        self.deleteLater()
        if had_focus:
            self.window_.centralWidget().setFocus(Qt.OtherFocusReason)
        self.closed.emit()

    def focusNextPrevChild(self, next: bool) -> bool:
        chain = [w for w in self.tab_order() if w.isVisible() and w.isEnabled()]
        if not chain:
            return True
        current = QApplication.focusWidget()
        if current in chain:
            i = chain.index(current) + (1 if next else -1)
        else:
            i = 0 if next else -1
        chain[i % len(chain)].setFocus(Qt.TabFocusReason if next else Qt.BacktabFocusReason)
        return True

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()  # a click on the panel's background mustn't reach the window and count as outside it


class _Watcher(QObject):
    """Closes a panel on a click elsewhere in its window, and keeps it centered as the window resizes."""

    def __init__(self, panel: Panel) -> None:
        super().__init__(panel)
        self.panel = panel

    def eventFilter(self, obj, event) -> bool:
        if obj is self.panel.window_ and event.type() == QEvent.Resize:
            self.panel.place()
        elif (
            event.type() == QEvent.MouseButtonPress
            and isinstance(obj, QWidget)
            and obj.window() is self.panel.window_
            and obj is not self.panel
            and not self.panel.isAncestorOf(obj)
        ):
            self.panel.dismiss()  # and let the click through
        return False


# --- Start window ---


class RecentDelegate(QStyledItemDelegate):
    """Draws a recent project as its name over its folder, highlighted like a menu item. The folder is shortened in
    the middle when it doesn't fit, and then shown in full as a tooltip."""

    PATH_ROLE = Qt.UserRole

    def __init__(self, view: QListWidget) -> None:
        super().__init__(view)
        self.font = QFont(view.font())
        self.small = _small_font(view)

    def row_height(self) -> int:
        return 2 * 6 + QFontMetrics(self.font).height() + ROW_GAP + QFontMetrics(self.small).height()

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), self.row_height())

    def _folder(self, index) -> str:
        return QDir.toNativeSeparators(str(Path(index.data(self.PATH_ROLE)).parent))

    def _elided_folder(self, index, width: int) -> str:
        return QFontMetrics(self.small).elidedText(self._folder(index), Qt.ElideMiddle, width - 2 * ROW_PADDING)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = option.rect
        if option.state & (QStyle.State_MouseOver | QStyle.State_HasFocus):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(MENU_HOVER))
            painter.drawRoundedRect(rect, 4, 4)
        name_metrics, small_metrics = QFontMetrics(self.font), QFontMetrics(self.small)
        x, width = rect.left() + ROW_PADDING, rect.width() - 2 * ROW_PADDING
        y = rect.top() + 6
        painter.setPen(TEXT)
        painter.setFont(self.font)
        name = name_metrics.elidedText(index.data(Qt.DisplayRole), Qt.ElideRight, width)
        painter.drawText(QRect(x, y, width, name_metrics.height()), Qt.AlignLeft | Qt.AlignVCenter, name)
        y += name_metrics.height() + ROW_GAP
        painter.setPen(QColor(MENU_HEADING))
        painter.setFont(self.small)
        folder = self._elided_folder(index, rect.width())
        painter.drawText(QRect(x, y, width, small_metrics.height()), Qt.AlignLeft | Qt.AlignVCenter, folder)
        painter.restore()

    def helpEvent(self, event, view, option, index) -> bool:
        if event.type() == QEvent.ToolTip and index.isValid():
            if self._elided_folder(index, option.rect.width()) != self._folder(index):
                QToolTip.showText(event.globalPos(), self._folder(index), view)
            else:
                QToolTip.hideText()
            return True
        return super().helpEvent(event, view, option, index)


class RecentList(QListWidget):
    opened = Signal(str)  # a project's path

    def __init__(self) -> None:
        super().__init__()
        self.delegate = RecentDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setMouseTracking(True)  # hover highlight
        self.setSelectionMode(QListWidget.NoSelection)  # the delegate highlights the current row itself
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.TabFocus)
        self.itemClicked.connect(lambda item: self.opened.emit(item.data(RecentDelegate.PATH_ROLE)))

    def set_paths(self, paths: list[str]) -> None:
        self.clear()
        for path in paths:
            item = QListWidgetItem(Path(path).stem)
            item.setData(RecentDelegate.PATH_ROLE, path)
            self.addItem(item)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if self.currentRow() < 0 and self.count():
            self.setCurrentRow(self.count() - 1 if event.reason() == Qt.BacktabFocusReason else 0)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            item = self.currentItem()
            if item:
                self.opened.emit(item.data(RecentDelegate.PATH_ROLE))
        else:
            super().keyPressEvent(event)


class StartPanel(Panel):
    """New, Open… and the recent projects, with the logo, version and credits. Shown when stemgraph starts.

    `window` is the MainWindow: it provides new(), open(), open_recent(path), recent_files() and recent_changed,
    and closes the panel when a project is opened or started.
    """

    def __init__(self, window, max_recent: int) -> None:
        super().__init__(window)
        self.new_button = self._button("file-plus", strings.START_NEW, "Ctrl+N", window.new)
        self.open_button = self._button("file", strings.START_OPEN, "Ctrl+O", window.open)
        self.credits = muted_label(credits_html(), rich=True)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        left.addWidget(lockup_label(window.devicePixelRatioF()))
        left.addSpacing(LOCKUP_GAP)
        version = muted_label(strings.VERSION_LABEL.format(version=strings.VERSION))
        left.addWidget(version)
        left.addSpacing(14)
        left.addWidget(self.new_button)
        left.addSpacing(2)
        left.addWidget(self.open_button)
        left.addStretch()
        left.addSpacing(24)
        fit_height(self.credits, LEFT_WIDTH)
        left.addWidget(self.credits)

        self.recent = RecentList()
        self.recent.opened.connect(window.open_recent)
        self.recent.setFixedHeight(max_recent * self.recent.delegate.row_height())
        self.no_recent = muted_label(strings.NO_RECENT)
        self.no_recent.setContentsMargins(ROW_PADDING, 0, 0, 0)
        heading = QLabel(strings.START_RECENT_HEADING)
        heading.setObjectName("heading")
        heading.setFont(_small_font(heading))
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        right.addWidget(heading)
        right.addWidget(self.recent)
        right.addWidget(self.no_recent)
        right.addStretch()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(COLUMN_GAP)
        for column, width in [(left, LEFT_WIDTH), (right, RIGHT_WIDTH)]:
            holder = QWidget()
            holder.setFixedWidth(width)
            holder.setLayout(column)
            layout.addWidget(holder)

        window.recent_changed.connect(self._show_recent)
        self._show_recent()

    def _button(self, icon: str, text: str, keys: str, slot) -> PanelButton:
        """A full-width button: icon, text, and its shortcut on the right."""
        button = PanelButton()
        button.setObjectName("row")
        button.setFixedHeight(BUTTON_HEIGHT)
        button.setFocusPolicy(Qt.TabFocus)
        button.setAccessibleName(text)
        button.clicked.connect(slot)
        layout = QHBoxLayout(button)
        layout.setContentsMargins(ROW_PADDING - 2, 0, ROW_PADDING, 0)  # the icon's 15px box has a little margin
        layout.setSpacing(8)
        icon_label = QLabel()
        icon_label.setPixmap(load_icon(icon, ICON_SIZE).pixmap(ICON_SIZE, ICON_SIZE))
        shortcut = muted_label(QKeySequence(keys).toString(QKeySequence.NativeText))
        for label in (icon_label, QLabel(text), shortcut):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(label)
        layout.insertStretch(2)
        return button

    def _show_recent(self) -> None:
        had_focus = self.recent.hasFocus()
        paths = self.window_.recent_files()
        self.recent.set_paths(paths)
        self.recent.setVisible(bool(paths))
        self.no_recent.setVisible(not paths)
        if had_focus and not paths:
            self.setFocus(Qt.OtherFocusReason)

    def tab_order(self) -> list[QWidget]:
        return [self.new_button, self.open_button, self.recent, self.credits]

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Up, Qt.Key_Down) and self.recent.isVisible() and not self.recent.hasFocus():
            reason = Qt.BacktabFocusReason if event.key() == Qt.Key_Up else Qt.TabFocusReason
            self.recent.setFocus(reason)
        else:
            super().keyPressEvent(event)


# --- About ---


class AboutPanel(Panel):
    """The logo, version, credits and third-party credits, with an OK button."""

    def __init__(self, window) -> None:
        super().__init__(window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN, PANEL_MARGIN)
        layout.setSpacing(0)
        layout.addWidget(lockup_label(window.devicePixelRatioF()))
        layout.addSpacing(LOCKUP_GAP)
        layout.addWidget(muted_label(strings.VERSION_LABEL.format(version=strings.VERSION)))
        layout.addSpacing(16)
        width = ABOUT_WIDTH - 2 * PANEL_MARGIN
        self.links = [muted_label(credits_html(), rich=True)]
        fit_height(self.links[0], width)
        layout.addWidget(self.links[0])
        layout.addSpacing(16)
        heading = QLabel(strings.ABOUT_THIRD_PARTY_HEADING)
        layout.addWidget(heading)
        for text in strings.THIRD_PARTY:
            layout.addSpacing(6)
            label = muted_label(third_party_html(text), rich=True)
            fit_height(label, width)
            self.links.append(label)
            layout.addWidget(label)
        layout.addSpacing(24)
        self.ok = PanelButton(strings.ABOUT_OK)
        self.ok.setObjectName("ok")
        self.ok.setFocusPolicy(Qt.TabFocus)
        self.ok.clicked.connect(self.dismiss)
        layout.addWidget(self.ok, alignment=Qt.AlignRight)
        self.setFixedWidth(ABOUT_WIDTH)

    def tab_order(self) -> list[QWidget]:
        return [*self.links, self.ok]

    def open(self) -> None:
        super().open()
        self.ok.setFocus(Qt.OtherFocusReason)
