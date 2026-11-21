"""Qt view of the node graph: canvas, nodes, ports and wires."""

from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QLineF, QPoint, QPointF, QRect, QRectF, QSettings, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QImage,
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
from graph import AUTO, AUTO_CHOICE, CHOICES, GRID, NODE_TYPES, Connection, Graph, Node, snap
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


class NodeItem(QGraphicsItem):
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


class WireItem(QGraphicsPathItem):
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
    nodes_changed = Signal()  # a node was added, moved or removed
    edited = Signal()  # the user changed the graph (it may have changed back to how it was)

    def __init__(self, graph: Graph) -> None:
        super().__init__()
        self.graph = graph
        self.node_items: dict[int, NodeItem] = {}
        self.wire_items: dict[Connection, WireItem] = {}
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
        if self.itemAt(pos, QTransform()):
            super().contextMenuEvent(event)  # e.g. a text box's own copy/paste menu
            return
        menu = QMenu()
        add_menu_heading(menu, strings.ADD_NODE_HEADING)
        for i, group in enumerate(MENU_GROUPS):
            if i:
                menu.addSeparator()
            for key in group:
                menu.addAction(NODE_TYPES[key].title).setData(key)
        chosen = menu.exec(event.screenPos())
        if chosen:
            self.add_node(chosen.data(), pos)

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

    def keyPressEvent(self, event) -> None:
        typing = isinstance(self.focusItem(), QGraphicsProxyWidget)
        if event.key() == Qt.Key_Delete and not typing:
            self.delete_selected()
        else:
            super().keyPressEvent(event)

    def add_node(self, type_key: str, pos: QPointF) -> None:
        self._add_item(self.graph.add_node(type_key, pos.x(), pos.y()))
        self.nodes_changed.emit()
        self.edited.emit()

    def _add_item(self, node: Node) -> None:
        item = NodeItem(node)
        self.addItem(item)
        self.node_items[node.id] = item

    def set_value(self, node_id: int, name: str, value: str) -> None:
        self.graph.set_value(node_id, name, value)
        self.edited.emit()

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
        scene.nodes_changed.connect(self.update_bounds)

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
        scene = EditorScene(graph)
        scene.nodes_changed.connect(self.update_bounds)
        self.setScene(scene)
        self._scene = scene
        self._center = QPointF(view.center_x, view.center_y)
        self._apply_zoom(min(range(len(ZOOM_LEVELS)), key=lambda i: abs(ZOOM_LEVELS[i] - view.zoom)))
        self.scene_replaced.emit()

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

    # --- Mouse: middle-drag always pans; in Drag mode left-drag pans and nothing in the scene can be clicked ---

    def mousePressEvent(self, event) -> None:
        dragging = self._effective_mode() == DRAG
        if event.button() == Qt.MiddleButton or (dragging and event.button() == Qt.LeftButton):
            self._pan_from = event.position()
            self._pan_button = event.button()
            self._update_cursor()
        elif not dragging:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._effective_mode() == DRAG:
            self.mousePressEvent(event)  # a quick second click should start another pan, not edit anything
        else:
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pan_from is not None:
            delta = event.position() - self._pan_from
            self._pan_from = event.position()
            h, v = self.horizontalScrollBar(), self.verticalScrollBar()
            h.setValue(h.value() - round(delta.x()))
            v.setValue(v.value() - round(delta.y()))
        elif self._effective_mode() == EDIT:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pan_from is not None and event.button() == self._pan_button:
            self._pan_from = None
            self._update_cursor()
        elif self._effective_mode() == EDIT:
            super().mouseReleaseEvent(event)


