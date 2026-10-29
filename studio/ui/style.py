"""Тема Catppuccin Mocha — продолжение стиля gui_pipeline.py."""
from gui_pipeline import STYLE as BASE_STYLE  # noqa: F401  (исходный стиль проекта — база)

EXTRA = """
QMainWindow, QTabWidget::pane { background:#1e1e2e; }
QTabWidget::pane { border:1px solid #313244; border-radius:6px; top:-1px; }
QTabBar::tab   { background:#181825; color:#a6adc8; padding:8px 18px; border:1px solid #313244;
                 border-bottom:none; border-top-left-radius:6px; border-top-right-radius:6px; margin-right:2px; }
QTabBar::tab:selected { background:#313244; color:#cdd6f4; border-bottom:2px solid #89b4fa; }
QTabBar::tab:hover    { color:#cdd6f4; }
QPlainTextEdit { background:#181825; border:1px solid #313244; border-radius:4px; padding:6px; color:#cdd6f4; }
QSpinBox, QDoubleSpinBox { background:#313244; border:1px solid #45475a; border-radius:4px; padding:3px 6px; }
QSlider::groove:vertical { background:#313244; width:6px; border-radius:3px; }
QSlider::handle:vertical { background:#89b4fa; height:18px; width:22px; margin:0 -8px; border-radius:4px; }
QSlider::sub-page:vertical { background:#313244; }
QSlider::add-page:vertical { background:#45475a; border-radius:3px; }
QScrollArea { border:none; }
QToolButton { background:#313244; border:1px solid #45475a; border-radius:4px; padding:3px 8px; }
QToolButton:checked#mute { background:#f38ba8; color:#1e1e2e; }
QToolButton:checked#solo { background:#f9e2af; color:#1e1e2e; }
QToolButton:hover { background:#45475a; }
QPushButton#accent { background:#a6e3a1; color:#1e1e2e; font-weight:bold; }
QPushButton#accent:hover { background:#94e2d5; }
QPushButton#accent:disabled { background:#45475a; color:#6c7086; }
QPushButton#tag { padding:2px 8px; font-size:11px; border-radius:10px; }
QLabel#h1 { font-size:18px; font-weight:bold; color:#cdd6f4; }
QLabel#muted { color:#7f849c; }
QLabel#ok { color:#a6e3a1; }
QLabel#warn { color:#f9e2af; }
QLabel#err { color:#f38ba8; }
QFrame#strip { background:#181825; border:1px solid #313244; border-radius:6px; }
QFrame#strip[selected="true"] { border:1px solid #89b4fa; }
QStatusBar { background:#181825; color:#a6adc8; }
QSplitter::handle { background:#313244; }
QToolTip { background:#313244; color:#cdd6f4; border:1px solid #45475a; padding:4px; }
"""

STYLE = BASE_STYLE + EXTRA
