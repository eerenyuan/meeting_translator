from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QPushButton, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QPalette


class _ContextSignals(QObject):
    _display_signal = pyqtSignal(str, object, object)


class ContextSidebar(QWidget):

    def __init__(self):
        super().__init__()

        self.signals = _ContextSignals()
        self.signals._display_signal.connect(self._on_result)

        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.Tool |
            Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)

        self._mode_labels = {
            "explain": ("Ctrl+1", "Explain", "Explain"),
            "experience": ("Ctrl+2", "Experience", "Experience"),
            "ammo": ("Ctrl+3", "Ammo", "Ammo"),
            "reply": ("Ctrl+4", "Reply", "Reply"),
        }

        self.drag_position = None
        self._init_ui()
        self.resize(350, 420)
        self.setMinimumSize(300, 300)

    def _init_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        container = QWidget()
        container.setStyleSheet("""
            QWidget#sidebarContainer {
                background-color: rgba(30, 30, 38, 235);
                border: 1px solid rgba(100, 150, 255, 80);
                border-radius: 12px;
            }
        """)
        container.setObjectName("sidebarContainer")

        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title_bar = QHBoxLayout()
        title_bar.setSpacing(6)
        title_label = QLabel("Context Assistant")
        title_label.setStyleSheet("color: rgba(200, 210, 255, 0.95); font-size: 13px; font-weight: bold; border: none;")
        title_bar.addWidget(title_label)
        title_bar.addStretch()

        self._close_btn = QPushButton("x")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(255, 255, 255, 30);
                border: none;
                border-radius: 12px;
                color: rgba(255, 255, 255, 150);
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(255, 80, 80, 120);
                color: white;
            }
        """)
        self._close_btn.clicked.connect(self.hide)
        title_bar.addWidget(self._close_btn)
        layout.addLayout(title_bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: rgba(100, 150, 255, 60); max-height: 1px; border: none;")
        layout.addWidget(sep)

        self._status_label = QLabel("Waiting...")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: rgba(160, 170, 200, 0.8); font-size: 11px; border: none; padding: 2px;")
        layout.addWidget(self._status_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background-color: rgba(255, 255, 255, 20);
                width: 8px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical {
                background-color: rgba(100, 150, 255, 120);
                border-radius: 4px;
                min-height: 20px;
            }
        """)

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: transparent;")
        self._cards_layout = QVBoxLayout(scroll_content)
        self._cards_layout.setContentsMargins(0, 4, 0, 4)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        btn_configs = [
            ("explain", "F1 Explain", "rgba(52, 152, 219, 180)"),
            ("experience", "F2 Exp", "rgba(46, 204, 113, 180)"),
            ("ammo", "F3 Ammo", "rgba(231, 76, 60, 180)"),
            ("reply", "F4 Reply", "rgba(155, 89, 182, 180)"),
        ]

        self._mode_buttons = {}
        for mode, label, color in btn_configs:
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color};
                    border: none;
                    border-radius: 6px;
                    color: white;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 0 8px;
                }}
                QPushButton:hover {{
                    background-color: {color.replace('180', '220')};
                }}
                QPushButton:pressed {{
                    background-color: {color.replace('180', '140')};
                }}
            """)
            btn.clicked.connect(lambda checked, m=mode: self._on_button_clicked(m))
            self._mode_buttons[mode] = btn
            btn_row.addWidget(btn)

        layout.addLayout(btn_row)

        outer.addWidget(container)
        self.setLayout(outer)

    def _on_button_clicked(self, mode: str):
        self._status_label.setText(f"Processing [{mode}]...")
        self._status_label.setStyleSheet("color: rgba(255, 200, 100, 0.95); font-size: 11px; border: none; padding: 2px;")

        if hasattr(self, '_trigger_callback') and self._trigger_callback:
            self._trigger_callback(mode)

    def set_trigger_callback(self, callback):
        self._trigger_callback = callback

    def on_result(self, mode: str, content: str, error: str):
        self.signals._display_signal.emit(mode, content, error)

    def _on_result(self, mode: str, content, error):
        if error:
            self._status_label.setText(f"Error: {error}")
            self._status_label.setStyleSheet("color: rgba(255, 100, 100, 0.95); font-size: 11px; border: none; padding: 2px;")
            self._add_error_card(mode, error)
            return

        self._status_label.setText("Done")
        self._status_label.setStyleSheet("color: rgba(100, 220, 130, 0.9); font-size: 11px; border: none; padding: 2px;")
        self._add_result_card(mode, content)

    def _add_result_card(self, mode: str, content: str):
        mode_info = self._mode_labels.get(mode, ("", mode, mode))
        _, mode_name, _ = mode_info

        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: rgba(50, 52, 68, 200);
                border: 1px solid rgba(100, 150, 255, 60);
                border-radius: 8px;
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(4)

        from datetime import datetime
        header = QHBoxLayout()
        tag = QLabel(f"[{mode_name}]")
        tag.setStyleSheet("color: rgba(100, 180, 255, 0.95); font-size: 11px; font-weight: bold; border: none;")
        header.addWidget(tag)

        ts_label = QLabel(datetime.now().strftime("%H:%M:%S"))
        ts_label.setStyleSheet("color: rgba(140, 150, 180, 0.7); font-size: 10px; border: none;")
        header.addWidget(ts_label)
        header.addStretch()
        card_layout.addLayout(header)

        content_label = QLabel(content)
        content_label.setWordWrap(True)
        content_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        content_label.setStyleSheet("""
            color: rgba(220, 225, 240, 0.95);
            font-size: 12px;
            line-height: 1.5;
            border: none;
            padding: 2px 0;
        """)
        card_layout.addWidget(content_label)

        stretch_index = self._cards_layout.count() - 1
        self._cards_layout.insertWidget(stretch_index, card)

    def _add_error_card(self, mode: str, error: str):
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: rgba(80, 40, 40, 200);
                border: 1px solid rgba(255, 100, 100, 60);
                border-radius: 8px;
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)

        label = QLabel(f"Error [{mode}]: {error}")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setStyleSheet("color: rgba(255, 150, 150, 0.95); font-size: 11px; border: none;")
        card_layout.addWidget(label)

        stretch_index = self._cards_layout.count() - 1
        self._cards_layout.insertWidget(stretch_index, card)

    def clear_cards(self):
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_position = None
