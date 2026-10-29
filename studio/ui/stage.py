"""Сцена сверху: помещение, сцена, инструменты и стереопара слушателя — всё перетаскивается."""
from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsLineItem,
                             QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView)

from ..render import channel_geometry, critical_distance, stage_center
from ..session import Session

U = 100.0          # 1 м = 100 единиц сцены
TOKEN_R = 15       # радиус значка в пикселях экрана


class _Token(QGraphicsEllipseItem):
    def __init__(self, view: "StageView", key: str, label: str, color: str, listener: bool = False):
        r = TOKEN_R + (2 if listener else 0)
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.view = view
        self.key = key
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setCursor(Qt.OpenHandCursor)
        self.setZValue(10 if not listener else 12)
        c = QColor(color)
        self.setBrush(QBrush(c if not listener else QColor("#1e1e2e")))
        self.setPen(QPen(QColor("#1e1e2e") if not listener else c, 2))
        self.text = QGraphicsSimpleTextItem(label, self)
        f = QFont("Menlo", 8)
        f.setBold(True)
        self.text.setFont(f)
        self.text.setBrush(QBrush(QColor("#cdd6f4")))
        br = self.text.boundingRect()
        self.text.setPos(-br.width() / 2, r + 2)
        self.badge = QGraphicsSimpleTextItem("", self)
        self.badge.setFont(QFont("Menlo", 9))
        self.badge.setBrush(QBrush(QColor("#1e1e2e") if not listener else c))
        self.set_badge("L+R" if listener else label[:2])

    def set_badge(self, s: str):
        self.badge.setText(s)
        br = self.badge.boundingRect()
        self.badge.setPos(-br.width() / 2, -br.height() / 2)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.view.room_rect is not None:
            r = self.view.room_rect
            p = QPointF(value)
            m = 0.2 * U
            p.setX(min(max(p.x(), r.left() + m), r.right() - m))
            p.setY(min(max(p.y(), r.top() + m), r.bottom() - m))
            return p
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.view.token_moved(self.key, self.pos())
        if change == QGraphicsItem.ItemSelectedHasChanged and value:
            self.view.token_selected(self.key)
        return super().itemChange(change, value)

    def mousePressEvent(self, e):
        self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(e)
        self.view.drag_finished.emit()


class StageView(QGraphicsView):
    channel_moved = pyqtSignal(str, float, float)
    listener_moved = pyqtSignal(float, float)
    channel_selected = pyqtSignal(str)
    drag_finished = pyqtSignal()
    info_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor("#11111b")))
        self.setMinimumSize(420, 320)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setToolTip("Перетаскивайте значки · колесо — масштаб · двойной клик по пустому месту — вписать")
        self.session: Session | None = None
        self.tokens: dict[str, _Token] = {}
        self.listener: _Token | None = None
        self.room_rect: QRectF | None = None
        self.lines: dict[str, QGraphicsLineItem] = {}
        self.selected_id: str | None = None
        self._building = False
        self.info = None

    # ── построение ───────────────────────────────────────────
    def set_session(self, session: Session):
        self.session = session
        self.rebuild()

    def rebuild(self):
        self._building = True
        sc = self.scene()
        sc.clear()
        self.tokens.clear()
        self.lines.clear()
        s = self.session
        if s is None:
            self._building = False
            return
        p = s.scene_preset
        W, D = p.width * U, p.depth * U
        self.room_rect = QRectF(0, 0, W, D)
        sc.setSceneRect(QRectF(-0.06 * W, -0.06 * D, W * 1.12, D * 1.12))
        # сетка: шаг 1/5/10 м в зависимости от размера
        step = 1 if max(p.width, p.depth) <= 20 else 5 if max(p.width, p.depth) <= 60 else 10
        grid = QPen(QColor("#1e1e2e"), 0)
        x = 0.0
        while x <= p.width + 1e-6:
            sc.addLine(x * U, 0, x * U, D, grid)
            x += step
        y = 0.0
        while y <= p.depth + 1e-6:
            sc.addLine(0, y * U, W, y * U, grid)
            y += step
        room = sc.addRect(self.room_rect, QPen(QColor("#45475a"), 0), QBrush(Qt.NoBrush))
        room.setZValue(1)
        x0, y0, x1, y1 = p.stage_rect()
        stage = sc.addRect(QRectF(x0 * U, y0 * U, (x1 - x0) * U, (y1 - y0) * U),
                           QPen(QColor("#585b70"), 0, Qt.DashLine), QBrush(QColor(137, 180, 250, 22)))
        stage.setZValue(2)
        # критическая дистанция вокруг центра сцены
        rc = critical_distance(p, s.rt60)
        if rc < max(p.width, p.depth):
            cx, cy = stage_center(s)
            circ = sc.addEllipse(QRectF((cx - rc) * U, (cy - rc) * U, 2 * rc * U, 2 * rc * U),
                                 QPen(QColor(203, 166, 247, 90), 0, Qt.DotLine))
            circ.setZValue(3)
            t = sc.addSimpleText(f"критическая дистанция {rc:.1f} м", QFont("Menlo", 8))
            t.setBrush(QBrush(QColor(203, 166, 247, 160)))
            t.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            t.setPos((cx + rc * 0.71) * U, (cy + rc * 0.71) * U)
        lx, ly = s.listener()
        for ch in s.channels:
            line = sc.addLine(ch.x * U, ch.y * U, lx * U, ly * U, QPen(QColor(ch.color).darker(160), 0, Qt.DotLine))
            line.setZValue(4)
            self.lines[ch.id] = line
            tok = _Token(self, ch.id, ch.name, ch.color)
            tok.setPos(ch.x * U, ch.y * U)
            tok.setOpacity(0.35 if ch.mute else 1.0)
            sc.addItem(tok)
            self.tokens[ch.id] = tok
        self.listener = _Token(self, "__listener__", "Слушатель / room-пара", "#f9e2af", listener=True)
        self.listener.setPos(lx * U, ly * U)
        sc.addItem(self.listener)
        self.info = True
        self.grid_step = step
        self._building = False
        if self.selected_id in self.tokens:
            self.tokens[self.selected_id].setSelected(True)
        self._update_info()
        self.fit()

    def fit(self):
        """Кадрируем сцену + слушателя (а не весь зал), чтобы в арене значки не слипались."""
        if self.room_rect is None or self.session is None:
            return
        p = self.session.scene_preset
        x0, y0, x1, y1 = p.stage_rect()
        lx, ly = self.session.listener()
        xs = [x0, x1, lx] + [c.x for c in self.session.channels]
        ys = [y0, y1, ly] + [c.y for c in self.session.channels]
        r = QRectF(min(xs) * U, min(ys) * U, (max(xs) - min(xs)) * U, (max(ys) - min(ys)) * U)
        mx, my = max(r.width() * 0.18, 1.2 * U), max(r.height() * 0.22, 1.2 * U)
        r = r.adjusted(-mx, -my, mx, my).intersected(self.scene().sceneRect())
        self.fitInView(r, Qt.KeepAspectRatio)
        self._zoom = 1.0

    def wheelEvent(self, e):
        k = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        z = getattr(self, "_zoom", 1.0) * k
        if 0.3 < z < 12:
            self._zoom = z
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
            self.scale(k, k)

    def mouseDoubleClickEvent(self, e):
        if self.itemAt(e.pos()) is None:
            self.fit()
        else:
            super().mouseDoubleClickEvent(e)

    # ── обратная связь от значков ────────────────────────────
    def token_moved(self, key: str, pos: QPointF):
        if self._building or self.session is None:
            return
        x, y = pos.x() / U, pos.y() / U
        if key == "__listener__":
            self.session.listener_x, self.session.listener_y = x, y
            for cid, line in self.lines.items():
                l0 = line.line()
                line.setLine(l0.x1(), l0.y1(), pos.x(), pos.y())
            self.listener_moved.emit(x, y)
        else:
            ch = self.session.channel(key)
            if ch:
                ch.x, ch.y = x, y
            line = self.lines.get(key)
            if line:
                l0 = line.line()
                line.setLine(pos.x(), pos.y(), l0.x2(), l0.y2())
            self.channel_moved.emit(key, x, y)
        self._update_info()

    def token_selected(self, key: str):
        if key != "__listener__":
            self.selected_id = key
            self.channel_selected.emit(key)
            self._update_info()

    def select(self, ch_id: str):
        self.selected_id = ch_id
        for k, t in self.tokens.items():
            t.setSelected(k == ch_id)
        self._update_info()

    def _update_info(self):
        if self.info is None or self.session is None:
            return
        p = self.session.scene_preset
        head = f"{p.name} · {p.width:g}×{p.depth:g} м · сетка {getattr(self, 'grid_step', 1)} м"
        ch = self.session.channel(self.selected_id) if self.selected_id else None
        if not ch:
            self.info_changed.emit(head + " · перетаскивайте инструменты и слушателя мышью")
            return
        g = channel_geometry(self.session, ch)
        side = "Л" if g["pan"] < -0.05 else "П" if g["pan"] > 0.05 else "центр"
        self.info_changed.emit(
            f"{head}  |  {ch.name}: {g['distance_m']:.1f} м до пары · {g['delay_ms']:.0f} мс · "
            f"азимут {g['azimuth_deg']:+.0f}° · панорама {abs(g['pan']) * 100:.0f}% {side}"
            + (" · за критической дистанцией" if g["beyond_critical"] else ""))

    def refresh_token(self, ch_id: str):
        ch = self.session.channel(ch_id) if self.session else None
        tok = self.tokens.get(ch_id)
        if not ch or not tok:
            return
        tok.setOpacity(0.35 if ch.mute else 1.0)
        tok.setBrush(QBrush(QColor(ch.color)))
        tok.text.setText(ch.name)
        br = tok.text.boundingRect()
        tok.text.setPos(-br.width() / 2, TOKEN_R + 2)
        tok.set_badge(ch.name[:2])
        self._update_info()


def distance(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
