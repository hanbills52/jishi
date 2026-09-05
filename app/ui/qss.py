"""应用级 QSS 样式：现代浅色主题，蓝灰主色。"""

APP_QSS = """
* {
    font-family: "Microsoft YaHei UI", "微软雅黑", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog {
    background: #f5f6f8;
}
/* 工具栏 */
QToolBar {
    background: #ffffff;
    border-bottom: 1px solid #e3e6ea;
    padding: 6px 8px;
    spacing: 4px;
}
QToolBar QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 6px 14px;
    color: #2b3445;
}
QToolBar QToolButton:hover {
    background: #eef2fb;
    border-color: #d5def5;
}
QToolBar QToolButton:pressed {
    background: #dde6fa;
}
QToolBar QToolButton:disabled {
    color: #b0b7c3;
}
QRadioButton {
    color: #2b3445;
    spacing: 6px;
}
/* 分割条 */
QSplitter::handle {
    background: #e3e6ea;
    width: 2px;
}
/* 树 / 表 / 列表 */
QListWidget {
    background: #ffffff;
    border: 1px solid #e3e6ea;
    border-radius: 8px;
    alternate-background-color: #f7f9fc;
    selection-background-color: #dbe6fd;
    selection-color: #1a1f2b;
    outline: none;
}
QListWidget::item {
    padding: 6px 8px;
    border: none;
}
QListWidget::item:hover {
    background: #eef2fb;
}
QListWidget::item:selected {
    background: #dbe6fd;
    color: #1a1f2b;
}
QTreeWidget, QTreeView, QTableWidget {
    background: #ffffff;
    border: 1px solid #e3e6ea;
    border-radius: 8px;
    alternate-background-color: #f7f9fc;
    selection-background-color: #dbe6fd;
    selection-color: #1a1f2b;
    outline: none;
}
QTreeWidget::item, QTreeView::item, QTableWidget::item {
    padding: 5px 6px;
    border: none;
}
QTreeWidget::item:hover, QTableWidget::item:hover {
    background: #eef2fb;
}
QHeaderView::section {
    background: #f0f2f5;
    color: #5a6472;
    border: none;
    border-bottom: 1px solid #e3e6ea;
    padding: 6px 8px;
    font-weight: 600;
}
/* 预览文本 */
QTextEdit, QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #e3e6ea;
    border-radius: 8px;
    padding: 8px;
    selection-background-color: #dbe6fd;
}
/* 按钮 */
QPushButton {
    background: #ffffff;
    border: 1px solid #d5dae2;
    border-radius: 6px;
    padding: 7px 16px;
    color: #2b3445;
}
QPushButton:hover {
    background: #eef2fb;
    border-color: #b9c8ee;
}
QPushButton:pressed {
    background: #dde6fa;
}
QPushButton:disabled {
    color: #b0b7c3;
    background: #f5f6f8;
}
QPushButton[primary="true"] {
    background: #2563eb;
    border: 1px solid #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QPushButton[primary="true"]:hover {
    background: #1d4fd7;
}
QPushButton[primary="true"]:pressed {
    background: #1a45be;
}
QPushButton[primary="true"]:disabled {
    background: #a5bcF5;
    border-color: #a5bcf5;
}
/* 输入框 */
QLineEdit {
    background: #ffffff;
    border: 1px solid #d5dae2;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #dbe6fd;
}
QLineEdit:focus {
    border-color: #2563eb;
}
/* 页签 */
QTabBar::tab {
    background: transparent;
    color: #5a6472;
    padding: 7px 18px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: #2563eb;
    border-bottom: 2px solid #2563eb;
    font-weight: 600;
}
QTabBar::tab:hover {
    color: #2563eb;
}
/* 进度条 */
QProgressBar {
    background: #e8ebf0;
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: #2563eb;
    border-radius: 5px;
}
/* 状态栏 */
QStatusBar {
    background: #ffffff;
    border-top: 1px solid #e3e6ea;
    color: #5a6472;
}
/* 滚动条 */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #c9cfda;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #aab2c0;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: #c9cfda;
    border-radius: 5px;
    min-width: 30px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
/* 复选框 */
QCheckBox {
    spacing: 6px;
}
/* 提示框文字色 */
QMessageBox QLabel {
    color: #2b3445;
}
/* 工具提示 */
QToolTip {
    background: #2b3445;
    color: #ffffff;
    border: none;
    padding: 5px 8px;
    border-radius: 4px;
}
"""
