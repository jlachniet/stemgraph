"""Qt view of the node graph: canvas, nodes, ports and wires."""

import json
import uuid
from pathlib import Path

from PySide6.QtCore import (
    QByteArray,
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
    QComboBox,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QWidget,
    QWidgetAction,
)

import build
import strings
from graph import AUTO, AUTO_CHOICE, CHOICES, GRID, NODE_TYPES, Connection, Graph, Node, load_fragment, snap
from project import ViewState

NODE_WIDTH = 8 * GRID
PORT_RADIUS = 6
CAPTION_GAP = 8  # space between a caption and its text box
ZOOM_LEVELS = (0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0)
WHEEL_NOTCH = 120  # angleDelta of one mouse-wheel notch
ICON_DIR = Path(__file__).parent.parent / "assets" / "icons"  # Radix Icons, MIT (see docs/design.md)
ICON_SIZE = 15  # Radix Icons are drawn on a 15px grid; render them 1:1 so they stay crisp
# Height of the corner controls, and width of their icon buttons. Odd on purpose: inside the 1px border
# that leaves 27px, so icons whose ink is an odd number of pixels across (most of them) center exactly.
CONTROL_SIZE = 29
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

# Right-click "add node" menu, with a divider between groups.
MENU_GROUPS = [
    ["input", "output"],
    ["split_mid_side"],
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
QPushButton#build {{ padding: 0 10px 0 6px; }}
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
QLabel#menu_heading {{ color: {MENU_HEADING}; background: transparent; padding: 4px 24px 2px 16px; }}
"""

FIELD_SCROLL_MARGIN = 2 * GRID  # Tab scrolls a field at least this far inside the view

LAST_AUDIO_DIR_KEY = "last_audio_dir"  # QSettings key: folder the file picker last chose from
# Common formats that soundfile (libsndfile) can read, alphabetical; it has no M4A/AAC support.
AUDIO_EXTENSIONS = ("aif", "aiff", "flac", "mp3", "ogg", "opus", "wav")
AUDIO_FILTER = ";;".join([
    strings.AUDIO_FILES_FILTER.format(patterns=" ".join(f"*.{e}" for e in AUDIO_EXTENSIONS)),
    strings.ALL_FILES_FILTER,
])


def app_settings() -> QSettings:
    """Per-user settings, kept in an INI file rather than the registry.

    On Windows: %APPDATA%\\stemgraph\\stemgraph.ini
    """
    return QSettings(QSettings.IniFormat, QSettings.UserScope, "stemgraph", "stemgraph")


def load_icon(name: str, box: int) -> QIcon:
    """An icon from assets/icons on a `box`-sized canvas, recolored to the theme (the SVGs draw in currentColor).

    The glyph is drawn at its native ICON_SIZE so it stays crisp, then shifted by whole pixels so its
    visible ink (not its nominal 15px box, which some glyphs don't fill evenly) is centered on the canvas.
    """
    svg = (ICON_DIR / f"{name}.svg").read_text()
    icon = QIcon()
    for mode, color in [(QIcon.Normal, TEXT.name()), (QIcon.Disabled, DISABLED_TEXT)]:
        renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", color).encode()))
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


def add_menu_heading(menu: QMenu, text: str) -> None:
    """Add a title to a menu: small and muted so it can't be mistaken for an option,
    lined up with the item text, followed by a divider, and not clickable."""
    label = QLabel(text)
    label.setObjectName("menu_heading")  # colour and padding in MENU_STYLE
    font = label.font()
    font.setPointSizeF(font.pointSizeF() * 0.9)
    label.setFont(font)
    action = QWidgetAction(menu)
    action.setDefaultWidget(label)
    action.setEnabled(False)  # skipped by the arrow keys
    menu.addAction(action)
    menu.addSeparator()


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
        self.setPos(NODE_WIDTH if is_output else 0, GRID * (node_item.first_port_row + index + 0.5))
        self.setBrush(PORT)
        self.setPen(QPen(NODE_BORDER, 1))
        self.setCursor(Qt.CrossCursor)
        self._drag_wire: QGraphicsPathItem | None = None

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        self._drag_wire = QGraphicsPathItem()
        self._drag_wire.setPen(QPen(WIRE, 2, Qt.DashLine))
        self.scene().addItem(self._drag_wire)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_wire:
            start, end = self.scenePos(), event.scenePos()
            if not self.is_output:
                start, end = end, start
            self._drag_wire.setPath(wire_path(start, end))

    def mouseReleaseEvent(self, event) -> None:
        if not self._drag_wire:
            return
        scene = self.scene()
        scene.removeItem(self._drag_wire)
        self._drag_wire = None
        for item in scene.items(event.scenePos()):
            if isinstance(item, PortItem):
                scene.connect_ports(self, item)
                break


FIELD_CAPTIONS = {"name": strings.NAME_CAPTION, "algorithm": strings.ALGORITHM_CAPTION}
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


class NodeItem(ShiftSelects, QGraphicsItem):
    def __init__(self, node: Node) -> None:
        super().__init__()
        self.node = node
        # Rows, one grid cell each: title, then one per field, then the ports.
        self.first_port_row = 1 + len(node.type.fields)
        port_rows = max(len(node.type.inputs), len(node.type.outputs))
        self.rect = QRectF(0, 0, NODE_WIDTH, GRID * (self.first_port_row + port_rows))
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setPos(node.x, node.y)
        self.fields: list[QGraphicsProxyWidget] = []  # top to bottom
        for row, name in enumerate(node.type.fields, start=1):
            self._add_field(row, name)
        self.inputs = [PortItem(self, False, i) for i in range(len(node.type.inputs))]
        self.outputs = [PortItem(self, True, i) for i in range(len(node.type.outputs))]

    def _add_field(self, row: int, name: str) -> None:
        if name == "name":
            widget = self._name_field()
        elif name in CHOICES:
            widget = self._choice_field(name)
        else:
            widget = self._file_field()
        # Captioned fields sit to the right of their caption ("Name:").
        caption = FIELD_CAPTIONS.get(name)
        left = self._box_left(caption) if caption else 6
        widget.setStyleSheet(FIELD_STYLE)
        # Embedded widgets are drawn over their window background colour; without this, the square behind the
        # rounded corners shows as dark specks against the node body.
        widget.setAttribute(Qt.WA_TranslucentBackground)
        widget.setFixedSize(NODE_WIDTH - left - 6, GRID - 4)
        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(widget)
        proxy.setPos(left, GRID * row + 2)
        self.fields.append(proxy)

    @staticmethod
    def _box_left(caption: str) -> int:
        return 8 + QFontMetrics(QApplication.font()).horizontalAdvance(caption) + CAPTION_GAP

    def _name_field(self) -> QWidget:
        field = QLineEdit(self.node.values.get("name", ""))
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
            if value == AUTO:
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

    def _file_field(self) -> QWidget:
        button = QPushButton()
        self._show_file(button, self.node.values.get("file"))
        button.clicked.connect(lambda: self._choose_file(button))
        return button

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

        painter.setPen(QPen(SELECTED if self.isSelected() else NODE_BORDER, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.rect, 4, 4)

        painter.setPen(TEXT)
        painter.drawText(title.adjusted(8, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, self.node.type.title)
        for row, name in enumerate(self.node.type.fields, start=1):
            if name in FIELD_CAPTIONS:
                caption = QRectF(8, GRID * row, NODE_WIDTH, GRID)
                painter.drawText(caption, Qt.AlignLeft | Qt.AlignVCenter, FIELD_CAPTIONS[name])
        half = NODE_WIDTH / 2 - 10
        top = self.first_port_row
        for i, name in enumerate(self.node.type.inputs):
            label = QRectF(10, GRID * (top + i), half, GRID)
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

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, BACKGROUND)
        painter.setPen(QPen(GRID_LINE, 0))
        left = int(rect.left()) - int(rect.left()) % GRID
        top = int(rect.top()) - int(rect.top()) % GRID
        lines = [QLineF(x, rect.top(), x, rect.bottom()) for x in range(left, int(rect.right()) + 1, GRID)]
        lines += [QLineF(rect.left(), y, rect.right(), y) for y in range(top, int(rect.bottom()) + 1, GRID)]
        painter.drawLines(lines)

    def contextMenuEvent(self, event) -> None:
        pos = event.scenePos()
        item = self.itemAt(pos, QTransform())
        if isinstance(item, QGraphicsProxyWidget):
            super().contextMenuEvent(event)  # a text box's own copy/paste menu
            return
        menu = QMenu()
        if item is None:
            self._menu_action(menu, strings.MENU_PASTE, "paste", lambda: self.paste(pos), self.can_paste())
            menu.addSeparator()
            add_menu_heading(menu, strings.ADD_NODE_HEADING)
            for i, group in enumerate(MENU_GROUPS):
                if i:
                    menu.addSeparator()
                for key in group:
                    menu.addAction(NODE_TYPES[key].title).setData(key)
            chosen = menu.exec(event.screenPos())
            if chosen and chosen.data():
                self.add_node(chosen.data(), pos)
            return
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

    def _add_item(self, node: Node) -> None:
        item = NodeItem(node)
        self.addItem(item)
        self.node_items[node.id] = item

    def set_value(self, node_id: int, name: str, value: str) -> None:
        self.graph.set_value(node_id, name, value)
        self.edited.emit()
        if name != "name":  # typing a name is committed when the box is left
            self.commit()

    def node_moved(self, item: NodeItem) -> None:
        node_id = item.node.id
        self.graph.move_node(node_id, item.x(), item.y())
        for wire in self.wire_items.values():
            if node_id in (wire.connection.src, wire.connection.dst):
                wire.update_path()
        self.nodes_changed.emit()
        self.edited.emit()

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
        """Make the wire items match the model's connections."""
        for connection in list(self.wire_items):
            if connection not in self.graph.connections:
                self.removeItem(self.wire_items.pop(connection))
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
    box = CONTROL_SIZE - 2  # inside the 1px border
    button.setIcon(load_icon("play", box))
    button.setIconSize(QSize(box, box))
    button.setToolTip(strings.BUILD_TIP)
    button.setFixedHeight(CONTROL_SIZE)
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
        """Limit panning so at least KEEP_VISIBLE screen px of the nodes' area always stays on screen."""
        zoom = self.transform().m11()
        dx = (self.viewport().width() - KEEP_VISIBLE) / zoom
        dy = (self.viewport().height() - KEEP_VISIBLE) / zoom
        center = self._center
        self._recentering = True
        try:
            self.setSceneRect(self.scene().nodes_rect().adjusted(-dx, -dy, dx, dy))
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
        """Show all nodes, with FIT_MARGIN screen px around them, at the largest zoom step up to 100% that fits."""
        rect = self.scene().nodes_rect()
        actual_size = ZOOM_LEVELS.index(1.0)
        index = actual_size
        if self.scene().node_items:
            width = self.viewport().width() - 2 * FIT_MARGIN
            height = self.viewport().height() - 2 * FIT_MARGIN
            while index > 0 and (rect.width() * ZOOM_LEVELS[index] > width
                                 or rect.height() * ZOOM_LEVELS[index] > height):
                index -= 1
        self._center = rect.center()  # the origin when there are no nodes
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


