"""Qt view of the node graph: canvas, nodes, ports and wires."""

import json
import os
import re
import uuid
from pathlib import Path

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QEvent,
    QLineF,
    QMimeData,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFontMetrics,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QToolTip,
    QWidget,
)

import build
import strings
from graph import (
    AUTO,
    AUTO_CHOICE,
    CHOICES,
    GRID,
    NODE_TYPES,
    OFF,
    TOGGLES,
    Connection,
    Graph,
    Node,
    load_fragment,
    snap,
)
from project import ViewState

NODE_WIDTH = 8 * GRID
PORT_RADIUS = 6
OPEN_PORT_WIDTH = 2  # the ring of a growing node's empty input
TARGET_PORT_SCALE = 1.25  # while a wire is dragged, the ports it can connect to grow by this much
TARGET_PORT_MS = 100  # how long they take to grow (and change colour) or go back
DIMMED_OPACITY = 0.35  # and the nodes it can't connect to fade to this
CAPTION_GAP = 8  # space between a caption and its text box
SIGN_SIZE = GRID - 6  # each half of the + / − switch on a growing node's connected inputs, left of the label
SIGN_LEFT = 12  # its left edge, just clear of the port
SIGN_GAP = 6  # space between it and the input's label
ZOOM_LEVELS = (0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0)
WHEEL_NOTCH = 120  # angleDelta of one mouse-wheel notch
ICON_DIR = Path(__file__).parent.parent / "assets" / "icons"  # Radix Icons, MIT (see docs/design.md)
ICON_SIZE = 15  # Radix Icons are drawn on a 15px grid; render them 1:1 so they stay crisp
# Height of the corner controls, and width of their icon buttons. Odd on purpose: inside the 1px border
# that leaves 27px, so icons whose ink is an odd number of pixels across (most of them) center exactly.
CONTROL_SIZE = 29
BUILD_SIZE = 37  # height of the Build button, bigger than the other corner controls; odd for the same reason
BUILD_FONT_SCALE = 1.15  # the Build button's text, relative to the app font
CONTROL_RADIUS = 5  # corner rounding of the corner controls (node text boxes use 3px)
KEEP_VISIBLE = 2 * GRID  # screen px of the graph that panning always leaves on screen
FIT_MARGIN = GRID  # screen px "Zoom to Fit" leaves between the nodes and the window edges
CONTROLS_MARGIN = 12  # gap between the corner controls and the window edge
CONTROL_GROUP_GAP = 8  # extra space between the mode buttons and the zoom buttons

# Cursor modes
EDIT = "edit"  # click, move, connect and type
DRAG = "drag"  # left-drag pans the canvas; nothing in the scene can be clicked

# Edit commands: shortcuts, used by the main window's Edit menu and shown in the right-click menus.
EDIT_SHORTCUTS = {
    "undo": ("Ctrl+Z",),
    "redo": ("Ctrl+Y",),
    "cut": ("Ctrl+X",),
    "copy": ("Ctrl+C",),
    "paste": ("Ctrl+V",),
    "duplicate": ("Ctrl+D",),
    "delete": ("Del", "Backspace"),
    "select_all": ("Ctrl+A",),
}
CLIPBOARD_FORMAT = "application/x-stemgraph-nodes"  # MIME type of copied nodes: Graph.fragment as UTF-8 JSON
BAND_FILL_ALPHA = 38  # selection box fill: the selection colour at about 15% opacity
BAND_SCROLL_MARGIN = GRID  # screen px from the window edge where dragging a selection box starts scrolling
BAND_SCROLL_MAX = 40  # fastest selection-box scrolling, in screen px per tick
BAND_SCROLL_INTERVAL = 16  # ms between selection-box scrolling ticks

# Right-click "add node" menu, with a divider between groups. Input and Output come first; keep every other
# group sorted alphabetically by node title (what the menu shows), not by type key, when adding a node type.
MENU_GROUPS = [
    ["input", "output"],
    ["align", "invert", "mix", "split_mid_side", "subtract"],
]

# Radix Colors dark scales (see docs/design.md)
BACKGROUND = QColor("#191919")   # gray-2
GRID_LINE = QColor("#222222")    # gray-3
NODE_BODY = QColor("#2a2a2a")    # gray-4
NODE_TITLE = QColor("#313131")   # gray-5
NODE_BORDER = QColor("#484848")  # gray-7
WIRE = QColor("#6e6e6e")         # gray-9
TEXT = QColor("#eeeeec")         # sand-12
PLACEHOLDER_TEXT = QColor("#b4b4b4")  # gray-11, low-contrast text
PORT = QColor("#70b8ff")         # blue-11
TARGET_PORT = QColor("#c2e6ff")  # blue-12, a port a wire being dragged can connect to
BUILD_ICON = QColor("#b4b4b4")   # gray-11, the Build button's play icon: a step softer than the text
SELECTED = QColor("#eeeeee")     # gray-12
FIELD_BACKGROUND = "#191919"     # gray-2
FIELD_BORDER = "#3a3a3a"         # gray-6
FIELD_BORDER_ACTIVE = "#606060"  # gray-8
DISABLED_TEXT = "#606060"        # gray-8
ACTIVE_BACKGROUND = "#3a3a3a"    # gray-6, the current cursor mode's button
HOVER_BACKGROUND = "#2a2a2a"     # gray-4

MENU_BAR_BACKGROUND = "#222222"  # gray-3
MENU_BAR_HOVER = "#313131"       # gray-5
MENU_BACKGROUND = "#313131"      # gray-5, lifted off both the canvas and the menu bar
MENU_HOVER = "#3a3a3a"           # gray-6
MENU_SEPARATOR = "#484848"       # gray-7
MENU_HEADING = "#b4b4b4"         # gray-11, muted text

FIELD_STYLE = f"""
QLineEdit, QPushButton, QComboBox {{
    background: {FIELD_BACKGROUND}; color: {TEXT.name()};
    border: 1px solid {FIELD_BORDER}; border-radius: 3px;
    padding: 0 4px; text-align: left;
}}
/* ChoiceField draws its own chevron in the drop-down area. */
QComboBox::drop-down {{ border: none; width: {ICON_SIZE + 4}px; }}
QComboBox::down-arrow {{ image: none; }}
QComboBox QAbstractItemView {{
    background: {MENU_BACKGROUND}; color: {TEXT.name()}; border: none; padding: 4px 0; outline: none;
    selection-background-color: {MENU_HOVER}; selection-color: {TEXT.name()};
}}
/* QLineEdit adds its own ~3px text margin; the padding lines its text up with buttons */
QLineEdit {{ padding: 0 1px; placeholder-text-color: {PLACEHOLDER_TEXT.name()}; }}
QLineEdit:focus, QPushButton:hover, QComboBox:hover, QComboBox:focus {{ border-color: {FIELD_BORDER_ACTIVE}; }}
"""

CONTROLS_STYLE = FIELD_STYLE + f"""
QPushButton {{ text-align: center; padding: 0; border-radius: {CONTROL_RADIUS}px; }}
QPushButton:checked {{ background: {ACTIVE_BACKGROUND}; border-color: {FIELD_BORDER_ACTIVE}; }}
QPushButton:disabled {{ color: {DISABLED_TEXT}; }}

/* Segmented control: the middle segment has no side borders, so neighbours share one divider line.
   Hover tints the background instead of the border, which would otherwise light up only partly. */
QPushButton#segment_first {{ border-top-right-radius: 0; border-bottom-right-radius: 0; }}
QPushButton#segment_middle {{ border-radius: 0; border-left: none; border-right: none; }}
QPushButton#segment_last {{ border-top-left-radius: 0; border-bottom-left-radius: 0; }}
QPushButton#segment_first:hover, QPushButton#segment_middle:hover, QPushButton#segment_last:hover {{
    border-color: {FIELD_BORDER}; background: {HOVER_BACKGROUND};
}}
QPushButton#build {{ padding: 0 14px 0 10px; border-color: {NODE_BORDER.name()}; }}
QPushButton#build:hover {{ border-color: {FIELD_BORDER_ACTIVE}; }}
"""

# Menu bar and all menus (File menu, "add node" menu, text box menus). Applied app-wide in main.py.
# Compact rows (about one grid cell) instead of the platform style's tall ones. Windows 11 rounds menu corners
# itself (made small in main.py).
MENU_STYLE = f"""
QMenuBar {{
    background: {MENU_BAR_BACKGROUND}; color: {TEXT.name()};
    border-bottom: 1px solid {FIELD_BORDER}; padding: 2px;
}}
QMenuBar::item {{ background: transparent; padding: 3px 8px; border-radius: 3px; }}
QMenuBar::item:selected, QMenuBar::item:pressed {{ background: {MENU_BAR_HOVER}; }}

QMenu {{
    background: {MENU_BACKGROUND}; color: {TEXT.name()};
    border: none; padding: 4px 0;
}}
QMenu::item {{ background: transparent; margin: 0 6px; padding: 4px 24px 4px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {MENU_HOVER}; }}
QMenu::item:disabled {{ color: {DISABLED_TEXT}; }}
QMenu::separator {{ height: 1px; background: {MENU_SEPARATOR}; margin: 4px 6px; }}  /* same width as item highlights */
QMenu::right-arrow {{ width: 8px; height: 8px; right: 14px; }}
"""

FIELD_SCROLL_MARGIN = 2 * GRID  # Tab scrolls a field at least this far inside the view

LAST_AUDIO_DIR_KEY = "last_audio_dir"  # QSettings key: folder the file picker last chose from
# Common formats that soundfile (libsndfile) can read, alphabetical; it has no M4A/AAC support.
AUDIO_EXTENSIONS = ("aif", "aiff", "flac", "mp3", "ogg", "opus", "wav")
INPUT_SPACING = (len(NODE_TYPES["input"].fields) + 3) * GRID  # between added Inputs: their height and a cell
AUDIO_FILTER = ";;".join([
    strings.AUDIO_FILES_FILTER.format(patterns=" ".join(f"*.{e}" for e in AUDIO_EXTENSIONS)),
    strings.ALL_FILES_FILTER,
])


def _natural_key(path: str) -> tuple:
    """Sorts file names the way people count: "2 Bass" before "10 Vox"."""
    parts = re.split(r"(\d+)", Path(path).name.casefold())
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in parts), path


def is_audio_file(path: str) -> bool:
    return Path(path).suffix.lower().lstrip(".") in AUDIO_EXTENSIONS and os.path.isfile(path)


def audio_files(paths: list[str]) -> list[str]:
    """The audio files among `paths`, each folder standing for the audio files directly inside it (not in its
    subfolders), in natural name order. Anything else is left out."""
    found = []
    for path in paths:
        if os.path.isdir(path):
            try:
                entries = [os.path.join(path, name) for name in os.listdir(path)]
            except OSError:
                continue
            found += [entry for entry in entries if is_audio_file(entry)]
        elif is_audio_file(path):
            found.append(path)
    unique = {os.path.normcase(os.path.abspath(path)): path for path in found}
    return sorted(unique.values(), key=_natural_key)


def dropped_paths(mime: QMimeData | None) -> list[str]:
    """The local files and folders being dragged, in natural name order."""
    if mime is None or not mime.hasUrls():
        return []
    return sorted((url.toLocalFile() for url in mime.urls() if url.isLocalFile()), key=_natural_key)


def app_settings() -> QSettings:
    """Per-user settings, kept in an INI file rather than the registry.

    On Windows: %APPDATA%\\stemgraph\\stemgraph.ini
    """
    return QSettings(QSettings.IniFormat, QSettings.UserScope, "stemgraph", "stemgraph")


def load_icon(name: str, box: int, color: QColor = TEXT) -> QIcon:
    """An icon from assets/icons on a `box`-sized canvas, in `color` (the SVGs draw in currentColor), or greyed
    out when disabled.

    The glyph is drawn at its native ICON_SIZE so it stays crisp, then shifted by whole pixels so its
    visible ink (not its nominal 15px box, which some glyphs don't fill evenly) is centered on the canvas.
    """
    svg = (ICON_DIR / f"{name}.svg").read_text()
    icon = QIcon()
    for mode, ink in [(QIcon.Normal, color.name()), (QIcon.Disabled, DISABLED_TEXT)]:
        renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", ink).encode()))
        for scale in (1, 2):  # 2x for high-DPI screens
            glyph = QImage(ICON_SIZE * scale, ICON_SIZE * scale, QImage.Format_ARGB32_Premultiplied)
            glyph.fill(Qt.transparent)
            painter = QPainter(glyph)
            renderer.render(painter)
            painter.end()

            ink = _ink_rect(glyph)
            canvas = box * scale
            x = round((canvas - ink.width()) / 2) - ink.left()
            y = round((canvas - ink.height()) / 2) - ink.top()
            pixmap = QPixmap(canvas, canvas)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.drawImage(x, y, glyph)
            painter.end()
            pixmap.setDevicePixelRatio(scale)
            icon.addPixmap(pixmap, mode)
    return icon


def _ink_rect(image: QImage) -> QRect:
    """The bounding box of the clearly visible (not faint anti-aliased) pixels in an image."""
    visible = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 96
    ]
    xs, ys = [x for x, _ in visible], [y for _, y in visible]
    return QRect(QPoint(min(xs), min(ys)), QPoint(max(xs), max(ys)))


def clipboard_fragment() -> tuple[Graph, str] | None:
    """The copied nodes on the clipboard and the id of that copy, or None if it holds no stemgraph nodes."""
    mime = QApplication.clipboard().mimeData()
    if mime is None or not mime.hasFormat(CLIPBOARD_FORMAT):
        return None
    try:
        data = json.loads(bytes(mime.data(CLIPBOARD_FORMAT)).decode("utf-8"))
    except ValueError:  # includes UnicodeDecodeError
        return None
    piece = load_fragment(data)
    return (piece, str(data.get("copy", ""))) if piece else None


class ShiftSelects:
    """For selectable items: Shift+click adds the item to the selection. Qt itself makes a plain click select
    just the item (or, on an already selected item, keep the selection so it can all be dragged) and Ctrl+click
    toggle it."""

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and event.modifiers() & Qt.ShiftModifier:
            self.setSelected(True)
            event.setModifiers(event.modifiers() | Qt.ControlModifier)  # so Qt leaves the rest selected
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        shift = event.button() == Qt.LeftButton and bool(event.modifiers() & Qt.ShiftModifier)
        if shift:
            event.setModifiers(event.modifiers() | Qt.ControlModifier)
        super().mouseReleaseEvent(event)
        if shift:
            self.setSelected(True)  # a Ctrl+click without dragging toggled it off again


def wire_path(start: QPointF, end: QPointF) -> QPainterPath:
    """A horizontal S-curve from an output (start) to an input (end)."""
    bend = max(abs(end.x() - start.x()) / 2, 2 * GRID)
    path = QPainterPath(start)
    path.cubicTo(start + QPointF(bend, 0), end - QPointF(bend, 0), end)
    return path


class PortItem(QGraphicsEllipseItem):
    def __init__(self, node_item: "NodeItem", is_output: bool, index: int) -> None:
        r = PORT_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r, node_item)
        self.node_item = node_item
        self.is_output = is_output
        self.index = index
        self.place()
        self.is_target = False  # a wire being dragged can connect here
        self._lit = 0.0  # how far it's drawn as a target, 0 to 1, while it changes
        self._lighting: QVariantAnimation | None = None  # made the first time it's needed
        self.set_open(False)
        self.setCursor(Qt.CrossCursor)
        # While dragging from this port: a dashed wire from each port being connected (several when dragging
        # the output of one of several selected nodes) to the mouse.
        self._drag_wires: list[tuple[PortItem, QGraphicsPathItem]] = []

    def place(self) -> None:
        """Put the port in its row, below the node's shown fields."""
        self.setPos(NODE_WIDTH if self.is_output else 0, GRID * (self.node_item.first_port_row + self.index + 0.5))

    def set_open(self, open: bool) -> None:
        """Draw the port as a filled dot, or, for the empty input a growing node keeps for adding more, a ring."""
        self.is_open = open
        self._show_target(self._lit)

    def set_target(self, target: bool) -> None:
        """While a wire being dragged can connect to the port, smoothly enlarge it and turn it TARGET_PORT, or
        take it back."""
        if target == self.is_target:
            return
        self.is_target = target
        if self._lighting is None:
            self._lighting = QVariantAnimation()
            self._lighting.setDuration(TARGET_PORT_MS)
            self._lighting.setEasingCurve(QEasingCurve.OutCubic)
            self._lighting.valueChanged.connect(self._show_target)
        self._lighting.stop()
        self._lighting.setStartValue(self._lit)  # from wherever it is, if it was still on its way
        self._lighting.setEndValue(1.0 if target else 0.0)
        self._lighting.start()

    def _show_target(self, lit: float) -> None:
        """Draw the port `lit` of the way (0 to 1) from normal to a connection target."""
        self._lit = lit
        self.setScale(1 + (TARGET_PORT_SCALE - 1) * lit)
        color = QColor.fromRgbF(*(a + (b - a) * lit for a, b in zip(PORT.getRgbF(), TARGET_PORT.getRgbF(),
                                                                       strict=True)))
        if self.is_open:
            self.setBrush(NODE_BODY)
            self.setPen(QPen(color, OPEN_PORT_WIDTH))
        else:
            self.setBrush(color)
            self.setPen(QPen(NODE_BORDER, 1))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        ports = self.scene().dragged_ports(self)
        for port in ports:
            wire = QGraphicsPathItem()
            wire.setPen(QPen(WIRE, 2, Qt.DashLine))
            self.scene().addItem(wire)
            self._drag_wires.append((port, wire))
        self.scene().show_targets(ports)

    def mouseMoveEvent(self, event) -> None:
        for port, wire in self._drag_wires:
            start, end = port.scenePos(), event.scenePos()
            if not self.is_output:
                start, end = end, start
            wire.setPath(wire_path(start, end))

    def mouseReleaseEvent(self, event) -> None:
        if not self._drag_wires:
            return
        scene = self.scene()
        ports = [port for port, _ in self._drag_wires]
        for _, wire in self._drag_wires:
            scene.removeItem(wire)
        self._drag_wires = []
        scene.show_targets([])
        for item in scene.items(event.scenePos()):
            if isinstance(item, PortItem):
                if len(ports) == 1:
                    scene.connect_ports(self, item)
                else:
                    scene.connect_many(ports, item)
                break


FIELD_CAPTIONS = {
    "name": strings.NAME_CAPTION,
    "algorithm": strings.ALGORITHM_CAPTION,
    "channels": strings.CHANNELS_CAPTION,
    "alignment": strings.ALGORITHM_CAPTION,
    "polarity": strings.POLARITY_CAPTION,
}
TOGGLE_LABELS = {"align": (strings.ALIGN_FIRST, strings.ALIGN_FIRST_TIP)}  # checkbox fields: label, hover text
CHECK_BOX_SIZE = GRID - 8
OPEN_POPUP_Z = 10  # stacking level of a node with an open dropdown, and of that dropdown's field


class ChoiceField(QComboBox):
    """A dropdown node field. The platform style's arrow is hidden (see FIELD_STYLE); this draws a Radix chevron.

    An item can have a shorter label for the closed box (SHORT_LABEL_ROLE), so the opened list can say more:
    "Auto (Paulus–Torcoli)" in the list, "Auto" on the node.
    """

    SHORT_LABEL_ROLE = Qt.UserRole + 1
    _chevrons: dict[int, QIcon] = {}  # by box size, shared by every dropdown

    # Qt embeds the opened list in the scene as a child of the field, so ports and other nodes would draw over it.
    # While it's open, lift the field above its node's ports and the node above other nodes.
    def showPopup(self) -> None:
        self._lift(OPEN_POPUP_Z)
        super().showPopup()

    def hidePopup(self) -> None:
        super().hidePopup()
        self._lift(0)

    def _lift(self, z: float) -> None:
        field = self.graphicsProxyWidget()
        if field:
            field.setZValue(z)
            if field.parentItem():
                field.parentItem().setZValue(z)

    def paintEvent(self, event) -> None:
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        short = self.currentData(self.SHORT_LABEL_ROLE)
        if short:
            option.currentText = short
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)
        box = self.height()
        if box not in self._chevrons:
            self._chevrons[box] = load_icon("chevron-down", box)
        mode = QIcon.Normal if self.isEnabled() else QIcon.Disabled
        self._chevrons[box].paint(painter, QRect(self.width() - box, 0, box, box), Qt.AlignCenter, mode)
        painter.end()


class TextField(QLineEdit):
    """A text node field that shows its whole text on hover when the box is too narrow for it, or while it's
    empty, its greyed-out placeholder."""

    def event(self, event) -> bool:
        if event.type() == QEvent.ToolTip:
            text = self.text() or self.placeholderText()
            # The border, the style sheet's padding and QLineEdit's own text margin take ~5px each side.
            if self.fontMetrics().horizontalAdvance(text) > self.width() - 10:
                QToolTip.showText(event.globalPos(), text, self)
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)


class CheckField(QCheckBox):
    """A checkbox node field, drawn to match the text boxes: a box with a Radix check in it, then the label, which
    starts where other fields' captions do. Clicking anywhere on the row toggles it."""

    _check: QIcon | None = None  # shared by every checkbox

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setAttribute(Qt.WA_Hover)  # repaint the border on hover

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:
        if CheckField._check is None:
            CheckField._check = load_icon("check", CHECK_BOX_SIZE)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        box = QRect(0, (self.height() - CHECK_BOX_SIZE) // 2, CHECK_BOX_SIZE, CHECK_BOX_SIZE)
        lit = self.underMouse() or self.hasFocus()
        painter.setPen(QPen(QColor(FIELD_BORDER_ACTIVE if lit else FIELD_BORDER), 1))
        painter.setBrush(QColor(FIELD_BACKGROUND))
        painter.drawRoundedRect(QRectF(box).adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        if self.isChecked():
            CheckField._check.paint(painter, box, Qt.AlignCenter)
        painter.setPen(TEXT)
        label = QRect(CHECK_BOX_SIZE + CAPTION_GAP, 0, self.width(), self.height())
        painter.drawText(label, Qt.AlignLeft | Qt.AlignVCenter, self.text())
        painter.end()


class SignItem(QGraphicsItem):
    """The + / − switch on a connected input of a growing node: two halves side by side, the input's sign lit and
    the other greyed out. Clicking a half chooses it."""

    def __init__(self, node_item: "NodeItem", index: int) -> None:
        super().__init__(node_item)
        self.node_item = node_item
        self.index = index
        self.rect = QRectF(0, 0, 2 * SIGN_SIZE, SIGN_SIZE)
        self.place()
        self.setAcceptHoverEvents(True)
        self._hovered: bool | None = None  # the half under the mouse: True for −, False for +, None for neither

    def place(self) -> None:
        """Put the switch in its input's row."""
        self.setPos(SIGN_LEFT, GRID * (self.node_item.first_port_row + self.index) + (GRID - SIGN_SIZE) / 2)

    def subtracts(self) -> bool:
        return self.node_item.node.subtracts(self.index)

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-1, -1, 1, 1)

    @staticmethod
    def _half(minus: bool) -> QRectF:
        return QRectF(SIGN_SIZE if minus else 0, 0, SIGN_SIZE, SIGN_SIZE)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        outline = self.rect.adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(FIELD_BORDER), 1))
        painter.setBrush(QColor(FIELD_BACKGROUND))
        painter.drawRoundedRect(outline, 3, 3)
        # The chosen half is raised, like the canvas controls' current cursor mode.
        painter.save()
        painter.setClipRect(self._half(self.subtracts()))
        painter.setPen(QPen(QColor(FIELD_BORDER_ACTIVE), 1))
        painter.setBrush(QColor(ACTIVE_BACKGROUND))
        painter.drawRoundedRect(outline, 3, 3)
        painter.restore()
        for minus in (False, True):
            chosen = minus == self.subtracts()
            color = TEXT if chosen else QColor(PLACEHOLDER_TEXT if self._hovered == minus else DISABLED_TEXT)
            # Drawn rather than typed, so + and − are the same size and both sit exactly in the middle.
            painter.setPen(QPen(color, 1.5))
            middle, arm = self._half(minus).center(), SIGN_SIZE / 4
            painter.drawLine(middle - QPointF(arm, 0), middle + QPointF(arm, 0))
            if not minus:
                painter.drawLine(middle - QPointF(0, arm), middle + QPointF(0, arm))

    def _hover(self, pos: QPointF | None) -> None:
        half = None if pos is None or not self.rect.contains(pos) else pos.x() >= SIGN_SIZE
        if half != self._hovered:
            self._hovered = half
            chosen = half == self.subtracts()
            self.setCursor(Qt.ArrowCursor if half is None or chosen else Qt.PointingHandCursor)
            self.setToolTip("" if half is None else strings.SUBTRACT_TIP if half else strings.ADD_TIP)
            self.update()

    def hoverMoveEvent(self, event) -> None:
        self._hover(event.pos())

    def hoverLeaveEvent(self, event) -> None:
        self._hover(None)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            event.ignore()  # a right-click opens the node's menu

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect.contains(event.pos()):
            minus = event.pos().x() >= SIGN_SIZE
            if minus != self.subtracts():
                self.scene().set_subtracts(self.node_item.node.id, self.index, minus)
                self._hovered = None  # the half under the mouse is chosen now: refresh its cursor
                self._hover(event.pos())


class NodeItem(ShiftSelects, QGraphicsItem):
    def __init__(self, node: Node, input_count: int, signs: int) -> None:
        super().__init__()
        self.node = node
        self.rect = QRectF()
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setPos(node.x, node.y)
        self.drop_target = False
        self.field_items: dict[str, QGraphicsProxyWidget] = {}  # every field, shown or not
        for name in node.type.fields:
            self._add_field(name)
        self._place_fields()
        self.inputs: list[PortItem] = []
        self.signs: list[SignItem] = []  # one per connected input of a growing node
        self.outputs = [PortItem(self, True, i) for i in range(len(node.type.outputs))]
        self.set_inputs(input_count, signs)

    def _place_fields(self) -> None:
        """Rows, one grid cell each: title, then one per shown field, then the ports. The fields of an unchecked
        checkbox are hidden."""
        shown = self.node.shown_fields()
        self.fields: list[QGraphicsProxyWidget] = []  # the shown ones, top to bottom
        for name, proxy in self.field_items.items():
            proxy.setVisible(name in shown)
            if name in shown:
                proxy.setPos(proxy.x(), GRID * (1 + shown.index(name)) + 2)
                self.fields.append(proxy)
        self.first_port_row = 1 + len(shown)

    def update_layout(self) -> None:
        """Show the fields that should be shown now, moving the ports below them and resizing the node."""
        self._place_fields()
        for item in [*self.inputs, *self.outputs, *self.signs]:
            item.place()
        self.set_inputs(len(self.inputs), len(self.signs))

    def set_inputs(self, count: int, signs: int) -> None:
        """Show `count` inputs (they change for growing nodes), and signs on the first `signs` of them."""
        while len(self.inputs) > count:
            self._remove_child(self.inputs.pop())
        self.inputs += [PortItem(self, False, i) for i in range(len(self.inputs), count)]
        for i, port in enumerate(self.inputs):
            port.set_open(self.node.type.growing and i == count - 1)
        rect = QRectF(0, 0, NODE_WIDTH, GRID * (self.first_port_row + max(count, len(self.outputs))))
        if rect != self.rect:
            self.prepareGeometryChange()
            self.rect = rect
        while len(self.signs) > signs:
            self._remove_child(self.signs.pop())
        self.signs += [SignItem(self, i) for i in range(len(self.signs), signs)]
        for sign in self.signs:
            sign.update()
        self.update()

    def _remove_child(self, item: QGraphicsItem) -> None:
        if item.scene():
            item.scene().removeItem(item)
        else:
            item.setParentItem(None)

    def _add_field(self, name: str) -> None:
        if name == "name":
            widget = self._name_field()
        elif name in CHOICES:
            widget = self._choice_field(name)
        elif name in TOGGLES:
            widget = self._check_field(name)
        else:
            widget = self._file_field()
        # Captioned fields sit to the right of their caption ("Name:"). A checkbox starts where captions do.
        caption = FIELD_CAPTIONS.get(name)
        left = self._box_left(caption) if caption else 8 if name in TOGGLES else 6
        widget.setStyleSheet(FIELD_STYLE)
        # Embedded widgets are drawn over their window background colour; without this, the square behind the
        # rounded corners shows as dark specks against the node body.
        widget.setAttribute(Qt.WA_TranslucentBackground)
        widget.setFixedSize(NODE_WIDTH - left - 6, GRID - 4)
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(widget)
        proxy.setPos(left, 0)  # _place_fields puts it in its row
        self.field_items[name] = proxy

    @staticmethod
    def _box_left(caption: str) -> int:
        return 8 + QFontMetrics(QApplication.font()).horizontalAdvance(caption) + CAPTION_GAP

    def _name_field(self) -> QWidget:
        field = TextField(self.node.values.get("name", ""))
        field.textChanged.connect(lambda text: self.scene().set_value(self.node.id, "name", text))
        field.editingFinished.connect(lambda: self.scene() and self.scene().commit())  # typing is one undo step
        self.name_field = field
        return field

    def show_default_name(self, name: str) -> None:
        """Show `name` greyed out in the empty Name box: what the node is called while the box is blank."""
        self.name_field.setPlaceholderText(name)

    def _choice_field(self, name: str) -> QWidget:
        field = ChoiceField()
        labels = {value: label for value, label, _ in CHOICES[name]}
        for value, label, tip in CHOICES[name]:
            if value == AUTO and name in AUTO_CHOICE:
                field.addItem(strings.AUTO_LIST_LABEL.format(choice=labels[AUTO_CHOICE[name]]), value)
                field.setItemData(field.count() - 1, label, ChoiceField.SHORT_LABEL_ROLE)
            else:
                field.addItem(label, value)
            field.setItemData(field.count() - 1, tip, Qt.ToolTipRole)
        # The opened list may be wider than the box, so longer list labels aren't cut off.
        field.view().setMinimumWidth(field.view().sizeHintForColumn(0) + 2 * GRID)
        field.setCurrentIndex(max(field.findData(self.node.values.get(name, "")), 0))
        field.currentIndexChanged.connect(
            lambda index: self.scene().set_value(self.node.id, name, field.itemData(index))
        )
        return field

    def _check_field(self, name: str) -> QWidget:
        label, tip = TOGGLE_LABELS[name]
        field = CheckField(label)
        field.setToolTip(tip)
        field.setChecked(self.node.is_on(name))
        field.toggled.connect(lambda checked: self.scene().set_value(self.node.id, name, "" if checked else OFF))
        return field

    def _file_field(self) -> QWidget:
        button = QPushButton()
        self._show_file(button, self.node.values.get("file"))
        button.clicked.connect(lambda: self._choose_file(button))
        self.file_button = button
        return button

    def show_file(self, path: str) -> None:
        self._show_file(self.file_button, path)

    def set_drop_target(self, target: bool) -> None:
        """Light up the outline while a file dragged over the node would become its file."""
        if target != self.drop_target:
            self.drop_target = target
            self.update()

    def _choose_file(self, button: QPushButton) -> None:
        window = self.scene().views()[0]
        settings = app_settings()
        start_dir = settings.value(LAST_AUDIO_DIR_KEY, "")
        path, _ = QFileDialog.getOpenFileName(window, strings.CHOOSE_AUDIO_TITLE, start_dir, AUDIO_FILTER)
        if path:
            settings.setValue(LAST_AUDIO_DIR_KEY, str(Path(path).parent))
            self.scene().set_value(self.node.id, "file", path)
            self._show_file(button, path)

    @staticmethod
    def _show_file(button: QPushButton, path: str | None) -> None:
        if path:
            text = button.fontMetrics().elidedText(Path(path).name, Qt.ElideMiddle, NODE_WIDTH - 24)
            button.setText(text)
            button.setToolTip(path)
        else:
            button.setText(strings.CHOOSE_FILE)

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-1, -1, 1, 1)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        title = QRectF(0, 0, NODE_WIDTH, GRID)

        painter.setPen(Qt.NoPen)
        painter.setBrush(NODE_BODY)
        painter.drawRoundedRect(self.rect, 4, 4)
        painter.save()
        painter.setClipRect(title)
        painter.setBrush(NODE_TITLE)
        painter.drawRoundedRect(self.rect, 4, 4)
        painter.restore()

        outline = PORT if self.drop_target else SELECTED if self.isSelected() else NODE_BORDER
        painter.setPen(QPen(outline, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.rect, 4, 4)

        painter.setPen(TEXT)
        painter.drawText(title.adjusted(8, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, self.node.type.title)
        for row, name in enumerate(self.node.shown_fields(), start=1):
            if name in FIELD_CAPTIONS:
                caption = QRectF(8, GRID * row, NODE_WIDTH, GRID)
                painter.drawText(caption, Qt.AlignLeft | Qt.AlignVCenter, FIELD_CAPTIONS[name])
        half = NODE_WIDTH / 2 - 10
        top = self.first_port_row
        # A growing node's labels all leave room for the sign, so they line up whether or not it's there.
        left = SIGN_LEFT + 2 * SIGN_SIZE + SIGN_GAP if self.node.type.growing else 10
        for i, port in enumerate(self.inputs):
            name = self.node.type.inputs[0 if self.node.type.growing else i]
            label = QRectF(left, GRID * (top + i), half, GRID)
            if port.is_open:  # greyed out, like a blank Name box's default: what connecting here does
                painter.setPen(PLACEHOLDER_TEXT)
                painter.drawText(label, Qt.AlignLeft | Qt.AlignVCenter, strings.ADD_INPUT)
                painter.setPen(TEXT)
            else:
                painter.drawText(label, Qt.AlignLeft | Qt.AlignVCenter, name)
        for i, name in enumerate(self.node.type.outputs):
            label = QRectF(NODE_WIDTH / 2, GRID * (top + i), half, GRID)
            painter.drawText(label, Qt.AlignRight | Qt.AlignVCenter, name)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            return QPointF(snap(value.x()), snap(value.y()))
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.scene().node_moved(self)
        return super().itemChange(change, value)


class WireItem(ShiftSelects, QGraphicsPathItem):
    def __init__(self, connection: Connection, src: PortItem, dst: PortItem) -> None:
        super().__init__()
        self.connection = connection
        self.src = src
        self.dst = dst
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setZValue(-1)
        self.update_path()

    def update_path(self) -> None:
        self.setPath(wire_path(self.src.scenePos(), self.dst.scenePos()))

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(10)
        return stroker.createStroke(self.path())

    def boundingRect(self) -> QRectF:
        return self.shape().boundingRect()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setPen(QPen(SELECTED if self.isSelected() else WIRE, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())


class EditorScene(QGraphicsScene):
    """The graph's items, and the edits made to them: undo history, clipboard and right-click menus.

    Each finished edit calls `commit`, which records everything changed since the previous commit as one undo step.
    """

    nodes_changed = Signal()  # a node was added, moved or removed
    edited = Signal()  # the user changed the graph (it may have changed back to how it was)
    history_changed = Signal()  # an undo step was added, undone or redone
    reveal = Signal(QRectF)  # undo or redo changed this area; show it if it's off-screen
    files_chosen = Signal(list, QPointF)  # Add Inputs… chose these files, to add at this scene point

    # The clipboard copy pasted last and how many times, so each paste of it lands one grid cell further on.
    _pasted: tuple[str, int] = ("", 0)

    def __init__(self, graph: Graph) -> None:
        super().__init__()
        self.graph = graph
        self.node_items: dict[int, NodeItem] = {}
        self.wire_items: dict[Connection, WireItem] = {}
        self._undo: list[tuple] = []  # graph states, oldest first
        self._redo: list[tuple] = []  # graph states, the next to redo last
        self._committed = graph.state()  # the state at the last commit
        for node in graph.nodes.values():
            self._add_item(node)
        self.sync_wires()
        self.edited.connect(self.update_default_names)
        self.update_default_names()

    def update_default_names(self) -> None:
        """Refresh what blank Name boxes show. An Input's depends on its file; an Output's on its wiring, the
        names upstream, and the other Outputs."""
        for node in self.graph.nodes.values():
            if node.type_key == "input":
                self.node_items[node.id].show_default_name(build.input_name(node))
        for node_id, name in build.output_names(self.graph).items():
            self.node_items[node_id].show_default_name(name)

    def nodes_rect(self) -> QRectF:
        """The area covered by all nodes, or the origin if there are none."""
        rect = QRectF(0, 0, 0, 0)
        for i, item in enumerate(self.node_items.values()):
            rect = item.sceneBoundingRect() if i == 0 else rect.united(item.sceneBoundingRect())
        return rect

    @staticmethod
    def hint_rect() -> QRectF:
        """Where an empty canvas shows how to get started: centered on the origin."""
        size = QFontMetrics(QApplication.font()).boundingRect(QRect(), Qt.AlignCenter, strings.EMPTY_HINT).size()
        rect = QRectF(0, 0, size.width(), size.height())
        rect.moveCenter(QPointF(0, 0))
        return rect

    def content_rect(self) -> QRectF:
        """What panning keeps in reach and Zoom to Fit shows: the nodes, or the empty canvas's hint."""
        return self.nodes_rect() if self.node_items else self.hint_rect()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, BACKGROUND)
        painter.setPen(QPen(GRID_LINE, 0))
        left = int(rect.left()) - int(rect.left()) % GRID
        top = int(rect.top()) - int(rect.top()) % GRID
        lines = [QLineF(x, rect.top(), x, rect.bottom()) for x in range(left, int(rect.right()) + 1, GRID)]
        lines += [QLineF(rect.left(), y, rect.right(), y) for y in range(top, int(rect.bottom()) + 1, GRID)]
        painter.drawLines(lines)
        if not self.node_items:
            painter.setPen(PLACEHOLDER_TEXT)
            painter.setFont(QApplication.font())
            painter.drawText(self.hint_rect(), Qt.AlignCenter, strings.EMPTY_HINT)

    def contextMenuEvent(self, event) -> None:
        pos = event.scenePos()
        item = self.itemAt(pos, QTransform())
        if isinstance(item, QGraphicsProxyWidget):
            super().contextMenuEvent(event)  # a text box's own copy/paste menu
            return
        if item is None:
            menu = self.canvas_menu(pos)
            chosen = menu.exec(event.screenPos())  # also returns what was chosen in the Add Node submenu
            if chosen and chosen.data():
                self.add_node(chosen.data(), pos)
            return
        menu = QMenu()
        clicked = item.topLevelItem()  # a port belongs to its node
        if not clicked.isSelected():
            self.clearSelection()
            clicked.setSelected(True)
        nodes = self.has_selected_nodes()
        self._menu_action(menu, strings.MENU_CUT, "cut", self.cut, nodes)
        self._menu_action(menu, strings.MENU_COPY, "copy", self.copy, nodes)
        self._menu_action(menu, strings.MENU_DUPLICATE, "duplicate", self.duplicate, nodes)
        self._menu_action(menu, strings.MENU_DELETE, "delete", self.delete_selected, True)
        menu.exec(event.screenPos())

    def canvas_menu(self, pos: QPointF) -> QMenu:
        """The right-click menu for empty canvas at scene point `pos`. Its Add Node submenu's actions hold the node
        type to add as their data."""
        menu = QMenu()
        menu.addAction(strings.MENU_ADD_INPUTS).triggered.connect(lambda: self._choose_inputs(pos))
        nodes = menu.addMenu(strings.MENU_ADD_NODE)
        for i, group in enumerate(MENU_GROUPS):
            if i:
                nodes.addSeparator()
            for key in group:
                nodes.addAction(NODE_TYPES[key].title).setData(key)
        menu.addSeparator()
        self._menu_action(menu, strings.MENU_PASTE, "paste", lambda: self.paste(pos), self.can_paste())
        return menu

    @staticmethod
    def _menu_action(menu: QMenu, text: str, command: str, slot, enabled: bool) -> None:
        action = QAction(text, menu)
        action.setShortcut(QKeySequence(EDIT_SHORTCUTS[command][0]))  # for show: the Edit menu's actions do the work
        action.setShortcutContext(Qt.WidgetShortcut)
        action.setEnabled(enabled)
        action.triggered.connect(slot)
        menu.addAction(action)

    def fields_in_order(self) -> list[QGraphicsProxyWidget]:
        """Every node's fields in reading order: nodes top to bottom then left to right, fields top to bottom."""
        items = sorted(self.node_items.values(), key=lambda item: (item.y(), item.x(), item.node.id))
        return [field for item in items for field in item.fields]

    def focus_next_field(self, next: bool) -> bool:
        """Move focus to the next (or previous) field in reading order, wrapping around, and scroll it into view.
        From outside the fields, start at the first (or last). Returns False if there are no fields."""
        fields = self.fields_in_order()
        if not fields:
            return False
        current = self.focusItem()
        if current in fields:
            index = (fields.index(current) + (1 if next else -1)) % len(fields)
        else:
            index = 0 if next else len(fields) - 1
        field = fields[index]
        field.setFocus(Qt.TabFocusReason if next else Qt.BacktabFocusReason)
        for view in self.views():
            view.ensureVisible(field, FIELD_SCROLL_MARGIN, FIELD_SCROLL_MARGIN)
        return True

    def focusNextPrevChild(self, next: bool) -> bool:
        return self.focus_next_field(next)

    def typing(self) -> bool:
        return isinstance(self.focusItem(), QGraphicsProxyWidget)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and not self.typing():
            self.clearSelection()
        else:
            super().keyPressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if not self.typing():
            self.commit()  # the end of dragging nodes

    def add_node(self, type_key: str, pos: QPointF) -> None:
        self._add_item(self.graph.add_node(type_key, pos.x(), pos.y()))
        self.nodes_changed.emit()
        self.edited.emit()
        self.commit()

    def _choose_inputs(self, pos: QPointF) -> None:
        settings = app_settings()
        window = self.views()[0]
        paths, _ = QFileDialog.getOpenFileNames(
            window, strings.CHOOSE_AUDIO_FILES_TITLE, settings.value(LAST_AUDIO_DIR_KEY, ""), AUDIO_FILTER)
        if paths:
            settings.setValue(LAST_AUDIO_DIR_KEY, str(Path(paths[0]).parent))
            self.files_chosen.emit(paths, pos)

    def add_inputs(self, paths: list[str], pos: QPointF) -> None:
        """Add an Input for each file, in a column with its top-left corner at `pos`, and select them. One undo
        step."""
        self.clearSelection()
        for i, path in enumerate(paths):
            node = self.graph.add_node("input", pos.x(), pos.y() + i * INPUT_SPACING)
            self.graph.set_value(node.id, "file", path)
            self._add_item(node)
            self.node_items[node.id].setSelected(True)
        self.nodes_changed.emit()
        self.edited.emit()
        self.commit()

    def input_at(self, pos: QPointF) -> int | None:
        """The id of the Input node at a scene point, if there is one."""
        for item in self.items(pos):
            node_item = item.topLevelItem()
            if isinstance(node_item, NodeItem):
                return node_item.node.id if node_item.node.type_key == "input" else None
        return None

    def set_input_file(self, node_id: int, path: str) -> None:
        self.set_value(node_id, "file", path)
        self.node_items[node_id].show_file(path)

    def show_drop_target(self, node_id: int | None) -> None:
        """Light up the Input a dragged file would go into (or none)."""
        for item in self.node_items.values():
            item.set_drop_target(item.node.id == node_id)

    def _add_item(self, node: Node) -> None:
        item = NodeItem(node, *self._inputs(node.id))
        self.addItem(item)
        self.node_items[node.id] = item

    def _inputs(self, node_id: int) -> tuple[int, int]:
        """How many inputs a node shows, and how many of them have signs: a growing node's connected ones."""
        growing = self.graph.nodes[node_id].type.growing
        return self.graph.input_count(node_id), len(self.graph.sources(node_id)) if growing else 0

    def set_value(self, node_id: int, name: str, value: str) -> None:
        self.graph.set_value(node_id, name, value)
        if name in TOGGLES:  # it shows or hides other fields
            self.node_items[node_id].update_layout()
            self._update_wires(node_id)
            self.nodes_changed.emit()
        self.edited.emit()
        if name != "name":  # typing a name is committed when the box is left
            self.commit()

    def set_subtracts(self, node_id: int, index: int, subtracts: bool) -> None:
        """Make a growing node's input subtract (or add)."""
        self.graph.set_subtracts(node_id, index, subtracts)
        self.node_items[node_id].set_inputs(*self._inputs(node_id))
        self.edited.emit()
        self.commit()

    def node_moved(self, item: NodeItem) -> None:
        node_id = item.node.id
        self.graph.move_node(node_id, item.x(), item.y())
        self._update_wires(node_id)
        self.nodes_changed.emit()

    def _update_wires(self, node_id: int) -> None:
        """Redraw the wires to and from a node, after it moved or its ports did."""
        for wire in self.wire_items.values():
            if node_id in (wire.connection.src, wire.connection.dst):
                wire.update_path()
        self.edited.emit()

    def dragged_ports(self, port: PortItem) -> list[PortItem]:
        """The ports a wire dragged from `port` connects: dragging an output of one of several selected nodes
        drags that output of each of them, top to bottom; otherwise just `port`."""
        item = port.node_item
        if not (port.is_output and item.isSelected()):
            return [port]
        items = [i for i in self.selectedItems() if isinstance(i, NodeItem) and port.index < len(i.outputs)]
        items.sort(key=lambda i: (i.node.y, i.node.x, i.node.id))
        return [i.outputs[port.index] for i in items] if len(items) > 1 else [port]

    def show_targets(self, ports: list[PortItem]) -> None:
        """While wires are dragged from `ports`: enlarge the ports they can connect to, and dim the nodes they
        can't (other than the ones being dragged from). With no ports, put everything back."""
        sources = {port.node_item for port in ports}
        for item in self.node_items.values():
            ends = (item.outputs if not ports[0].is_output else item.inputs) if ports else []
            targets = [end for end in ends if self._can_join(ports, end)]
            for port in item.inputs + item.outputs:
                port.set_target(port in targets)
            item.setOpacity(1 if not ports or targets or item in sources else DIMMED_OPACITY)

    def _can_join(self, ports: list[PortItem], end: PortItem) -> bool:
        """Whether wires dragged from `ports` can be dropped on `end`: see connect_ports and connect_many."""
        if len(ports) > 1:
            node_id = end.node_item.node.id
            return any(self.graph.can_add_source(p.node_item.node.id, p.index, node_id) for p in ports)
        out, inp = (ports[0], end) if ports[0].is_output else (end, ports[0])
        return self.graph.can_connect(out.node_item.node.id, out.index, inp.node_item.node.id, inp.index)

    def connect_many(self, outputs: list[PortItem], target: PortItem) -> None:
        """Connect several outputs to a node whose inputs grow, as new inputs in order. Outputs already wired
        into it are skipped. Onto any other port, nothing is connected."""
        node = target.node_item.node
        if target.is_output or not node.type.growing:
            return
        for port in outputs:
            self.graph.add_source(port.node_item.node.id, port.index, node.id)
        self.sync_wires()
        self.edited.emit()
        self.commit()

    def connect_ports(self, a: PortItem, b: PortItem) -> None:
        if a.is_output == b.is_output:
            return
        out, inp = (a, b) if a.is_output else (b, a)
        self.graph.connect(out.node_item.node.id, out.index, inp.node_item.node.id, inp.index)
        self.sync_wires()
        self.edited.emit()
        self.commit()

    def delete_selected(self) -> None:
        for item in self.selectedItems():
            if isinstance(item, WireItem):
                self.graph.disconnect(item.connection)
            elif isinstance(item, NodeItem):
                self.graph.remove_node(item.node.id)
                del self.node_items[item.node.id]
                self.removeItem(item)
        self.sync_wires()
        self.nodes_changed.emit()
        self.edited.emit()
        self.commit()

    def select_all(self) -> None:
        for item in [*self.node_items.values(), *self.wire_items.values()]:
            item.setSelected(True)

    def has_selected_nodes(self) -> bool:
        return any(isinstance(item, NodeItem) for item in self.selectedItems())

    def _selected_ids(self) -> list[int]:
        return [item.node.id for item in self.selectedItems() if isinstance(item, NodeItem)]

    # --- Clipboard ---

    def copy(self) -> None:
        """Put the selected nodes, and the wires between them, on the clipboard."""
        ids = self._selected_ids()
        if not ids:
            return
        data = self.graph.fragment(ids)
        data["copy"] = uuid.uuid4().hex
        mime = QMimeData()
        mime.setData(CLIPBOARD_FORMAT, QByteArray(json.dumps(data, ensure_ascii=False).encode("utf-8")))
        QApplication.clipboard().setMimeData(mime)

    def cut(self) -> None:
        if self.has_selected_nodes():
            self.copy()
            self.delete_selected()

    def can_paste(self) -> bool:
        return clipboard_fragment() is not None

    def paste(self, pos: QPointF | None = None) -> None:
        """Paste the copied nodes with their top-left corner at `pos`. With no `pos`, one grid cell further on from
        where they were copied than the last paste of them."""
        found = clipboard_fragment()
        if not found:
            return
        piece, copy_id = found
        if pos is None:
            last_id, count = EditorScene._pasted
            count = count + 1 if last_id == copy_id else 1
            EditorScene._pasted = (copy_id, count)
            x, y = self._corner(piece)
            pos = QPointF(x + count * GRID, y + count * GRID)
        self._add_piece(piece, pos)

    def duplicate(self) -> None:
        """Copy the selected nodes, and the wires between them, one grid cell down and right of them."""
        ids = self._selected_ids()
        if ids:
            piece = load_fragment(self.graph.fragment(ids))
            x, y = self._corner(piece)
            self._add_piece(piece, QPointF(x + GRID, y + GRID))

    @staticmethod
    def _corner(piece: Graph) -> tuple[int, int]:
        """The top-left corner of a piece's nodes."""
        return min(n.x for n in piece.nodes.values()), min(n.y for n in piece.nodes.values())

    def _add_piece(self, piece: Graph, pos: QPointF) -> None:
        """Add copies of `piece`'s nodes and wires with their top-left corner at `pos`, and select them."""
        ids = set(self.graph.paste(piece, pos.x(), pos.y()))
        for node_id in ids:
            self._add_item(self.graph.nodes[node_id])
        self.sync_wires()
        self.clearSelection()
        for node_id in ids:
            self.node_items[node_id].setSelected(True)
        for connection, wire in self.wire_items.items():
            if connection.src in ids and connection.dst in ids:
                wire.setSelected(True)
        self.nodes_changed.emit()
        self.edited.emit()
        self.commit()

    # --- Undo ---

    def commit(self) -> None:
        """End the current undo step: everything changed since the last commit becomes one step."""
        state = self.graph.state()
        if state != self._committed:
            self._undo.append(self._committed)
            self._redo.clear()
            self._committed = state
            self.history_changed.emit()

    def can_undo(self) -> bool:
        return bool(self._undo) or self.graph.state() != self._committed

    def can_redo(self) -> bool:
        return bool(self._redo) and self.graph.state() == self._committed

    def undo(self) -> None:
        self.commit()
        if self._undo:
            self._redo.append(self._committed)
            self._go_to(self._undo.pop())

    def redo(self) -> None:
        self.commit()
        if self._redo:
            self._undo.append(self._committed)
            self._go_to(self._redo.pop())

    def _go_to(self, state: tuple) -> None:
        """Put the graph in an earlier or later state, then select and show what that changed."""
        before = self._committed
        self._committed = state
        self.graph.set_state(state)
        for item in [*self.node_items.values(), *self.wire_items.values()]:
            self.removeItem(item)
        self.node_items.clear()
        self.wire_items.clear()
        for node in self.graph.nodes.values():
            self._add_item(node)
        self.sync_wires()

        old_nodes, old_wires = set(before[0]), set(before[1])
        changed = [self.node_items[n[0]] for n in state[0] if n not in old_nodes]
        changed += [self.wire_items[Connection(*c)] for c in state[1] if c not in old_wires]
        for item in changed:
            item.setSelected(True)
        self.nodes_changed.emit()
        self.edited.emit()
        self.history_changed.emit()
        if changed:
            area = changed[0].sceneBoundingRect()
            for item in changed[1:]:
                area = area.united(item.sceneBoundingRect())
            self.reveal.emit(area)

    def sync_wires(self) -> None:
        """Make the wire items, and the inputs of growing nodes, match the model's connections."""
        for connection in list(self.wire_items):
            if connection not in self.graph.connections:
                self.removeItem(self.wire_items.pop(connection))
        for node_id, item in self.node_items.items():
            if item.node.type.growing:
                item.set_inputs(*self._inputs(node_id))
        for connection in self.graph.connections:
            if connection not in self.wire_items:
                src = self.node_items[connection.src].outputs[connection.src_output]
                dst = self.node_items[connection.dst].inputs[connection.dst_input]
                wire = WireItem(connection, src, dst)
                self.addItem(wire)
                self.wire_items[connection] = wire


class CanvasControls(QWidget):
    """The "[Edit][Drag]  [−] 100% [+]" controls in the bottom-right corner of the canvas."""

    def __init__(self, view: "EditorView") -> None:
        super().__init__(view)
        self.edit_mode = self._button("cursor-arrow", strings.EDIT_MODE_TIP, lambda: view.set_mode(EDIT))
        self.drag_mode = self._button("hand", strings.DRAG_MODE_TIP, lambda: view.set_mode(DRAG))
        self.zoom_out = self._button("zoom-out", strings.ZOOM_OUT_TIP, view.zoom_out)
        self.reset = self._button(None, strings.RESET_ZOOM_TIP, view.reset_zoom, width=2 * CONTROL_SIZE)
        self.reset.setText(strings.ZOOM_PERCENT.format(percent=100))
        self.zoom_in = self._button("zoom-in", strings.ZOOM_IN_TIP, view.zoom_in)
        for button in (self.edit_mode, self.drag_mode):
            button.setCheckable(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.edit_mode)
        layout.addWidget(self.drag_mode)
        layout.addSpacing(CONTROL_GROUP_GAP)

        # Zoom buttons form one segmented control: no gaps, single dividers, rounded outer corners only.
        zoom = QHBoxLayout()
        zoom.setSpacing(0)
        for button, segment in [(self.zoom_out, "first"), (self.reset, "middle"), (self.zoom_in, "last")]:
            button.setObjectName(f"segment_{segment}")
            zoom.addWidget(button)
        layout.addLayout(zoom)
        self.setStyleSheet(CONTROLS_STYLE)
        self.adjustSize()

    @staticmethod
    def _button(icon: str | None, tooltip: str, action, width: int = CONTROL_SIZE) -> QPushButton:
        button = QPushButton()
        if icon:
            box = CONTROL_SIZE - 2  # inside the 1px border
            button.setIcon(load_icon(icon, box))
            button.setIconSize(QSize(box, box))
        button.setToolTip(tooltip)
        button.setFixedSize(width, CONTROL_SIZE)
        button.setFocusPolicy(Qt.NoFocus)  # keep keyboard focus (e.g. Delete) on the canvas
        button.clicked.connect(action)
        return button

    def show_mode(self, mode: str) -> None:
        self.edit_mode.setChecked(mode == EDIT)
        self.drag_mode.setChecked(mode == DRAG)

    def show_zoom(self, index: int) -> None:
        self.reset.setText(strings.ZOOM_PERCENT.format(percent=round(ZOOM_LEVELS[index] * 100)))
        self.zoom_out.setEnabled(index > 0)
        self.zoom_in.setEnabled(index < len(ZOOM_LEVELS) - 1)


def build_button(view: "EditorView") -> QPushButton:
    """The "▶ Build" button in the bottom-left corner of the canvas."""
    button = QPushButton(strings.BUILD_BUTTON, view)
    button.setObjectName("build")
    font = button.font()
    font.setPointSizeF(font.pointSizeF() * BUILD_FONT_SCALE)
    button.setFont(font)
    box = ICON_SIZE + 4  # a little room between the icon and the text
    button.setIcon(load_icon("play-filled", box, BUILD_ICON))
    button.setIconSize(QSize(box, box))
    button.setToolTip(strings.BUILD_TIP)
    button.setFixedHeight(BUILD_SIZE)
    button.setFocusPolicy(Qt.NoFocus)  # keep keyboard focus (e.g. Delete) on the canvas
    button.setStyleSheet(CONTROLS_STYLE)
    button.clicked.connect(view.build_requested)
    button.adjustSize()
    return button


class EditorView(QGraphicsView):
    """The canvas. Its keyboard shortcuts (zoom, V/H for the cursor modes) live on the main window's View menu."""

    scene_replaced = Signal()  # set_graph put a new EditorScene in the view
    zoom_changed = Signal(int)  # index into ZOOM_LEVELS
    mode_changed = Signal(str)  # the chosen cursor mode (EDIT or DRAG), not counting Space held down
    build_requested = Signal()  # the Build button was clicked
    # Files were dropped on the canvas or chosen with Add Inputs…: the paths, the scene point to add Inputs at,
    # and the Input a single dropped file landed on (or None).
    files_dropped = Signal(list, QPointF, object)

    def __init__(self, graph: Graph) -> None:
        scene = EditorScene(graph)
        super().__init__(scene)
        self._scene = scene  # keep a Python reference so the scene isn't garbage-collected
        self.setRenderHint(QPainter.Antialiasing)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)  # _set_zoom keeps its own anchor point fixed

        # The scene point in the middle of the view, kept unrounded. Scroll positions are whole pixels, so
        # re-reading the center after every resize would drift by half a pixel each time on odd sizes.
        self._center = QPointF(0, 0)
        self._recentering = False  # True while the view moves for internal reasons (not a user pan)
        for bar in (self.horizontalScrollBar(), self.verticalScrollBar()):
            bar.valueChanged.connect(self._scrolled)
        self._watch_scene(scene)

        # Selection box, while one is being dragged: its corners in scene coordinates, how it changes the
        # selection, and the selection from before it.
        self._band_start: QPointF | None = None
        self._band_end = QPointF()
        self._band_mouse = QPointF()  # the mouse, in viewport coordinates
        self._band_mode = "replace"  # or "add" (Shift) or "toggle" (Ctrl)
        self._band_before: set[QGraphicsItem] = set()
        self._band_timer = QTimer(self)  # scrolls while the mouse is near or past the window edge
        self._band_timer.setInterval(BAND_SCROLL_INTERVAL)
        self._band_timer.timeout.connect(self._band_scroll)

        self._mode = EDIT
        self._space_held = False  # holding Space switches to Drag mode until released
        self._pan_from: QPointF | None = None
        self._pan_button = Qt.NoButton
        self._zoom_index = ZOOM_LEVELS.index(1.0)
        self._wheel_delta = 0  # touchpads scroll in small steps; add them up to whole notches

        self.controls = CanvasControls(self)
        self.controls.show_mode(EDIT)
        self.build_button = build_button(self)

    # --- Showing a different graph ---

    def set_graph(self, graph: Graph, view: ViewState) -> None:
        """Show `graph` in a fresh scene, at the given zoom and center."""
        self._leave_text_box()
        self._end_band()
        scene = EditorScene(graph)
        self._watch_scene(scene)
        self.setScene(scene)
        self._scene = scene
        self._center = QPointF(view.center_x, view.center_y)
        self._apply_zoom(min(range(len(ZOOM_LEVELS)), key=lambda i: abs(ZOOM_LEVELS[i] - view.zoom)))
        self.scene_replaced.emit()

    def _watch_scene(self, scene: EditorScene) -> None:
        scene.nodes_changed.connect(self.update_bounds)
        scene.reveal.connect(self._reveal)
        scene.files_chosen.connect(lambda paths, pos: self.files_dropped.emit(paths, pos, None))

    # --- Dropping files ---
    # Handled here rather than in the scene, which ignores drops while in drag mode.

    def _drop_target(self, paths: list[str], pos: QPoint) -> int | None:
        """The Input a drop at `pos` would set the file of: one is under it, and the drop is a single audio file."""
        if len(paths) != 1 or not is_audio_file(paths[0]):
            return None
        return self.scene().input_at(self.mapToScene(pos))

    def dragEnterEvent(self, event) -> None:
        if dropped_paths(event.mimeData()):
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        paths = dropped_paths(event.mimeData())
        if paths:
            self.scene().show_drop_target(self._drop_target(paths, event.position().toPoint()))
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self.scene().show_drop_target(None)

    def dropEvent(self, event) -> None:
        self.scene().show_drop_target(None)
        paths = dropped_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        event.setDropAction(Qt.CopyAction)
        event.accept()
        pos = event.position().toPoint()
        self.files_dropped.emit(paths, QPointF(self.mapToScene(pos)), self._drop_target(paths, pos))

    def _reveal(self, area: QRectF) -> None:
        """Center on `area` if none of it is on screen, without zooming."""
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        if not visible.intersects(area):
            self._recenter(area.center())

    def view_state(self) -> ViewState:
        return ViewState(ZOOM_LEVELS[self._zoom_index], self._center.x(), self._center.y())

    # --- View center and pan limits ---

    def _actual_center(self) -> QPointF:
        size = self.viewport().size()
        return self.viewportTransform().inverted()[0].map(QPointF(size.width() / 2, size.height() / 2))

    def _scrolled(self) -> None:
        if not self._recentering:
            self._center = self._actual_center()

    def _recenter(self, center: QPointF) -> None:
        """Put `center` in the middle of the view (as far as the pan limits allow) and remember it unrounded."""
        self._recentering = True
        try:
            super().centerOn(center)
        finally:
            self._recentering = False
        actual = self._actual_center()
        close = (actual - center).manhattanLength() * self.transform().m11() <= 1  # off only by rounding
        self._center = QPointF(center) if close else actual

    def update_bounds(self) -> None:
        """Limit panning so at least KEEP_VISIBLE screen px of the nodes' area (or an empty canvas's hint) always
        stays on screen."""
        zoom = self.transform().m11()
        dx = (self.viewport().width() - KEEP_VISIBLE) / zoom
        dy = (self.viewport().height() - KEEP_VISIBLE) / zoom
        center = self._center
        self._recentering = True
        try:
            self.setSceneRect(self.scene().content_rect().adjusted(-dx, -dy, dx, dy))
        finally:
            self._recentering = False
        self._recenter(center)  # changing the scene rect would otherwise shift the view

    # --- Cursor modes ---

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._mode_changed()
        self.mode_changed.emit(mode)

    def _effective_mode(self) -> str:
        return DRAG if self._space_held else self._mode

    def _mode_changed(self) -> None:
        mode = self._effective_mode()
        if mode == DRAG:
            self._leave_text_box()
        self.controls.show_mode(mode)
        self._update_cursor()

    def _typing(self) -> bool:
        return isinstance(self.scene().focusItem(), QGraphicsProxyWidget)

    def _leave_text_box(self) -> None:
        if self._typing():
            self.scene().focusItem().clearFocus()

    def text_field(self) -> QLineEdit | None:
        """The Name box being typed in, if any."""
        item = self.scene().focusItem()
        if isinstance(item, QGraphicsProxyWidget) and isinstance(item.widget(), QLineEdit):
            return item.widget()
        return None

    def mouse_scene_pos(self) -> QPointF | None:
        """Where the mouse is on the canvas, or None if it isn't over the canvas (but e.g. over a menu)."""
        mouse = QCursor.pos()
        if QApplication.widgetAt(mouse) is not self.viewport():
            return None
        return self.mapToScene(self.viewport().mapFromGlobal(mouse))

    def _update_cursor(self) -> None:
        if self._pan_from is not None:
            self.viewport().setCursor(Qt.ClosedHandCursor)
        elif self._effective_mode() == DRAG:
            self.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self.viewport().unsetCursor()

    def event(self, event) -> bool:
        # Tab and Shift+Tab move between node fields in reading order. The fields live in the scene, so the view
        # keeps keyboard focus and would otherwise use Qt's order: the order the nodes were added.
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            if not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
                backwards = event.key() == Qt.Key_Backtab or event.modifiers() & Qt.ShiftModifier
                if self.scene().focus_next_field(not backwards):
                    return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and not self._typing():
            if not event.isAutoRepeat():
                self._space_held = True
                self._mode_changed()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and self._space_held:
            if not event.isAutoRepeat():
                self._space_held = False
                self._mode_changed()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        if self._space_held:  # the Space release may go to another window
            self._space_held = False
            self._mode_changed()
        super().focusOutEvent(event)

    # --- Zoom ---

    def zoom_in(self) -> None:
        self._set_zoom(self._zoom_index + 1)

    def zoom_out(self) -> None:
        self._set_zoom(self._zoom_index - 1)

    def zoom_index(self) -> int:
        return self._zoom_index

    def zoom_to_fit(self) -> None:
        """Show all nodes (or an empty canvas's hint), with FIT_MARGIN screen px around them, at the largest zoom
        step up to 100% that fits."""
        rect = self.scene().content_rect()
        actual_size = ZOOM_LEVELS.index(1.0)
        index = actual_size
        if self.scene().node_items:
            width = self.viewport().width() - 2 * FIT_MARGIN
            height = self.viewport().height() - 2 * FIT_MARGIN
            while index > 0 and (rect.width() * ZOOM_LEVELS[index] > width
                                 or rect.height() * ZOOM_LEVELS[index] > height):
                index -= 1
        self._center = rect.center()
        self._apply_zoom(index)

    def reset_zoom(self) -> None:
        self._set_zoom(ZOOM_LEVELS.index(1.0))

    def _set_zoom(self, index: int, anchor: QPoint | None = None) -> None:
        """Zoom to ZOOM_LEVELS[index], keeping the scene point at `anchor` (default: view center) in place."""
        index = max(0, min(len(ZOOM_LEVELS) - 1, index))
        if index == self._zoom_index:
            return
        zoom = ZOOM_LEVELS[index]
        if anchor is not None:
            # Choose the new center so the scene point under `anchor` stays under it at the new zoom.
            size = self.viewport().size()
            offset = QPointF(anchor) - QPointF(size.width() / 2, size.height() / 2)  # screen px from the middle
            fixed_point = self._center + offset / self.transform().m11()
            self._center = fixed_point - offset / zoom
        self._apply_zoom(index)

    def _apply_zoom(self, index: int) -> None:
        """Set the zoom to ZOOM_LEVELS[index] around self._center."""
        self._zoom_index = index
        zoom = ZOOM_LEVELS[index]
        self._recentering = True
        try:
            self.setTransform(QTransform.fromScale(zoom, zoom))
        finally:
            self._recentering = False
        self.update_bounds()  # the limits depend on how much fits on screen; also recenters on self._center
        self.controls.show_zoom(index)
        self.zoom_changed.emit(index)

    def wheelEvent(self, event) -> None:
        self._wheel_delta += event.angleDelta().y()
        steps = int(self._wheel_delta / WHEEL_NOTCH)  # rounds toward zero, so partial notches carry over
        self._wheel_delta -= steps * WHEEL_NOTCH
        if steps:
            self._set_zoom(self._zoom_index + steps, anchor=event.position().toPoint())

    def resizeEvent(self, event) -> None:
        self._recentering = True
        try:
            super().resizeEvent(event)
        finally:
            self._recentering = False
        self.update_bounds()  # also keeps the same spot in the middle while the window resizes
        self.controls.move(
            self.width() - self.controls.width() - CONTROLS_MARGIN,
            self.height() - self.controls.height() - CONTROLS_MARGIN,
        )
        self.build_button.move(CONTROLS_MARGIN, self.height() - self.build_button.height() - CONTROLS_MARGIN)

    # --- Mouse: middle-drag always pans; in Drag mode left-drag pans and nothing in the scene can be clicked. In
    # Edit mode, left-dragging from empty canvas draws a selection box. ---

    def mousePressEvent(self, event) -> None:
        dragging = self._effective_mode() == DRAG
        if event.button() == Qt.MiddleButton or (dragging and event.button() == Qt.LeftButton):
            self._pan_from = event.position()
            self._pan_button = event.button()
            self._update_cursor()
        elif self._on_empty_canvas(event):
            self._start_band(event)
        elif not dragging:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._effective_mode() == DRAG or self._on_empty_canvas(event):
            self.mousePressEvent(event)  # a quick second click should start another pan or box, not edit anything
        else:
            super().mouseDoubleClickEvent(event)

    def _on_empty_canvas(self, event) -> bool:
        """True for a left click in Edit mode that isn't on a node or wire."""
        return (
            event.button() == Qt.LeftButton
            and self._effective_mode() == EDIT
            and self.itemAt(event.position().toPoint()) is None
        )

    def _start_band(self, event) -> None:
        self._leave_text_box()
        modifiers = event.modifiers()
        if modifiers & Qt.ShiftModifier:
            self._band_mode = "add"
        elif modifiers & Qt.ControlModifier:
            self._band_mode = "toggle"
        else:
            self._band_mode = "replace"
        self._band_before = set(self.scene().selectedItems())
        self._band_mouse = event.position()
        self._band_start = self.mapToScene(event.position().toPoint())
        self._update_band()
        self._band_timer.start()

    def _update_band(self) -> None:
        """Select what the box touches, combined with the selection from before it as the box's mode says."""
        self._band_end = self.mapToScene(self._band_mouse.toPoint())
        box = QRectF(self._band_start, self._band_end).normalized()
        scene = self.scene()
        hits = set()
        if box.width() or box.height():
            hits = {item.topLevelItem() for item in scene.items(box, Qt.IntersectsItemShape)}
        if self._band_mode == "add":
            chosen = self._band_before | hits
        elif self._band_mode == "toggle":
            chosen = self._band_before ^ hits
        else:
            chosen = hits
        for item in [*scene.node_items.values(), *scene.wire_items.values()]:
            item.setSelected(item in chosen)
        self.viewport().update()

    def _band_scroll(self) -> None:
        """While the mouse is near or past an edge of the window, scroll that way, faster the further out it is."""
        rect = self.viewport().rect()
        x, y = self._band_mouse.x(), self._band_mouse.y()

        def step(position: float, size: int) -> int:
            if position < BAND_SCROLL_MARGIN:
                distance = position - BAND_SCROLL_MARGIN
            elif position > size - BAND_SCROLL_MARGIN:
                distance = position - (size - BAND_SCROLL_MARGIN)
            else:
                return 0
            return max(-BAND_SCROLL_MAX, min(BAND_SCROLL_MAX, round(distance / 2)))

        moved = False
        for bar, delta in ((self.horizontalScrollBar(), step(x, rect.width())),
                           (self.verticalScrollBar(), step(y, rect.height()))):
            if delta:
                before = bar.value()
                bar.setValue(before + delta)
                moved |= bar.value() != before
        if moved:
            self._update_band()

    def _end_band(self) -> None:
        if self._band_start is not None:
            self._band_start = None
            self._band_before = set()
            self._band_timer.stop()
            self.viewport().update()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if self._band_start is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)  # a crisp 1px line
        pen = QPen(SELECTED, 1)
        pen.setCosmetic(True)  # 1 screen px at any zoom
        fill = QColor(SELECTED)
        fill.setAlpha(BAND_FILL_ALPHA)
        painter.setPen(pen)
        painter.setBrush(fill)
        painter.drawRect(QRectF(self._band_start, self._band_end).normalized())
        painter.restore()

    def mouseMoveEvent(self, event) -> None:
        if self._band_start is not None:
            self._band_mouse = event.position()
            self._update_band()
        elif self._pan_from is not None:
            delta = event.position() - self._pan_from
            self._pan_from = event.position()
            h, v = self.horizontalScrollBar(), self.verticalScrollBar()
            h.setValue(h.value() - round(delta.x()))
            v.setValue(v.value() - round(delta.y()))
        elif self._effective_mode() == EDIT:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._band_start is not None:
            if event.button() == Qt.LeftButton:
                self._end_band()
        elif self._pan_from is not None and event.button() == self._pan_button:
            self._pan_from = None
            self._update_cursor()
        elif self._effective_mode() == EDIT:
            super().mouseReleaseEvent(event)


