import sys
import os
import json
import pandas as pd
import traceback
import shutil
import webbrowser
import urllib.request

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QFileDialog, 
    QMessageBox, QGroupBox, QRadioButton, QLineEdit, QComboBox, QFormLayout, 
    QSpinBox, QMenuBar, QMenu, QGraphicsScene, QGraphicsTextItem, QGraphicsItem,
    QAbstractItemView, QAbstractSpinBox, QTextEdit
)
from PyQt6.QtCore import Qt, QRectF, QSettings, QThread, pyqtSignal, QEvent
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush, QPen, QAction, QImage

# 他のファイルからインポート
from utils import load_color_map, save_color_map, encode_path_for_premiere, escape_xml
from custom_ui import BpmTapperDialog, ColorMapEditorDialog, MappedTextItem, SnapTextItem, PreviewView, TutorialOverlay

# =========================================================
# アプリの設定
# =========================================================
APP_VERSION = "1.0.0"
GITHUB_REPO = "yamatyann/ExcelToProject" 
# =========================================================

# ---------------------------------------------------------
# 非同期でアップデートを確認するスレッド
# ---------------------------------------------------------
class UpdateChecker(QThread):
    # 最新バージョンと、ダウンロードページのURLを送るシグナル
    update_available = pyqtSignal(str, str)

    def run(self):
        if GITHUB_REPO == "yamatyann/ExcelToProject":
            return # リポジトリ名が設定されていない場合はスキップ

        try:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            # GitHub APIを叩く (タイムアウトは3秒に設定し、長引かないようにする)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=3) as response:
                data = json.loads(response.read().decode('utf-8'))
                latest_version = data.get("tag_name", "").lstrip("v")
                release_url = data.get("html_url", "")

                current_version = APP_VERSION.lstrip("v")

                # バージョン文字列を数値のリストに変換して比較 (例: "1.0.1" -> [1, 0, 1])
                def parse_v(v_str):
                    return [int(x) for x in v_str.split(".") if x.isdigit()]

                if parse_v(latest_version) > parse_v(current_version):
                    self.update_available.emit(latest_version, release_url)
        except Exception:
            # ネットが繋がっていない、またはAPI制限などの場合はエラーを出さずに静かに終了
            pass

class ExcelToProjectApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"照明オペレーション エディタ (XML連携版) v{APP_VERSION}")
        self.resize(1600, 850)
        self.df = None
        self.excel_path = "" 
        self.start_row = None
        self.end_row = None
        self.current_step = -1
        self.selected_item = None
        self.color_map = load_color_map()
        self.canvas_bg = None 
        self.is_exporting = False 
        self.bpm_tapper_dialog = None
        self.row_count_settings = {}
        self.shared_count_offset = (0, -80)
        
        self.col_min = -1
        self.col_sec = -1
        
        self.audio_path = ""
        if getattr(sys, 'frozen', False):
            # exeとして実行されている場合は、exe本体があるディレクトリを取得
            base_dir = os.path.dirname(sys.executable)
        else:
            # Pythonスクリプトとして実行されている場合は、スクリプトがあるディレクトリを取得
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.video_path = os.path.join(base_dir, "count.mp4")
        # --------------

        if not os.path.exists(self.video_path):
            self.video_path = ""

        self.setup_ui()
        self.setup_default_scene()
        QApplication.instance().installEventFilter(self)

        # ----------------------------------------------------
        # 初回起動時のチュートリアル表示
        # ----------------------------------------------------
        self.settings = QSettings("ExcelToProjectOrg", "ExcelToProjectApp")
        if not self.settings.value("tutorial_shown", type=bool):
            self.start_tutorial()
            self.settings.setValue("tutorial_shown", True)

        # ----------------------------------------------------
        # 裏側でアップデート確認を開始
        # ----------------------------------------------------
        self.update_checker = UpdateChecker()
        self.update_checker.update_available.connect(self.show_update_notification)
        self.update_checker.start()

    def eventFilter(self, obj, event):
        """ ←/→キーで前後の行へ移動 (文字入力や表の操作中は邪魔しない) """
        if event.type() == QEvent.Type.KeyPress and self.isActiveWindow()                 and event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right)                 and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            focus = QApplication.focusWidget()
            if not isinstance(focus, (QLineEdit, QAbstractSpinBox, QComboBox, QAbstractItemView, QTextEdit)):
                if event.key() == Qt.Key.Key_Left: self.step_prev()
                else: self.step_next()
                return True
        return super().eventFilter(obj, event)

    def show_update_notification(self, latest_version, url):
        """ アップデートが見つかった際に呼ばれる処理 """
        reply = QMessageBox.information(
            self,
            "アップデートのお知らせ",
            f"新しいバージョン (v{latest_version}) が公開されています。\n\n"
            f"現在のバージョン: v{APP_VERSION}\n\n"
            f"ダウンロードページを開きますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            webbrowser.open(url)

    def setup_ui(self):
        menubar = self.menuBar()
        
        menu_file = menubar.addMenu("ファイル(&F)")
        action_open = QAction("プロジェクトを開く...", self)
        action_open.triggered.connect(self.load_project)
        menu_file.addAction(action_open)
        
        action_save = QAction("プロジェクトを保存...", self)
        action_save.triggered.connect(self.save_project)
        menu_file.addAction(action_save)

        menu_settings = menubar.addMenu("設定(&S)")
        action_edit_color = QAction("カラーマップを編集...", self)
        action_edit_color.triggered.connect(self.open_color_editor)
        menu_settings.addAction(action_edit_color)
        
        menu_tools = menubar.addMenu("ツール(&T)")
        action_bpm_tapper = QAction("BPM確認ツール (Tapper)...", self)
        action_bpm_tapper.triggered.connect(self.open_bpm_tapper)
        menu_tools.addAction(action_bpm_tapper)

        menu_help = menubar.addMenu("ヘルプ(&H)")
        action_tutorial = QAction("チュートリアルを見る", self)
        action_tutorial.triggered.connect(self.start_tutorial)
        menu_help.addAction(action_tutorial)
        
        action_bug_report = QAction("バグ報告 / フィードバック...", self)
        action_bug_report.triggered.connect(self.open_feedback_form)
        menu_help.addAction(action_bug_report)
        
        action_about = QAction("バージョン情報", self)
        action_about.triggered.connect(self.show_about)
        menu_help.addAction(action_about)

        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 1920, 1080) 
        self.scene.selectionChanged.connect(self.on_selection_changed)
        self.view = PreviewView(self.scene)
        self.setCentralWidget(self.view)
        self.draw_default_background()

        self.dock_excel = QDockWidget("① Excel読込・範囲/列設定", self)
        excel_widget = QWidget()
        excel_layout = QVBoxLayout(excel_widget)
        self.btn_load = QPushButton("Excelファイルを読み込む")
        self.btn_load.clicked.connect(self.action_load_excel)
        excel_layout.addWidget(self.btn_load)
        self.table_excel = QTableWidget()
        excel_layout.addWidget(self.table_excel)
        group_range = QGroupBox("使用する行の範囲")
        layout_range = QVBoxLayout()
        box_start = QHBoxLayout()
        self.btn_set_start = QPushButton("選択行を開始行に設定")
        self.btn_set_start.clicked.connect(self.set_start_row)
        self.lbl_start = QLabel("未設定")
        box_start.addWidget(self.btn_set_start)
        box_start.addWidget(self.lbl_start)
        layout_range.addLayout(box_start)
        box_end = QHBoxLayout()
        self.btn_set_end = QPushButton("選択行を終了行に設定")
        self.btn_set_end.clicked.connect(self.set_end_row)
        self.lbl_end = QLabel("未設定")
        box_end.addWidget(self.btn_set_end)
        box_end.addWidget(self.lbl_end)
        layout_range.addLayout(box_end)
        group_range.setLayout(layout_range)
        excel_layout.addWidget(group_range)
        group_map = QGroupBox("タイムコード読み取り列の設定")
        map_layout = QVBoxLayout()
        box_min = QHBoxLayout()
        self.btn_set_min = QPushButton("選択列を「分」に設定")
        self.btn_set_min.clicked.connect(self.set_min_col)
        self.lbl_min_col = QLabel("未設定")
        self.btn_clear_min = QPushButton("解除")
        self.btn_clear_min.clicked.connect(lambda: self.clear_col("min"))
        box_min.addWidget(self.btn_set_min)
        box_min.addWidget(self.lbl_min_col)
        box_min.addWidget(self.btn_clear_min)
        map_layout.addLayout(box_min)

        box_sec = QHBoxLayout()
        self.btn_set_sec = QPushButton("選択列を「秒」に設定")
        self.btn_set_sec.clicked.connect(self.set_sec_col)
        self.lbl_sec_col = QLabel("未設定")
        self.btn_clear_sec = QPushButton("解除")
        self.btn_clear_sec.clicked.connect(lambda: self.clear_col("sec"))
        box_sec.addWidget(self.btn_set_sec)
        box_sec.addWidget(self.lbl_sec_col)
        box_sec.addWidget(self.btn_clear_sec)
        map_layout.addLayout(box_sec)
        group_map.setLayout(map_layout)
        excel_layout.addWidget(group_map)
        self.dock_excel.setWidget(excel_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_excel)

        self.dock_export = QDockWidget("⑤ 編集ソフト連携 (XML出力)", self)
        export_widget = QWidget()
        export_layout = QVBoxLayout(export_widget)
        
        box_audio = QHBoxLayout()
        self.btn_audio = QPushButton("音声(mp3/wav)を選択")
        self.btn_audio.clicked.connect(self.select_audio)
        self.lbl_audio = QLabel("未選択")
        box_audio.addWidget(self.btn_audio)
        box_audio.addWidget(self.lbl_audio)
        export_layout.addLayout(box_audio)
        
        group_video = QGroupBox("背景動画 (自動認識)")
        v_layout = QVBoxLayout()
        self.lbl_video = QLabel()
        if self.video_path:
            self.lbl_video.setText("✅ count.mp4 を認識しました")
            self.lbl_video.setStyleSheet("color: #10b981; font-weight: bold;")
        else:
            self.lbl_video.setText("❌ count.mp4 が同じフォルダにありません")
            self.lbl_video.setStyleSheet("color: #ef4444; font-weight: bold;")
        v_layout.addWidget(self.lbl_video)
        group_video.setLayout(v_layout)
        export_layout.addWidget(group_video)


        self.btn_export = QPushButton("▶ プロジェクト(XML)を書き出し")
        self.btn_export.setStyleSheet("background-color: #10b981; color: white; font-weight: bold; padding: 15px;")
        self.btn_export.clicked.connect(self.export_project)
        export_layout.addWidget(self.btn_export)
        
        export_layout.addStretch()
        self.dock_export.setWidget(export_widget)

        self.dock_count = QDockWidget("④ カウント＆BPM設定", self)
        count_widget = QWidget()
        count_layout = QVBoxLayout(count_widget)
        group_pos = QGroupBox("表示レイアウト")
        pos_form = QFormLayout()
        self.combo_count_pos = QComboBox()
        self.combo_count_pos.addItems(["1箇所にまとめて表示 (自由に移動)", "各指示に紐づけて表示 (連動して移動)"])
        self.combo_count_pos.currentIndexChanged.connect(self.update_preview)
        pos_form.addRow("カウント位置:", self.combo_count_pos)
        group_pos.setLayout(pos_form)
        count_layout.addWidget(group_pos)
        
        self.group_row_settings = QGroupBox("現在の行のカウント設定")
        row_form = QFormLayout()
        self.line_bpm = QLineEdit()
        self.line_bpm.setPlaceholderText("例: 120")
        self.line_bpm.textChanged.connect(self.save_row_count_settings)
        row_form.addRow("BPM:", self.line_bpm)
        self.spin_count = QSpinBox()
        self.spin_count.setRange(0, 32)
        self.spin_count.setValue(0)
        self.spin_count.valueChanged.connect(self.save_row_count_settings)
        row_form.addRow("カウント数:", self.spin_count)

        self.btn_copy_prev = QPushButton("↑ 一つ前の行の設定をコピー")
        self.btn_copy_prev.clicked.connect(self.copy_prev_row_settings)
        row_form.addRow("", self.btn_copy_prev)

        self.group_row_settings.setLayout(row_form)
        count_layout.addWidget(self.group_row_settings)
        count_layout.addStretch()
        self.dock_count.setWidget(count_widget)

        self.dock_inspector = QDockWidget("② テキスト配置・プロパティ", self)
        inspector_widget = QWidget()
        self.inspector_layout = QVBoxLayout(inspector_widget)
        box_text_ops = QHBoxLayout()
        self.btn_add_text = QPushButton("＋ 新規テキスト")
        self.btn_add_text.clicked.connect(self.add_new_text_item)
        self.btn_del_text = QPushButton("🗑 選択中を削除")
        self.btn_del_text.clicked.connect(self.delete_selected_text_item)
        box_text_ops.addWidget(self.btn_add_text)
        box_text_ops.addWidget(self.btn_del_text)
        self.inspector_layout.addLayout(box_text_ops)
        
        self.prop_group = QGroupBox("選択中のアイテム設定")
        prop_form = QFormLayout()
        self.combo_type = QComboBox()
        self.combo_type.addItems(["固定テキスト", "ストップウォッチ (秒数)", "Excelデータ"])
        self.combo_type.currentIndexChanged.connect(self.apply_properties_to_item)
        prop_form.addRow("種類:", self.combo_type)
        self.line_static = QLineEdit()
        self.line_static.textChanged.connect(self.apply_properties_to_item)
        prop_form.addRow("表示文字:", self.line_static)
        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(10, 300)
        self.spin_font_size.setValue(60)
        self.spin_font_size.valueChanged.connect(self.apply_properties_to_item)
        prop_form.addRow("文字サイズ:", self.spin_font_size)
        
        box_ref = QHBoxLayout()
        self.btn_set_ref = QPushButton("選択列を参照")
        self.btn_set_ref.clicked.connect(self.set_item_ref_col)
        self.lbl_ref_col = QLabel("未設定")
        box_ref.addWidget(self.btn_set_ref)
        box_ref.addWidget(self.lbl_ref_col)
        prop_form.addRow("参照列:", box_ref)
        
        self.prop_group.setLayout(prop_form)
        self.inspector_layout.addWidget(self.prop_group)

        self.init_group = QGroupBox("曲開始前の状態 (NOW側)")
        init_layout = QVBoxLayout()
        self.radio_blackout = QRadioButton("暗転 (「暗転」と表示)")
        self.radio_blackout.toggled.connect(self.apply_properties_to_item)
        init_layout.addWidget(self.radio_blackout)
        box_cell = QHBoxLayout()
        self.radio_cell = QRadioButton("表のセル:")
        self.radio_cell.toggled.connect(self.apply_properties_to_item)
        self.btn_set_cell = QPushButton("選択セルを登録")
        self.btn_set_cell.clicked.connect(self.set_item_init_cell)
        self.lbl_cell = QLabel("未設定")
        box_cell.addWidget(self.radio_cell)
        box_cell.addWidget(self.btn_set_cell)
        box_cell.addWidget(self.lbl_cell)
        init_layout.addLayout(box_cell)
        box_input = QHBoxLayout()
        self.radio_input = QRadioButton("自由入力:")
        self.radio_input.toggled.connect(self.apply_properties_to_item)
        self.line_input = QLineEdit()
        self.line_input.textChanged.connect(self.apply_properties_to_item)
        box_input.addWidget(self.radio_input)
        box_input.addWidget(self.line_input)
        init_layout.addLayout(box_input)
        self.init_group.setLayout(init_layout)
        self.inspector_layout.addWidget(self.init_group)

        self.inspector_layout.addStretch()
        self.dock_inspector.setWidget(inspector_widget)

        self.dock_timeline = QDockWidget("③ タイムライン (プレビュー操作)", self)
        time_widget = QWidget()
        time_layout = QHBoxLayout(time_widget)
        self.btn_prev = QPushButton("◀ 前の行へ (←)")
        self.btn_prev.clicked.connect(self.step_prev)
        self.lbl_status = QLabel("待機中 (Excel読込後、開始行/終了行を設定してください)")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_next = QPushButton("次の行へ (→) ▶")
        self.btn_next.clicked.connect(self.step_next)
        time_layout.addWidget(self.btn_prev)
        time_layout.addWidget(self.lbl_status, stretch=1)
        time_layout.addWidget(self.btn_next)
        self.dock_timeline.setWidget(time_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_timeline)

        # 右側は操作順 (② → ④ → ⑤) に上から並べる
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_count)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_export)

        self.prop_group.setEnabled(False)
        self.init_group.setEnabled(False)
        self.btn_del_text.setEnabled(False)
        self.group_row_settings.setEnabled(False)

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "プロジェクトを保存", "", "Lighting Project (*.ltpj)")
        if not path: return
        
        items_data = []
        for item in self.scene.items():
            if isinstance(item, MappedTextItem):
                items_data.append({
                    "x": item.pos().x(),
                    "y": item.pos().y(),
                    "item_type": item.item_type,
                    "static_text": item.static_text,
                    "col_idx": item.col_idx,
                    "init_mode": item.init_mode,
                    "init_text": item.init_text,
                    "init_row": item.init_row,
                    "init_col": item.init_col,
                    "font_size": item.font_size
                })

        data = {
            "excel_path": self.excel_path,
            "audio_path": self.audio_path,
            "start_row": self.start_row,
            "end_row": self.end_row,
            "col_min": self.col_min,
            "col_sec": self.col_sec,
            "row_count_settings": self.row_count_settings,
            "count_layout_mode": self.combo_count_pos.currentIndex(),
            "shared_count_offset": list(self.shared_count_offset),
            "global_count_pos": [self.global_count_item.pos().x(), self.global_count_item.pos().y()],
            "items": items_data
        }

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            QMessageBox.information(self, "保存完了", "プロジェクトを保存しました。")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存に失敗しました:\n{e}")

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "プロジェクトを開く", "", "Lighting Project (*.ltpj);;JSON Files (*.json)")
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            excel_path = data.get("excel_path", "")
            if excel_path and os.path.exists(excel_path):
                self._load_excel_from_path(excel_path)
            else:
                QMessageBox.warning(self, "警告", "保存されていたExcelファイルが見つかりません。必要であれば再度読み込んでください。")

            self.audio_path = data.get("audio_path", "")
            if self.audio_path:
                self.lbl_audio.setText(os.path.basename(self.audio_path))
            else:
                self.lbl_audio.setText("未選択")

            self.start_row = data.get("start_row")
            if self.start_row is not None:
                self.lbl_start.setText(f"{self.start_row + 1} 行目")
            self.end_row = data.get("end_row")
            if self.end_row is not None:
                self.lbl_end.setText(f"{self.end_row + 1} 行目")

            self.col_min = data.get("col_min", -1)
            self.col_sec = data.get("col_sec", -1)
            if self.col_min >= 0: self.lbl_min_col.setText(f"{self.get_col_letter(self.col_min)} 列")
            if self.col_sec >= 0: self.lbl_sec_col.setText(f"{self.get_col_letter(self.col_sec)} 列")

            saved_rc = data.get("row_count_settings", {})
            self.row_count_settings = {int(k): v for k, v in saved_rc.items()}

            self.combo_count_pos.blockSignals(True)
            self.combo_count_pos.setCurrentIndex(data.get("count_layout_mode", 0))
            self.combo_count_pos.blockSignals(False)
            offset = data.get("shared_count_offset")
            if offset:
                self.shared_count_offset = (offset[0], offset[1])
            gpos = data.get("global_count_pos")
            if gpos:
                self.global_count_item.setPos(gpos[0], gpos[1])

            items_to_remove = [item for item in self.scene.items() if isinstance(item, MappedTextItem)]
            for item in items_to_remove:
                if item.count_item:
                    self.scene.removeItem(item.count_item)
                self.scene.removeItem(item)

            for idata in data.get("items", []):
                item = MappedTextItem(self, idata.get("item_type", "static"), idata.get("static_text", ""))
                item.setPos(idata.get("x", 0), idata.get("y", 0))
                item.col_idx = idata.get("col_idx", -1)
                item.init_mode = idata.get("init_mode", "blackout")
                item.init_text = idata.get("init_text", "")
                item.init_row = idata.get("init_row", -1)
                item.init_col = idata.get("init_col", -1)
                item.font_size = idata.get("font_size", 60)
                self.scene.addItem(item)
                self.scene.addItem(item.count_item)

            self.current_step = -1
            self.update_preview()

        except Exception as e:
            QMessageBox.critical(self, "エラー", f"プロジェクトの読み込みに失敗しました:\n{e}")

    def start_tutorial(self):
        self.overlay = TutorialOverlay(self)
        self.overlay.show()

    def open_feedback_form(self):
        url = "https://forms.gle/KBD83L3A1Ue4xWs49"
        webbrowser.open(url)

    def show_about(self):
        QMessageBox.information(
            self, 
            "バージョン情報", 
            f"照明オペレーション エディタ (XML連携版)\n\n"
            f"現在のバージョン: {APP_VERSION}\n\n"
            f"バグ報告・フィードバックの際は、こちらのバージョン番号をフォームにご記入ください。"
        )

    def open_color_editor(self):
        d = ColorMapEditorDialog(self.color_map, self)
        if d.exec(): 
            self.color_map = d.color_map
            save_color_map(self.color_map) 
            self.update_preview() 

    def open_bpm_tapper(self):
        if not self.bpm_tapper_dialog: self.bpm_tapper_dialog = BpmTapperDialog(self)
        self.bpm_tapper_dialog.show()
        self.bpm_tapper_dialog.raise_()

    def select_audio(self):
        path, _ = QFileDialog.getOpenFileName(self, "音声ファイルを選択", "", "Audio Files (*.wav *.mp3 *.m4a *.aac)")
        if path:
            self.audio_path = path
            self.lbl_audio.setText(os.path.basename(path))

    def set_min_col(self):
        col = self.table_excel.currentColumn()
        if col >= 0:
            self.col_min = col
            self.lbl_min_col.setText(f"{self.get_col_letter(col)} 列")
            self.update_preview()

    def set_sec_col(self):
        col = self.table_excel.currentColumn()
        if col >= 0:
            self.col_sec = col
            self.lbl_sec_col.setText(f"{self.get_col_letter(col)} 列")
            self.update_preview()

    def clear_col(self, col_type):
        if col_type == "min":
            self.col_min = -1
            self.lbl_min_col.setText("未設定")
        else:
            self.col_sec = -1
            self.lbl_sec_col.setText("未設定")
        self.update_preview()

    def set_item_ref_col(self):
        if not self.selected_item or self.selected_item.item_type != "excel": return
        col = self.table_excel.currentColumn()
        if col >= 0:
            self.selected_item.col_idx = col
            self.sync_inspector_from_item()
            self.update_preview()

    def draw_default_background(self):
        self.scene.clear()
        self.canvas_bg = self.scene.addRect(0, 0, 1920, 1080, QPen(Qt.PenStyle.NoPen), QBrush(QColor("black")))
        self.canvas_bg.setZValue(-1)
        self.global_count_item = SnapTextItem("カウント")
        self.global_count_item.setDefaultTextColor(QColor("yellow"))
        self.global_count_item.setFont(QFont("Meiryo", 50))
        self.global_count_item.setPos(960 - self.global_count_item.boundingRect().width() / 2, 900)
        self.scene.addItem(self.global_count_item)
        self.global_count_item.hide()

    def setup_default_scene(self):
        org_item = MappedTextItem(self, "static", "団体名 (ここを編集)")
        org_item.setPos(350, 80)
        self.scene.addItem(org_item)
        self.scene.addItem(org_item.count_item)
        org_item.update_content("single", self.color_map, "団体名 (ここを編集)")

        sec_item = MappedTextItem(self, "stopwatch", "00:00:00")
        sec_item.setPos(1700, 80)
        self.scene.addItem(sec_item)
        self.scene.addItem(sec_item.count_item)
        sec_item.update_content("single", self.color_map, "00:00:00")

    def add_new_text_item(self):
        item = MappedTextItem(self, "excel", "NOW   ▶   NEXT")
        item.setPos(960, 540)
        self.scene.addItem(item)
        self.scene.addItem(item.count_item)
        self.scene.clearSelection()
        item.setSelected(True)
        self.update_preview()

    def delete_selected_text_item(self):
        if self.selected_item:
            if hasattr(self.selected_item, 'count_item') and self.selected_item.count_item:
                self.scene.removeItem(self.selected_item.count_item)
            self.scene.removeItem(self.selected_item)
            self.selected_item = None
            self.sync_inspector_from_item()
            self.update_preview()

    def on_selection_changed(self):
        selected = self.scene.selectedItems()
        real_selected = [s for s in selected if isinstance(s, MappedTextItem)]
        
        if len(real_selected) == 1:
            self.selected_item = real_selected[0]
            self.sync_inspector_from_item()
            self.btn_del_text.setEnabled(True)
        else:
            self.selected_item = None
            self.prop_group.setEnabled(False)
            self.init_group.setEnabled(False)
            self.btn_del_text.setEnabled(False)

    def sync_inspector_from_item(self):
        item = self.selected_item
        if not item: return
        self.combo_type.blockSignals(True)
        self.line_static.blockSignals(True)
        self.spin_font_size.blockSignals(True)
        self.prop_group.setEnabled(True)

        is_static = (item.item_type == "static")
        is_excel = (item.item_type == "excel")
        if is_static: self.combo_type.setCurrentIndex(0)
        elif item.item_type == "stopwatch": self.combo_type.setCurrentIndex(1)
        elif is_excel: self.combo_type.setCurrentIndex(2)

        self.line_static.setEnabled(is_static)
        self.line_static.setText(item.static_text)
        self.spin_font_size.setValue(item.font_size)
        
        self.btn_set_ref.setEnabled(is_excel)
        if is_excel:
            if item.col_idx >= 0:
                self.lbl_ref_col.setText(f"{self.get_col_letter(item.col_idx)} 列")
            else:
                self.lbl_ref_col.setText("未設定")
        else:
            self.lbl_ref_col.setText("-")

        self.init_group.setEnabled(is_excel)
        if is_excel:
            if item.init_mode == "blackout": self.radio_blackout.setChecked(True)
            elif item.init_mode == "cell": 
                self.radio_cell.setChecked(True)
                if item.init_row >= 0: self.lbl_cell.setText(f"登録済: {self.get_col_letter(item.init_col)}{item.init_row + 1}")
            elif item.init_mode == "text": 
                self.radio_input.setChecked(True)
                self.line_input.setText(item.init_text)

        self.combo_type.blockSignals(False)
        self.line_static.blockSignals(False)
        self.spin_font_size.blockSignals(False)

    def apply_properties_to_item(self):
        item = self.selected_item
        if not item: return
        idx = self.combo_type.currentIndex()
        if idx == 0: item.item_type = "static"
        elif idx == 1: item.item_type = "stopwatch"
        elif idx == 2: item.item_type = "excel"

        item.static_text = self.line_static.text()
        item.font_size = self.spin_font_size.value()

        if self.radio_blackout.isChecked(): item.init_mode = "blackout"
        elif self.radio_cell.isChecked(): item.init_mode = "cell"
        elif self.radio_input.isChecked():
            item.init_mode = "text"
            item.init_text = self.line_input.text()

        is_static = (item.item_type == "static")
        is_excel = (item.item_type == "excel")
        self.line_static.setEnabled(is_static)
        self.btn_set_ref.setEnabled(is_excel)
        self.init_group.setEnabled(is_excel)
        self.update_preview()

    def set_item_init_cell(self):
        if not self.selected_item or self.selected_item.item_type != "excel": return
        r, c = self.table_excel.currentRow(), self.table_excel.currentColumn()
        if r >= 0 and c >= 0:
            self.selected_item.init_row, self.selected_item.init_col = r, c
            self.selected_item.init_mode = "cell"
            self.radio_cell.setChecked(True)
            self.sync_inspector_from_item()
            self.update_preview()

    def _load_excel_from_path(self, path):
        try:
            self.df = pd.read_excel(path, header=None).fillna("")
            self.excel_path = path
            self.display_excel_data()
            return True
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"Excelの読込失敗:\n{str(e)}")
            return False

    def action_load_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "Excel選択", "", "Excel Files (*.xlsx *.xls)")
        if not path: return
        if self._load_excel_from_path(path):
            self.col_min = -1
            self.col_sec = -1
            self.lbl_min_col.setText("未設定")
            self.lbl_sec_col.setText("未設定")
            
            self.start_row, self.end_row = None, None
            self.lbl_start.setText("未設定")
            self.lbl_end.setText("未設定")
            self.current_step = -1
            self.update_preview()

    def display_excel_data(self):
        self.table_excel.clear()
        rows, cols = self.df.shape
        self.table_excel.setRowCount(rows)
        self.table_excel.setColumnCount(cols)
        self.table_excel.setHorizontalHeaderLabels([self.get_col_letter(c) for c in range(cols)])
        for r in range(rows):
            for c in range(cols):
                item = QTableWidgetItem(str(self.df.iloc[r, c]))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table_excel.setItem(r, c, item)
        self.table_excel.resizeColumnsToContents()

    def get_col_letter(self, col_idx):
        res = ""
        col_idx += 1
        while col_idx > 0:
            col_idx, rem = divmod(col_idx - 1, 26)
            res = chr(65 + rem) + res
        return res

    def set_start_row(self):
        row = self.table_excel.currentRow()
        if row >= 0:
            self.start_row = row
            self.lbl_start.setText(f"{row + 1} 行目")
            self.current_step = -1
            self.update_preview()

    def set_end_row(self):
        row = self.table_excel.currentRow()
        if row >= 0:
            self.end_row = row
            self.lbl_end.setText(f"{row + 1} 行目")
            self.update_preview()

    def step_prev(self):
        if self.start_row is not None and self.current_step > -1:
            self.current_step -= 1
            self.update_preview()

    def step_next(self):
        if self.start_row is not None and self.end_row is not None and self.current_step < (self.end_row - self.start_row):
            self.current_step += 1
            self.update_preview()

    def get_cell_safe(self, r, c):
        if self.df is None or r < 0 or r >= self.df.shape[0] or c < 0 or c >= self.df.shape[1]: return ""
        return str(self.df.iloc[r, c])

    def save_row_count_settings(self):
        if self.start_row is not None and self.current_step >= -1:
            current_r = self.start_row + self.current_step if self.current_step >= 0 else (self.start_row - 1)
            self.row_count_settings[current_r] = {"bpm": self.line_bpm.text(), "count": self.spin_count.value()}
            self.update_preview()

    def copy_prev_row_settings(self):
        if self.start_row is not None and self.current_step > -1:
            current_r = self.start_row + self.current_step
            prev_r = current_r - 1
            if prev_r in self.row_count_settings:
                setting = self.row_count_settings[prev_r]
                self.line_bpm.setText(setting.get("bpm", ""))
                self.spin_count.setValue(setting.get("count", 0))

    def sync_all_counts(self, exclude_item=None):
        offset_x, offset_y = self.shared_count_offset
        for item in self.scene.items():
            if isinstance(item, MappedTextItem) and item.item_type == "excel" and item.count_item and item.count_item != exclude_item:
                item.count_item.setPos(item.pos().x() + offset_x, item.pos().y() + offset_y)

    def set_counts_visible(self, visible):
        pos_idx = self.combo_count_pos.currentIndex()
        if pos_idx == 0:
            self.global_count_item.setVisible(visible)
            for item in self.scene.items():
                if isinstance(item, MappedTextItem) and item.count_item:
                    item.count_item.setVisible(False)
        else:
            self.global_count_item.setVisible(False)
            for item in self.scene.items():
                if isinstance(item, MappedTextItem) and item.count_item:
                    item.count_item.setVisible(visible)
        QApplication.processEvents()

    def set_counts_text(self, text):
        for item in self.scene.items():
            if isinstance(item, MappedTextItem) and item.count_item:
                item.count_item.setPlainText(text)
        if self.global_count_item:
            self.global_count_item.setPlainText(text)
        QApplication.processEvents()

    def set_base_items_visible(self, visible):
        for item in self.scene.items():
            if isinstance(item, MappedTextItem):
                item.center_item.setVisible(visible)
                item.left_item.setVisible(visible)
                item.right_item.setVisible(visible)
                item.arrow_item.setVisible(visible)

    def render_scene_to_png(self, filepath):
        image = QImage(1920, 1080, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.scene.render(painter, QRectF(0, 0, 1920, 1080), QRectF(0, 0, 1920, 1080))
        painter.end()
        image.save(filepath)

    def update_preview(self):
        if self.df is None or self.start_row is None or self.end_row is None:
            self.lbl_status.setText("待機中 (開始行と終了行を設定してください)")
            self.group_row_settings.setEnabled(False)
            has_count = False
        else:
            current_r = self.start_row + self.current_step if self.current_step >= 0 else (self.start_row - 1)
            self.lbl_status.setText("ステータス: [ 曲開始前 ]" if self.current_step == -1 else f"ステータス: 進行中 (Excel {current_r + 1} 行目)")
            self.group_row_settings.setEnabled(True)
            self.line_bpm.blockSignals(True); self.spin_count.blockSignals(True)
            setting = self.row_count_settings.get(current_r, {"bpm": "", "count": 0})
            self.line_bpm.setText(setting.get("bpm", ""))
            self.spin_count.setValue(setting.get("count", 0))
            self.line_bpm.blockSignals(False); self.spin_count.blockSignals(False)
            has_count = (setting.get("count", 0) > 0)

        pos_idx = self.combo_count_pos.currentIndex()
        global_count_show = False
        item_count_mode = False
        
        if not self.is_exporting and has_count:
            if pos_idx == 0: global_count_show = True
            else: item_count_mode = True
        
        self.global_count_item.setVisible(global_count_show)

        for item in self.scene.items():
            if not isinstance(item, MappedTextItem): continue
            
            if self.is_exporting and item.item_type == "stopwatch":
                item.update_content("single", self.color_map, "")
                item.count_item.setVisible(False)
                continue

            if item.item_type == "static":
                item.update_content("single", self.color_map, item.static_text)
                item.count_item.setVisible(False)
            elif item.item_type == "stopwatch":
                item.update_content("single", self.color_map, "00:00:00") 
                item.count_item.setVisible(False)
            elif item.item_type == "excel":
                if self.current_step == -1:
                    if item.init_mode == "blackout": now_text = "暗転"
                    elif item.init_mode == "text": now_text = item.init_text
                    elif item.init_mode == "cell": now_text = self.get_cell_safe(item.init_row, item.init_col)
                    next_text = self.get_cell_safe(self.start_row, item.col_idx) if self.start_row is not None and item.col_idx >= 0 else ""
                else:
                    current_r = self.start_row + self.current_step
                    if item.col_idx >= 0:
                        now_text = self.get_cell_safe(current_r, item.col_idx)
                        next_text = self.get_cell_safe(current_r + 1, item.col_idx) if current_r + 1 <= self.end_row else "END"
                    else:
                        now_text = "列 未設定"
                        next_text = "列 未設定"

                if not now_text and not next_text: item.update_content("single", self.color_map, "")
                else:
                    cmode = "none" if self.is_exporting else ("above" if pos_idx == 1 else "below")
                    item.update_content("dual", self.color_map, now_text, next_text, count_mode=cmode)
                
                item.count_item.setVisible(True if item_count_mode else False)

        if item_count_mode: self.sync_all_counts()

    # ==========================================
    # エクスポート ＆ FCPXML生成エンジン
    # ==========================================
    def get_seconds_from_row(self, row):
        minutes = 0
        seconds = 0
        if self.col_min >= 0:
            try: minutes = float(self.get_cell_safe(row, self.col_min))
            except: pass
        if self.col_sec >= 0:
            try: seconds = float(self.get_cell_safe(row, self.col_sec))
            except: pass
        return (minutes * 60) + seconds

    def export_project(self):
        if self.df is None or self.start_row is None or self.end_row is None:
            QMessageBox.warning(self, "エラー", "Excelを読み込み、開始行と終了行を設定してください。")
            return
            
        out_dir = QFileDialog.getExistingDirectory(self, "画像・コピーファイル・XMLの保存先を選択")
        if not out_dir: return

        fps = 30
        intro_offset_sec = 5.0

        dest_audio = ""
        dest_video = ""
        
        if self.audio_path and os.path.exists(self.audio_path):
            dest_audio = os.path.join(out_dir, os.path.basename(self.audio_path))
            if os.path.abspath(self.audio_path) != os.path.abspath(dest_audio):
                shutil.copy2(self.audio_path, dest_audio)
            else:
                dest_audio = self.audio_path
            
        if self.video_path and os.path.exists(self.video_path):
            dest_video = os.path.join(out_dir, os.path.basename(self.video_path))
            if os.path.abspath(self.video_path) != os.path.abspath(dest_video):
                shutil.copy2(self.video_path, dest_video)
            else:
                dest_video = self.video_path

        audio_duration = 0.0
        try:
            from mutagen.mp3 import MP3
            from mutagen.wave import WAVE
            if self.audio_path.lower().endswith('.mp3'):
                audio_info = MP3(self.audio_path)
                audio_duration = audio_info.info.length
            elif self.audio_path.lower().endswith('.wav'):
                audio_info = WAVE(self.audio_path)
                audio_duration = audio_info.info.length
        except ImportError:
            pass

        if audio_duration > 0:
            total_audio_time = audio_duration + intro_offset_sec + 30.0
        else:
            last_row_sec = self.get_seconds_from_row(self.end_row)
            total_audio_time = last_row_sec + intro_offset_sec + 30.0

        timeline_events = []
        current_time = 0.0
        max_step = self.end_row - self.start_row
        
        for step in range(-1, max_step + 1):
            if step < max_step:
                next_row = self.start_row + step + 1
                end_time = self.get_seconds_from_row(next_row) + intro_offset_sec
            else:
                end_time = total_audio_time
            
            duration = end_time - current_time
            if duration <= 0: 
                duration = 3.0 
                end_time = current_time + duration
                
            row_idx = self.start_row + step if step >= 0 else (self.start_row - 1)
            timeline_events.append({"step": step, "start": current_time, "end": end_time, "row_idx": row_idx})
            current_time = end_time 

        max_c = 0
        for r, c_set in self.row_count_settings.items():
            if c_set["count"] > max_c:
                max_c = c_set["count"]

        count_png_files = {}
        if max_c > 0:
            self.is_exporting = True
            if self.canvas_bg: self.canvas_bg.hide()
            
            self.set_base_items_visible(False)
            self.set_counts_visible(True)

            for num in range(1, max_c + 1):
                self.set_counts_text(str(num))
                cnt_filename = f"count_{num:02d}.png"
                cnt_path = os.path.join(out_dir, cnt_filename)
                self.render_scene_to_png(cnt_path)
                count_png_files[num] = cnt_filename

            self.set_base_items_visible(True)
            self.set_counts_visible(False)
            self.is_exporting = False


        orig_step = self.current_step
        self.scene.clearSelection() 
        self.is_exporting = True 
        if self.canvas_bg: self.canvas_bg.hide()

        base_clips_info = []   
        count_clips_info = []  
        
        for event in timeline_events:
            step = event["step"]
            self.current_step = step
            self.update_preview()
            
            self.set_counts_visible(False)
            base_filename = f"instruction_{step+2:03d}_base.png"
            base_path = os.path.join(out_dir, base_filename)
            self.render_scene_to_png(base_path)

            base_clips_info.append({
                "name": base_filename, "file": base_filename,
                "start": event["start"], "end": event["end"]
            })

            row_idx = event["row_idx"]
            c_set = self.row_count_settings.get(row_idx, None)
            c_num = c_set["count"] if c_set else 0
            bpm = float(c_set["bpm"]) if c_set and c_set["bpm"] else 120.0
            beat_sec = 60.0 / bpm if bpm > 0 else 0.5

            if c_num > 0:
                count_end_time = event["end"]
                count_start_time = count_end_time - (c_num * beat_sec)
                
                for i in range(c_num):
                    num_val = c_num - i
                    s = count_start_time + (i * beat_sec)
                    e = s + beat_sec
                    
                    actual_s = max(s, event["start"])
                    actual_e = min(e, event["end"])
                    if actual_e > actual_s:
                        count_clips_info.append({
                            "name": count_png_files[num_val], "file": count_png_files[num_val],
                            "start": actual_s, "end": actual_e
                        })

        self.is_exporting = False
        if self.canvas_bg: self.canvas_bg.show()
        self.current_step = orig_step
        self.set_counts_text("カウント")
        self.update_preview()

        def frame(sec): return int(round(sec * fps))

        def video_clip_xml(cid, name, start_s, end_s, filepath, is_image=False):
            sf, ef = frame(start_s), frame(end_s)
            dur = ef - sf
            if dur <= 0: return ""
            purl = encode_path_for_premiere(filepath)
            safe_name = escape_xml(name)

            if is_image:
                media_dur = 1296000
                in_frame = 648000
                out_frame = in_frame + dur
            else:
                media_dur = dur
                in_frame = 0
                out_frame = dur

            return f"""
            <clipitem id="{cid}">
              <name>{safe_name}</name>
              <duration>{media_dur}</duration>
              <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
              <start>{sf}</start><end>{ef}</end>
              <in>{in_frame}</in><out>{out_frame}</out>
              <file id="file-{cid}">
                <name>{safe_name}</name>
                <pathurl>{purl}</pathurl>
                <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
                <duration>{media_dur}</duration>
                <media>
                  <video>
                    <duration>{media_dur}</duration>
                    <samplecharacteristics>
                      <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
                      <width>1920</width><height>1080</height>
                      <anamorphic>FALSE</anamorphic>
                      <pixelaspectratio>square</pixelaspectratio>
                    </samplecharacteristics>
                  </video>
                </media>
              </file>
            </clipitem>"""

        xml_clips_v1 = ""
        if dest_video:
            xml_clips_v1 = video_clip_xml("bg_video", os.path.basename(dest_video), 0, total_audio_time, os.path.abspath(dest_video), is_image=False)

        xml_clips_v2 = ""
        for i, clip in enumerate(base_clips_info):
            png_abs_path = os.path.abspath(os.path.join(out_dir, clip["file"]))
            xml_clips_v2 += video_clip_xml(f"base_png_{i}", clip["name"], clip["start"], clip["end"], png_abs_path, is_image=True)

        xml_clips_v3 = ""
        for i, clip in enumerate(count_clips_info):
            png_abs_path = os.path.abspath(os.path.join(out_dir, clip["file"]))
            xml_clips_v3 += video_clip_xml(f"cnt_png_{i}", clip["name"], clip["start"], clip["end"], png_abs_path, is_image=True)

        audio_xml = ""
        if dest_audio:
            purl = encode_path_for_premiere(os.path.abspath(dest_audio))
            start_frame = frame(intro_offset_sec)
            end_frame = frame(total_audio_time)
            dur = end_frame - start_frame
            audio_xml = f"""
            <clipitem id="audio-1">
              <name>Audio Track</name>
              <duration>{dur}</duration>
              <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
              <start>{start_frame}</start><end>{end_frame}</end>
              <in>0</in><out>{dur}</out>
              <file id="afile-1">
                <name>{escape_xml(os.path.basename(dest_audio))}</name>
                <pathurl>{purl}</pathurl>
                <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
                <duration>{dur}</duration>
                <media>
                  <audio>
                    <samplecharacteristics>
                      <depth>16</depth><samplerate>48000</samplerate>
                    </samplecharacteristics>
                    <channelcount>2</channelcount>
                  </audio>
                </media>
              </file>
            </clipitem>"""

        video_tracks_xml = ""
        if xml_clips_v1: video_tracks_xml += f"<track>{xml_clips_v1}</track>\n"
        if xml_clips_v2: video_tracks_xml += f"<track>{xml_clips_v2}</track>\n"
        if xml_clips_v3: video_tracks_xml += f"<track>{xml_clips_v3}</track>\n"

        audio_section = ""
        if audio_xml:
            audio_section = f"""<audio>
              <format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format>
              <track>{audio_xml}</track>
            </audio>"""

        fcpxml_data = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
  <project>
    <name>Lighting_Export</name>
    <children>
      <sequence id="seq-1">
        <name>Lighting_Timeline</name>
        <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
        <media>
          <video>
            <format>
              <samplecharacteristics>
                <rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>
                <width>1920</width><height>1080</height>
              </samplecharacteristics>
            </format>
            {video_tracks_xml}
          </video>
          {audio_section}
        </media>
      </sequence>
    </children>
  </project>
</xmeml>"""

        xml_filename = "project_timeline.xml"
        with open(os.path.join(out_dir, xml_filename), "w", encoding="utf-8") as f:
            f.write(fcpxml_data)

        total_pngs = len(base_clips_info) + len(count_png_files)
        QMessageBox.information(self, "完了", f"【出力完了】\n・画像 {total_pngs}枚（ベース画像＋汎用カウント画像）\n・プロジェクトファイル ({xml_filename})\n\n※指定した素材ファイルも同じフォルダにコピーしました。")
        import subprocess
        subprocess.Popen(f'explorer "{os.path.abspath(out_dir)}"')

if __name__ == "__main__":
    def global_exception_handler(exctype, value, tb):
        error_msg = "".join(traceback.format_exception(exctype, value, tb))
        print("CRITICAL ERROR:\n" + error_msg)
        app = QApplication.instance()
        if not app: app = QApplication(sys.argv)
        QMessageBox.critical(None, "致命的なエラー", f"プログラムがクラッシュしました。\n\n{error_msg}")
        sys.exit(1)
    sys.excepthook = global_exception_handler
    app = QApplication(sys.argv)
    window = ExcelToProjectApp()
    window.show()
    sys.exit(app.exec())