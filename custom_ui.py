import time
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, 
    QTableWidgetItem, QComboBox, QHeaderView, QAbstractItemView, QGraphicsView,
    QColorDialog, QApplication, QGraphicsRectItem, QWidget
)
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QFont, QColor, QPainter, QPen
from PyQt6.QtWidgets import QGraphicsTextItem, QGraphicsItemGroup, QGraphicsItem

from utils import get_rainbow_html, generate_colored_html

class BpmTapperDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BPM確認ツール (Tapper)")
        self.resize(300, 250)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint) 
        self.taps = []
        self.current_bpm = 0
        layout = QVBoxLayout(self)
        
        self.lbl_bpm = QLabel("--- BPM")
        self.lbl_bpm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_bpm.setFont(QFont("Meiryo", 36, QFont.Weight.Bold))
        layout.addWidget(self.lbl_bpm)
        
        self.btn_tap = QPushButton("TAP (曲に合わせてクリック)")
        self.btn_tap.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold; font-size: 20px; padding: 20px;")
        self.btn_tap.clicked.connect(self.on_tap)
        layout.addWidget(self.btn_tap)
        
        self.btn_reset = QPushButton("リセット (最初からやり直す)")
        self.btn_reset.setStyleSheet("background-color: #6b7280; color: white; padding: 10px; font-weight: bold;")
        self.btn_reset.clicked.connect(self.reset_taps)
        layout.addWidget(self.btn_reset)
        
        self.btn_copy = QPushButton("BPMの数値をコピー")
        self.btn_copy.setStyleSheet("padding: 10px; font-weight: bold;")
        self.btn_copy.clicked.connect(self.copy_bpm)
        layout.addWidget(self.btn_copy)

    def on_tap(self):
        now = time.time()
        if self.taps and now - self.taps[-1] > 3.0:
            self.taps = []
            
        self.taps.append(now)
        if len(self.taps) > 10: self.taps.pop(0)
        
        if len(self.taps) >= 2:
            avg_interval = sum([self.taps[i] - self.taps[i-1] for i in range(1, len(self.taps))]) / (len(self.taps)-1)
            if avg_interval > 0:
                self.current_bpm = int(round(60.0 / avg_interval))
                self.lbl_bpm.setText(f"{self.current_bpm} BPM")
                self.btn_copy.setText("BPMの数値をコピー")

    def reset_taps(self):
        self.taps = []
        self.current_bpm = 0
        self.lbl_bpm.setText("--- BPM")
        self.btn_copy.setText("BPMの数値をコピー")

    def copy_bpm(self):
        if self.current_bpm > 0:
            QApplication.clipboard().setText(str(self.current_bpm))
            self.btn_copy.setText("コピーしました！")

class ColorMapEditorDialog(QDialog):
    def __init__(self, current_map, parent=None):
        super().__init__(parent)
        self.setWindowTitle("カラーマップ(色判定)の編集")
        self.resize(650, 500)
        self.color_map = current_map.copy()
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["判定文字列", "種類", "色設定", "プレビュー"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(40) 
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        self.table.itemChanged.connect(self.on_item_changed)
        layout.addWidget(self.table)
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("＋ 追加")
        self.btn_add.clicked.connect(self.add_row)
        self.btn_del = QPushButton("－ 削除")
        self.btn_del.clicked.connect(self.delete_row)
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_del)
        layout.addLayout(btn_layout)
        self.btn_save = QPushButton("保存して反映")
        self.btn_save.clicked.connect(self.save_and_close)
        layout.addWidget(self.btn_save)
        self.populate_table()

    def populate_table(self):
        self.table.setRowCount(0)
        for name, cfg in self.color_map.items(): self.insert_row(name, cfg)

    def insert_row(self, name, cfg):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.blockSignals(True)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        combo = QComboBox()
        combo.addItems(["単色", "虹色"])
        combo.setCurrentText("虹色" if cfg.get("type", "color") == "rainbow" else "単色")
        combo.currentIndexChanged.connect(self.on_type_changed)
        self.table.setCellWidget(row, 1, combo)
        color_item = QTableWidgetItem()
        color_item.setFlags(color_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 2, color_item)
        preview_label = QLabel()
        preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_label.setStyleSheet("background-color: black; border-radius: 4px; margin: 2px;")
        self.table.setCellWidget(row, 3, preview_label)
        self.table.blockSignals(False)
        self.update_row_visuals(row, cfg.get("value", [255, 255, 255]))

    def on_type_changed(self):
        combo = self.sender()
        if combo:
            for row in range(self.table.rowCount()):
                if self.table.cellWidget(row, 1) == combo:
                    self.update_row_visuals(row)
                    break

    def on_item_changed(self, item):
        if item.column() == 0: self.update_row_visuals(item.row())

    def update_row_visuals(self, row, rgb=None):
        name_item = self.table.item(row, 0)
        if not name_item: return
        name = name_item.text()
        type_str = self.table.cellWidget(row, 1).currentText()
        color_item = self.table.item(row, 2)
        if type_str == "虹色":
            color_item.setText("(自動生成)")
            color_item.setBackground(QColor(60, 60, 60))
            color_item.setForeground(QColor("white"))
            preview_inner_html = get_rainbow_html(name)
        else:
            if rgb is None:
                try: rgb = list(map(int, color_item.text().split(",")))
                except: rgb = [255, 255, 255]
            color_item.setText(f"{rgb[0]}, {rgb[1]}, {rgb[2]}")
            color_item.setBackground(QColor(*rgb))
            text_color = "white" if sum(rgb)/3 < 128 else "black"
            color_item.setForeground(QColor(text_color))
            preview_inner_html = f'<span style="color: rgb({rgb[0]},{rgb[1]},{rgb[2]});">{name}</span>'
        self.table.cellWidget(row, 3).setText(f'<div align="center" style="font-family: Meiryo; font-size: 16px; font-weight: bold; color: white;">{preview_inner_html}</div>')

    def on_cell_double_clicked(self, row, col):
        if col == 2 and self.table.cellWidget(row, 1).currentText() == "単色":
            r, g, b = map(int, self.table.item(row, col).text().split(","))
            color = QColorDialog.getColor(QColor(r, g, b), self, "色を選択")
            if color.isValid(): self.update_row_visuals(row, [color.red(), color.green(), color.blue()])

    def add_row(self): self.insert_row("新規の設定", {"type": "color", "value": [255, 255, 255]})
    
    def delete_row(self):
        for row in sorted(set([item.row() for item in self.table.selectedItems()]), reverse=True):
            self.table.removeRow(row)

    def save_and_close(self):
        new_map = {}
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text().strip()
            if not name: continue
            if self.table.cellWidget(row, 1).currentText() == "虹色":
                new_map[name] = {"type": "rainbow", "value": None}
            else:
                r, g, b = map(int, self.table.item(row, 2).text().split(","))
                new_map[name] = {"type": "color", "value": [r, g, b]}
        self.color_map = new_map
        self.accept()


# ---------------------------------------------------------
# ドラッグ時のスナップ処理
# ---------------------------------------------------------
SNAP_THRESHOLD = 12  # シーン座標(px)。Altキーを押しながらドラッグするとスナップ無効

def snap_anchor(moving, anchor):
    """ 移動中アイテムの基準点(anchor)を、キャンバス中央や他アイテムの中心に吸着させた座標を返す """
    scene = moving.scene()
    if scene is None or not moving.isSelected():
        return anchor
    if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
        return anchor
    if QApplication.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
        return anchor
    if len(scene.selectedItems()) != 1:
        return anchor

    xs, ys = [960.0], [540.0]
    for it in scene.items():
        if it is moving:
            continue
        if isinstance(it, MappedTextItem):
            xs.append(it.pos().x()); ys.append(it.pos().y())
        elif isinstance(it, SnapTextItem) and it.isVisible():
            c = it.pos() + it.boundingRect().center()
            xs.append(c.x()); ys.append(c.y())

    x, y = anchor.x(), anchor.y()
    best_x = min(xs, key=lambda t: abs(t - x))
    best_y = min(ys, key=lambda t: abs(t - y))
    if abs(best_x - x) <= SNAP_THRESHOLD: x = best_x
    if abs(best_y - y) <= SNAP_THRESHOLD: y = best_y
    return QPointF(x, y)


class SnapTextItem(QGraphicsTextItem):
    """ ドラッグ時にスナップするテキストアイテム (共通カウント表示用) """
    def __init__(self, text=""):
        super().__init__(text)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            center = self.boundingRect().center()
            value = snap_anchor(self, value + center) - center
        return super().itemChange(change, value)

class CountTextItem(SnapTextItem):
    def __init__(self, main_app, target_item):
        super().__init__()
        self.main_app = main_app
        self.target_item = target_item
        self.setDefaultTextColor(QColor("yellow"))
        self.setFont(QFont("Meiryo", int(60 * 0.7)))
        self.setZValue(10)
        self.setPlainText("カウント")
        self.setVisible(False)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            if self.isSelected():
                center = self.boundingRect().center()
                new_pos = snap_anchor(self, value + center) - center
                value = new_pos
                offset_x = new_pos.x() - self.target_item.pos().x()
                offset_y = new_pos.y() - self.target_item.pos().y()
                self.main_app.shared_count_offset = (offset_x, offset_y)
                self.main_app.sync_all_counts(exclude_item=self)
                return value
        return super().itemChange(change, value)

class MappedTextItem(QGraphicsItemGroup):
    def __init__(self, main_app, item_type="static", default_text="新規テキスト"):
        super().__init__()
        self.main_app = main_app
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        
        self.selection_rect = QGraphicsRectItem(self)
        pen = QPen(QColor(0, 255, 255))
        pen.setWidth(3)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.selection_rect.setPen(pen)
        self.selection_rect.hide()

        self.item_type = item_type
        self.static_text = default_text
        self.col_idx = -1
        self.init_mode = "blackout" 
        self.init_text = ""
        self.init_row = -1
        self.init_col = -1
        self.font_size = 60
        self.center_item = QGraphicsTextItem()
        self.left_item = QGraphicsTextItem()
        self.right_item = QGraphicsTextItem()
        self.arrow_item = QGraphicsTextItem()
        self.count_item = CountTextItem(main_app, self)
        for item in [self.center_item, self.left_item, self.right_item, self.arrow_item]:
            self.addToGroup(item)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            value = snap_anchor(self, value)
            if self.count_item and self.count_item.isVisible():
                offset_x, offset_y = self.main_app.shared_count_offset
                self.count_item.setPos(value.x() + offset_x, value.y() + offset_y)
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.selection_rect.setVisible(bool(value))
            
        return super().itemChange(change, value)

    def update_content(self, mode, color_map, text1="", text2="", count_mode="none"):
        self.selection_rect.hide()
        
        for item in [self.center_item, self.left_item, self.right_item, self.arrow_item]: item.setHtml("")
        self.count_item.setPlainText("")
        
        if mode == "single":
            self.center_item.setHtml(generate_colored_html(text1, self.font_size, color_map))
            r = self.center_item.boundingRect()
            self.center_item.setPos(-r.width() / 2, -r.height() / 2)
        elif mode == "dual":
            self.left_item.setHtml(generate_colored_html(text1, self.font_size, color_map))
            self.right_item.setHtml(generate_colored_html(text2, self.font_size, color_map))
            self.arrow_item.setHtml(f'<div align="center" style="font-family: Meiryo; font-size: {self.font_size}px; color: white;">▶</div>')
            a_r = self.arrow_item.boundingRect()
            self.arrow_item.setPos(-a_r.width() / 2, -a_r.height() / 2)
            l_r = self.left_item.boundingRect()
            self.left_item.setPos(-a_r.width() / 2 - l_r.width() - 20, -l_r.height() / 2)
            r_r = self.right_item.boundingRect()
            self.right_item.setPos(a_r.width() / 2 + 20, -r_r.height() / 2)
            
            if count_mode in ["above", "below"]:
                self.count_item.setPlainText("カウント")
                self.count_item.setFont(QFont("Meiryo", int(self.font_size * 0.7)))
                c_r = self.count_item.boundingRect()
                if count_mode == "above": self.count_item.setPos(-c_r.width() / 2, -a_r.height() / 2 - c_r.height() - 10)
                else: self.count_item.setPos(-c_r.width() / 2, a_r.height() / 2 + 10)

        rect = QRectF()
        for child in [self.center_item, self.left_item, self.right_item, self.arrow_item]:
            if child.isVisible() and child.toPlainText().strip():
                child_rect = child.mapToParent(child.boundingRect()).boundingRect()
                rect = rect.united(child_rect)
                
        if rect.isNull():
            rect = QRectF(-50, -20, 100, 40)
            
        rect.adjust(-15, -15, 15, 15)
        self.selection_rect.setRect(rect)
        
        if self.isSelected():
            self.selection_rect.show()

class PreviewView(QGraphicsView):
    def __init__(self, scene):
        super().__init__(scene)
        self.setBackgroundBrush(QColor("#242424"))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)


# ---------------------------------------------------------
# チュートリアル用オーバーレイウィジェット
# ---------------------------------------------------------
class TutorialOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        
        self.steps = [
            "【ようこそ！チュートリアル (1/6)】\n\nまずは左上の「Excelファイルを読み込む」ボタンから、\nタイムテーブルが書かれたExcelファイルを開きましょう。",
            "【列の設定 (2/6)】\n\n表の列（A, B, C...）をクリックして選択し、\n右側の設定パネルから「選択列を『分』に設定」「『秒』に設定」を押して、\n時間を読み取る列を指定します。",
            "【範囲の設定 (3/6)】\n\n表の中から、使用する開始行を選んで「開始行に設定」を、\n終了行を選んで「終了行に設定」を押します。",
            "【カウントとBPM (4/6)】\n\n右側のパネルで、各行の「BPM」と「カウント数」を設定できます。\n「↑ 一つ前の行の設定をコピー」を使うと連続入力が簡単です！",
            "【文字の配置 (5/6)】\n\n「＋ 新規テキスト」から文字を追加し、プレビュー画面で自由に配置します。\n右下のパネルで、Excelのデータを参照するか、固定文字にするかを選べます。",
            "【書き出し (6/6)】\n\n準備ができたら、右上の「音声(mp3/wav)を選択」から音源を選び、\n「プロジェクト(XML)を書き出し」を押して完了です！\n(背景動画 count.mp4 は自動認識されます)\n\n※このチュートリアルはメニューの「ヘルプ」からいつでも見られます。"
        ]
        self.current_step = 0
        
        self.label = QLabel(self)
        self.label.setStyleSheet("""
            background-color: transparent;
            color: white;
            font-size: 26px;
            font-weight: bold;
            border: none;
        """)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.update_step()

    def paintEvent(self, event):
        """ 背景を確実に暗転させるための描画処理 """
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 200)) # 半透明の黒で塗りつぶす
        super().paintEvent(event)
        
    def update_step(self):
        if self.current_step < len(self.steps):
            text = self.steps[self.current_step] + "\n\n(画面のどこかをクリックして次へ ▶)"
            self.label.setText(text)
            self.label.adjustSize()
            self.resize_and_center()
        else:
            self.hide()
            self.deleteLater()
            
    def mousePressEvent(self, event):
        self.current_step += 1
        self.update_step()
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resize_and_center()
        
    def resize_and_center(self):
        if self.parent():
            self.resize(self.parent().size())
            self.label.move(
                (self.width() - self.label.width()) // 2,
                (self.height() - self.label.height()) // 2
            )