import os
import sys
import json
import re
import colorsys
import urllib.parse
import xml.sax.saxutils

# ---------------------------------------------------------
# ファイルパス・XML関連
# ---------------------------------------------------------
def encode_path_for_premiere(filepath):
    path = filepath.replace('\\', '/')
    path = urllib.parse.quote(path)
    path = path.replace('%2F', '/')
    return "file://localhost/" + path

def escape_xml(text):
    return xml.sax.saxutils.escape(str(text), {'"': "&quot;", "'": "&apos;"})

# ---------------------------------------------------------
# カラーマップ関連
# ---------------------------------------------------------
def _app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

# 起動時のカレントフォルダに関係なく、exe(またはスクリプト)と同じ場所に置く
COLOR_MAP_FILE = os.path.join(_app_dir(), "color_map.json")
DEFAULT_COLOR_MAP = {
    "赤": {"type": "color", "value": [255, 0, 0]}, "橙": {"type": "color", "value": [255, 128, 0]},
    "オレンジ": {"type": "color", "value": [255, 128, 0]}, "黄": {"type": "color", "value": [255, 255, 0]},
    "黄緑": {"type": "color", "value": [128, 255, 0]}, "緑": {"type": "color", "value": [0, 255, 0]},
    "水色": {"type": "color", "value": [0, 255, 255]}, "水": {"type": "color", "value": [0, 255, 255]},
    "青": {"type": "color", "value": [0, 0, 255]}, "青紫": {"type": "color", "value": [128, 0, 255]},
    "赤紫": {"type": "color", "value": [255, 0, 128]}, "紫": {"type": "color", "value": [128, 0, 128]},
    "ピンク": {"type": "color", "value": [255, 128, 192]}, "白": {"type": "color", "value": [255, 255, 255]},
    "カラフル": {"type": "rainbow", "value": None}
}

def load_color_map():
    if not os.path.exists(COLOR_MAP_FILE):
        save_color_map(DEFAULT_COLOR_MAP)
        return DEFAULT_COLOR_MAP.copy()
    try:
        with open(COLOR_MAP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        migrated = False
        for k, v in list(data.items()):
            if isinstance(v, list):
                data[k] = {"type": "color", "value": v}
                migrated = True
        if "カラフル" not in data:
            data["カラフル"] = {"type": "rainbow", "value": None}
            migrated = True
        if migrated: save_color_map(data)
        return data
    except: return DEFAULT_COLOR_MAP.copy()

def save_color_map(color_map):
    try:
        with open(COLOR_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(color_map, f, ensure_ascii=False, indent=4)
    except: pass

def get_rainbow_html(text):
    if not text: return ""
    colored_text = ""
    clean_text = text.replace('\n', '')
    n = max(len(clean_text), 1)
    for i, char in enumerate(text):
        if char == '\n':
            colored_text += '<br>'; continue
        rgb = colorsys.hsv_to_rgb(i / n, 1, 1)
        r, g, b = [int(255 * v) for v in rgb]
        colored_text += f'<span style="color: rgb({r},{g},{b})">{char}</span>'
    return colored_text

def generate_colored_html(text, font_size, color_map):
    if not text: return ""
    html_start = f'<div align="center" style="font-family: Meiryo; font-size: {font_size}px; color: white;">'
    html_end = '</div>'
    color_names = sorted(color_map.keys(), key=len, reverse=True)
    if not color_names: return html_start + text.replace('\n', '<br>') + html_end
    
    parts = re.split("(" + "|".join(map(re.escape, color_names)) + ")", text)
    colored_text = ""
    for part in parts:
        if not part: continue
        if part in color_map:
            cfg = color_map[part]
            if cfg.get("type", "color") == "rainbow": 
                colored_text += get_rainbow_html(part) 
            else:
                r, g, b = cfg.get("value", [255, 255, 255])
                colored_text += f'<span style="color: rgb({r},{g},{b})">{part.replace(chr(10), "<br>")}</span>'
        else: colored_text += part.replace('\n', '<br>')
    return html_start + colored_text + html_end