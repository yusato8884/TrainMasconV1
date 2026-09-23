# -*- coding: utf-8 -*-
"""
AE-RP2040 / MicroPython
可変抵抗とボタンで文字を入力する簡易キーボード

仕様
  ・可変抵抗：角度(電圧)が別の範囲に変わった瞬間、その範囲のキーを1回入力
  ・ボタン  ：押した瞬間、そのボタンに割り当てたキーを1回入力（各ボタン独立）
  ・ボタンは長押しでリピート入力（可変抵抗もPOT_REPEAT=Trueで同様に）
  ・OLED   ：可変抵抗で今選んでいる文字を、太字・中央揃えで表示

配線
  OLED (SSD1306, I2C)  SDA=GP20 / SCL=GP19  ※SoftI2C
  ボタン1              GP23  --- GND
  ボタン2              GP24  --- GND
  ボタン3              GP25  --- GND
  可変抵抗             ADC0 (GP26) の中点、両端は 3V3 と GND

必要ライブラリ: ssd1306.py を AE-RP2040 に転送しておいてください
  (mpremote mip install ssd1306  など)
"""

from machine import Pin, SoftI2C, ADC
import time
import framebuf
import gc

import ssd1306

# ============================================================
# 設定
# ============================================================

PIN_SDA = 20
PIN_SCL = 19
PIN_BUTTONS = (23, 24, 25)   # B1, B2, B3
PIN_POT = 26                 # ADC0

OLED_W, OLED_H = 128, 64
OLED_ADDR = 0x3C

VREF = 3.3                   # ADCの基準電圧[V]


# --- OLED表示の設定 ------------------------------------------
# 可変抵抗で今選んでいるキーの「表示用文字列」を、
# 大きな太字・中央揃えでOLEDに表示します。
DISPLAY_BOLD = True   # True=太字, False=普通の太さ
TEXT_SCALE = 6        # 文字の拡大倍率。標準8pxの何倍にするか（1文字なら6〜7が大きめ）

FONT_W = 8            # 標準フォントの1文字の幅[px]
FONT_H = 8            # 標準フォントの1文字の高さ[px]


# --- キー配列（マスコン）-------------------------------------
# (下限電圧, 上限電圧, キー, 表示ラベル) のタプルを並べます。
#   下限 <= 電圧 < 上限  のときそのマスコン位置が選ばれます。
#   3番目「キー」  … その位置のとき送るキー（HID）。特殊キーは "RIGHT" 等の名前。
#   4番目「ラベル」… OLEDに大きく表示する文字（P4 / N / B3 / EB など）。
# 電圧は後で調整する前提の“とりあえず等分”です。数値だけ書き換えれば調整できます。
# 並びは電圧の小さい順。P4が電圧の低い方（一番上のノッチ）です。

LAYERS = {
    "mascon": [
        # (下限V, 上限V, キー,     ラベル)  ※0.9〜3.3Vを均等13分割
        (0.900, 1.085, "1",    "P4"),   # ← 電圧が低い方
        (1.085, 1.269, "2",    "P3"),
        (1.269, 1.454, "3",    "P2"),
        (1.454, 1.638, "4",    "P1"),
        (1.638, 1.823, "RIGHT", "N"),    # N = 右矢印キー
        (1.823, 2.008, "5",    "B1"),
        (2.008, 2.192, "6",    "B2"),
        (2.192, 2.377, "7",    "B3"),
        (2.377, 2.562, "8",    "B4"),
        (2.562, 2.746, "9",    "B5"),
        (2.746, 2.931, "0",    "B6"),
        (2.931, 3.115, "-",    "B7"),
        (3.115, 3.300, " ",    "EB"),   # EB = Space
    ],
}
LAYER_ORDER = ["mascon"]


# --- ボタンに割り当てるキー -----------------------------------
# ボタンを押した「瞬間」からそのキーを押し続け、離した瞬間に解除します。
# 同時押しに特別な意味はありません（各ボタンは独立）。
#   ボタン1(GP23) = Enter
#   ボタン2(GP24) = H （Shiftなし。大文字にしたい場合は "H" にする）
#   ボタン3(GP25) = B （Shiftなし。大文字にしたい場合は "B" にする）
BUTTON_KEYS = ["\n", "h", "b"]


# --- タイミング / 精度 ----------------------------------------
DEBOUNCE_MS = 20      # チャタリング除去[ms]
TAP_MS = 12           # タップ入力の押下→解放の間隔[ms]（短すぎると取りこぼす）
HID_TIMEOUT_MS = 30   # HID送信の最大待ち時間[ms]。大きいと固まりやすく、0で待たない
POT_SAMPLES = 8       # 可変抵抗の平均化サンプル数
POT_HYST_V = 0.03     # ヒステリシス[V]。境界付近のブレが気になるなら増やす

# 万一フリーズしても自動リセットで復帰させる安全装置（ウォッチドッグ）
# 注意: 一度オンにすると停止できず、編集中もリセットがかかって保存しづらくなる。
#       まずは False のまま使い、動作が安定してから必要なら True にする。
#       True にしても、ボタン1を押しながら起動すれば安全モードで編集できる。
USE_WATCHDOG = False  # True=有効。ハングしても数秒で自動リセットして復帰
WATCHDOG_MS = 4000    # この時間 反応が無いと自動リセット[ms]（RP2040は最大約8300）

# 長押しのリピート（同じ文字が連続入力される）はPC側の設定で行われます。
# このプログラムは「押している間キーを押し続ける」ことだけを担当します。

# 可変抵抗を同じ範囲に留めているときの動作
#   False = 範囲に入った瞬間に1回だけ入力（既定・タップ）
#   True  = 留めている間はそのキーを押し続ける（＝長押し。リピートはPC側）
POT_REPEAT = False

MAX_BUFFER = 200      # 入力バッファの最大文字数


# --- 起動画面（スプラッシュ）の設定 ---------------------------
BOOT_TEXT = ["Train", "Mascon"]   # 起動画面 右側に出す文字（1要素=1行）
BOOT_HOLD_S = 2          # 起動画面を表示する秒数
ICON_SIZE = 54           # アイコンの一辺[px]
ICON_PAD = 10            # 左の余白 & 画像とテキストの間隔[px]
ICON_FILE = "icon.txt"   # ICON_TEXTが空のとき読むファイル（0/1のテキスト）
# ※アイコンの絵そのもの(0/1データ = ICON_TEXT)は、下の「起動画面」セクションにあります


# --- USB（HID）の設定 ---------------------------------------
USE_HID = True    # True: USBキーボードとして入力を送る / False: printだけ
# 下のプロパティは None なら MicroPython の既定値。値を入れればそれが反映されます。
DEVICE_NAME   = "TrainMasconV1"   # PCに表示されるデバイス名（product string）
MANUFACTURER  = "Yu Sato"         # 製造者名（例: "Yu"）。不要なら None
USB_VID       = None              # ベンダーID（例: 0xF055）。None=既定
USB_PID       = None              # プロダクトID（例: 0x9802）。None=既定
USB_SERIAL    = None              # シリアル番号文字列。None=既定
USB_MAX_POWER = 100               # 最大消費電流[mA]（例: 100）。None=既定


# ============================================================
# ハードウェア初期化
# ============================================================

i2c = SoftI2C(sda=Pin(PIN_SDA), scl=Pin(PIN_SCL), freq=100000)
oled = ssd1306.SSD1306_I2C(OLED_W, OLED_H, i2c, addr=OLED_ADDR)

buttons = [Pin(p, Pin.IN, Pin.PULL_UP) for p in PIN_BUTTONS]
pot = ADC(PIN_POT)

# 起動時の脱出口（安全モード）:
#   ボタン1を押しながら電源を入れる/リセットすると、HID初期化・メインループ・
#   ウォッチドッグを一切始めずにREPLへ落ちる。
#   自動実行やウォッチドッグでソースを書き換えられないときに使う。
SAFE_MODE = (buttons[0].value() == 0)   # ボタン1が押されていれば安全モード


_oled_fail = 0

def oled_show():
    """OLEDへの書き込み。I2Cが一時的に失敗(ENODEV等)しても落ちないようにする。
    連続で失敗したら、表示を初期化し直して復帰を試みる。"""
    global _oled_fail
    try:
        oled.show()
        _oled_fail = 0
    except OSError:
        _oled_fail += 1
        if _oled_fail >= 5:
            _oled_fail = 0
            try:
                oled.init_display()   # 一度リセットして立て直す
            except OSError:
                pass                  # それでも駄目なら次のフレームで再挑戦


def read_voltage():
    """可変抵抗の電圧[V]を返す"""
    total = 0
    for _ in range(POT_SAMPLES):
        total += pot.read_u16()
    return (total / POT_SAMPLES) / 65535.0 * VREF


# ============================================================
# OLEDへの文字表示（拡大・太字・中央揃え）
# ============================================================

def draw_big_center(s, scale, bold=True):
    """
    文字列 s を scale 倍に拡大し、画面の中央（縦横とも）に描く。
    標準フォント(8x8)の1ドットを scale×scale の正方形に拡大する。
    （1bitのOLEDなので“にじみ”は作れないが、大きく均一なドットにすることで
      ファミコンのタイル文字のようにくっきり見せる）
    """
    oled.fill(0)

    if not s:
        oled_show()
        return

    w = len(s) * FONT_W        # 元の文字列の幅[px]
    h = FONT_H                 # 元の高さ[px]

    # 画面からはみ出さないように、必要なら倍率を自動で下げる
    scale = min(scale, OLED_W // w, OLED_H // h)
    if scale < 1:
        scale = 1

    # 元サイズの文字を一時バッファ(モノクロ)に描く
    row_bytes = (w + 7) // 8   # MONO_HLSBは1行あたり ceil(w/8) バイト
    buf = bytearray(row_bytes * h)
    fb = framebuf.FrameBuffer(buf, w, h, framebuf.MONO_HLSB)
    fb.fill(0)
    fb.text(s, 0, 0, 1)

    # 拡大後のサイズと、中央に置くための左上座標
    out_w = w * scale
    out_h = h * scale
    x0 = (OLED_W - out_w) // 2
    y0 = (OLED_H - out_h) // 2

    # 太字は「上下左右に1pxずつ均等に膨らませる」ことで太くする（横だけ太る不均一を防ぐ）
    grow = 1 if bold else 0
    block = scale + 2 * grow

    # 点いているドットを scale 角の正方形として描く
    for y in range(h):
        for x in range(w):
            if fb.pixel(x, y):
                oled.fill_rect(x0 + x * scale - grow,
                               y0 + y * scale - grow,
                               block, block, 1)

    oled_show()


# ============================================================
# 大きめフォント（DejaVuSans Bold を1bit化して埋め込み）
#   荒い8x8の拡大をやめ、これでマスコンのラベルをきれいに描く。
#   対応文字は 0-9 / A-Z / "-"。対応外が混ざる場合だけ従来の拡大表示に切替。
# ============================================================
import binascii

GLYPH_H = 48
_GLYPHS = {
    '0': (28, 0),
    '1': (24, 168),
    '2': (26, 312),
    '3': (26, 468),
    '4': (28, 624),
    '5': (26, 792),
    '6': (28, 948),
    '7': (26, 1116),
    '8': (28, 1272),
    '9': (28, 1440),
    'A': (36, 1608),
    'B': (28, 1824),
    'C': (29, 1992),
    'D': (32, 2166),
    'E': (25, 2358),
    'F': (24, 2508),
    'G': (33, 2652),
    'H': (31, 2850),
    'I': (9, 3036),
    'J': (15, 3090),
    'K': (33, 3180),
    'L': (25, 3378),
    'M': (38, 3528),
    'N': (31, 3756),
    'O': (35, 3942),
    'P': (28, 4152),
    'Q': (35, 4320),
    'R': (31, 4530),
    'S': (27, 4716),
    'T': (32, 4878),
    'U': (30, 5070),
    'V': (36, 5250),
    'W': (49, 5466),
    'X': (35, 5760),
    'Y': (35, 5970),
    'Z': (30, 6180),
    '-': (15, 6360),
}
_FONT_B64 = "AAAAgMDg8Pj4+Pz8/Pz8/Pz8+Pj48ODAgAAAAID4/v///////w8DAQAAAAABAw/////////++ID///////////8AAAAAAAAAAAAA////////////AA8/////////+ODAgICAgMDg+P///////z8PAAAAAAABAwcPDw8fHx8fHx8fHw8PDwcDAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA4ODw8PDw+Pj4+Pj4+Pj4+AAAAAAAAAAABwcDAwMDAQH//////////wAAAAAAAAAAAAAAAAAAAAD//////////wAAAAAAAAAAgICAgICAgID//////////4CAgICAgICAHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPD4+Pj4+Pz8/Pz8/Pz8/Pz4+PDw4MCAAAAABwMDAQEBAAAAAAAAAQMH//////////98AAAAAAAAAAAAgIDA4PD4/v///38/Hw8HAQAAAMDg8Pj8/v////+/n4+Hg4GAgICAgICAgAAAHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADw+Pj4+Pz8/Pz8/Pz8/Pz4+Pjw8ODAAAAAAAMBAQEAAAAAAAAAgYHD/////////38MAAAAAAAAAD8/Pz8/Pz9/f///////+fnw4IAA4MDAwMCAgICAgICAgMDA4PH/////////fwAPDw8fHx8fHx8fHx8fHx8fDw8PBwcDAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADA4Pj4+Pj4+Pj4+PgAAAAAAAAAAAAAgMDw+P7//z8fB///////////AAAAAACA4PD8/v9/Pw8HAQAAAAD//////////wAAAAAAf39/f39/fn5+fn5+fn5+//////////9+fn5+fgAAAAAAAAAAAAAAAAAAAB8fHx8fHx8fAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+PgAAAAAAP/////////BwcHBwcHBwYGBgQEBAQAAAAAAPx8fHw8PDw8PDw8PHz9////////+/PCAAPDg4MDAwICAgICAgIDA4PD/////////fw8ABw8PDw8fHx8fHx8fHx8fDw8PDwcDAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIDA4ODw+Pj4/Pz8/Pz8/Pz8+Pj48AAAAADA+P7//////z+Pg4HBwMDAwMDAgIEBAQMAAAAA////////////fx8PDw8PDx8////////+/PAAAAMff/////////DAgICAgIDA4P////////8/AAAAAAABAwcHDw8PHx8fHx8fHx8PDwcHAwEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+AABAQEBAQEBAQEBAQEBgeH5////////Pw8DAAAAAAAAAAAAAADA8P7//////38fBwAAAAAAAAAAAAAAgOD8////////Pw8BAAAAAAAAAAAAAAAAEB4fHx8fHx8fAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACA4PDw+Pj4/Pz8/Pz8/Pz8/Pj4+PDw4IAAAAAAP//////////BwYCAgIDBwf///////38/AAAAgODw+Pn9//9/Pz8fHx8fHz/////9+fjw4IAAAH//////////4MCAgICAgIDA8P////////9/AAAAAQMHBw8PDx8fHx8fHx8fHx8PDw8HBwMBAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAwODw8Pj4/Pz8/Pz8/Pz4+Pjw4OCAAAAAAPD+/////////wMBAAAAAAABB//////////8wAAABx8/f3/////+/Pj4+Pj4/H9///////////8AAAAA4MDAwICBgYGBgYHBwOD4/v////9/Pw8BAAAAAAcPDw8fHx8fHx8fHx8PDw8HAwMBAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADA+Pj4+Pj4+Pj4+PjwgAAAAAAAAAAAAAAAAAAAAAAAAADA8P7//////38PH/////////zggAAAAAAAAAAAAAAAAACA8P7///////8fAwAAAAAHP/////////zgAAAAAAAAAACA8P7///////9/f35+fn5+fn5+fn9/f/////////zgAAAAEB4fHx8fHx8fBwEAAAAAAAAAAAAAAAAAAAMPHx8fHx8fHxgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+PDw8ODgwAAAAP///////////wEBAQEBAQGDx///////////AAD///////////8/Pz8/Pz8/P3////////vx4MAA////////////gICAgICAgIDA4P//////////Px8fHx8fHx8fHx8fHx8fHx8fHx8fDw8PBwcDAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIDAwODw8Pj4+Pz8/Pz8/Pz8/Pz4+Pj48PAA8Pz+////////Hw8DAwEBAAAAAAAAAAEBAQMDB3///////////4EAAAAAAAAAAAAAAAAAAAAAAAAAAAcfP/////////z44ODAwICAgICAgIDAwMDg4PAAAAAAAAEBAwcHDw8PHx8fHx8fHx8fHw8PDw8HBwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4+Pj4+Pj4+Pj48PDw8ODgwMCAAAAAAAD///////////8BAQEBAQEBAwMHBw8//////////vjgAP///////////wAAAAAAAAAAAAAAAACB//////////9/////////////gICAgICAgMDA4ODw/P///////38fBwAfHx8fHx8fHx8fHx8fHx8fHx8PDw8PBwcDAwEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4AP///////////wEBAQEBAQEBAQEBAQEBAQD///////////8/Pz8/Pz8/Pz8/Pz8/PwAA////////////gICAgICAgICAgICAgICAAB8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4////////////AQEBAQEBAQEBAQEBAQEB////////////Pz8/Pz8/Pz8/Pz8/Pz8A////////////AAAAAAAAAAAAAAAAAAAAHx8fHx8fHx8fAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAwODw8Pj4+Pj8/Pz8/Pz8/Pz8/Pj4+Pjw8AAAAPD8/v///////x8PBwMBAQAAAAAAAAAAAQEBAQMDBwAAf///////////gAAAAAAAAAAAAPz8/Pz8/Pz8/Pz8/PwAAAcfP/////////z44ODAwICAgICAgIDA//////////8AAAAAAAABAQMHBw8PDx8fHx8fHx8fHx8fDw8PDwcHBwMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4AAAAAAAAAAAAAAAAAPj4+Pj4+Pj4AP///////////wAAAAAAAAAAAAAAAAD//////////wD///////////8/Pz8/Pz8/Pz8/Pz8///////////8A////////////AAAAAAAAAAAAAAAAAP//////////AB8fHx8fHx8fHwAAAAAAAAAAAAAAAAAfHx8fHx8fHwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4////////////////////////////////////Hx8fHx8fHx8fAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4AAAAAAAA////////////AAAAAAAA////////////AAAAAAAA////////////AAAAgIDg//////////8fPz8/Pz8/Hx8fDw8HAwAA+Pj4+Pj4+Pj4AAAAAAAAAACAwODw+Pj4+Pj4eDgYCAAA////////////gMDg8Pj8/v///38/Hw8HAwEAAAAAAAAA//////////////////////PhwIAAAAAAAAAAAAAAAAAA////////////AAEDBw8fP3///////vz48ODAgAAAAAAAHx8fHx8fHx8fAAAAAAAAAAAAAQMHDx8fHx8fHx8eHBgQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4AAAAAAAAAAAAAAAAAAAAAP///////////wAAAAAAAAAAAAAAAAAAAAD///////////8AAAAAAAAAAAAAAAAAAAAA////////////gICAgICAgICAgICAgICAAB8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4+PjwwAAAAAAAAAAAAAAAAMD4+Pj4+Pj4+Pj4+Pj//////////z9//////vjgAAAAAACA4Pz/////P///////////////////////AAABDz///////ODw/P////8/BwEA//////////////////////8AAAAAAAEHH39/f39/fx8DAAAAAAD///////////8fHx8fHx8fHwAAAAAAAAAAAAAAAAAAAAAAAAAAAB8fHx8fHx8fHwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4+PDAAAAAAAAAAAAAAPj4+Pj4+Pj4AP//////////f//////88MAAAAAAAAD//////////wD//////////wAAAw8ff/////z44IAA//////////8A//////////8AAAAAAAABBx9//////v//////////AB8fHx8fHx8fAAAAAAAAAAAAAAEHHx8fHx8fHx8fHwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIDA4ODw8Pj4+Pz8/Pz8/Pz8/Pj4+Pjw4ODAgAAAAAAA8Pz/////////HwcDAQEAAAAAAAEBAwcP//////////zwAH///////////4AAAAAAAAAAAAAAAAAAAACA//////////9/AAcff/////////zw4MDAgICAgIDAwODw+P///////38fBwAAAAAAAAEDAwcHDw8PHx8fHx8fHx8fDw8PDwcDAwEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+PDw8ODgwIAAAP///////////wEBAQEBAQEDAw////////////j////////////4+Pj4+Pj4/Pz/////f38/Hw8B////////////AQEBAQEBAQEBAQAAAAAAAAAAAB8fHx8fHx8fHwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIDA4ODw8Pj4+Pz8/Pz8/Pz8/Pj4+Pjw8ODAgAAAAAAA8Pz/////////HwcDAQEAAAAAAAEBAwcP//////////zwAH///////////4AAAAAAAAAAAAAAAAAAAACA//////////9/AAcff/////////zw4MDAgICAgIDAwODw+P///////38fBwAAAAAAAAEDAwcHDw8PHx8fHx8fP////////+fDgwEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAEDBw8PDw8PDgwIAAAA+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+PDw8ODAgAAAAAAAAP///////////wEBAQEBAQMDz///////////AAAAAAD////////////8/Pz8/Pz+/v/////Pz4cDAAAAAAAA////////////AAAAAAABAwcff////////vjggAAAAB8fHx8fHx8fHwAAAAAAAAAAAAABBx8fHx8fHx8eGAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIDA4PDw+Pj8/Pz8/Pz8/Pz8/Pj4+Pj48AAAfP/////////jwYGAAAAAAAAAAQEBAwMDAwAAAAMHDx8fPz9/f39/f//////+/v7+/Pz48OAAAPDg4MDAwMCAgICAgICAgMHB//////////8fAAcHDw8PDw8fHx8fHx8fHx8fDw8PDwcDAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+AABAQEBAQEBAQEBAf///////////wEBAQEBAQEBAQEBAAAAAAAAAAAAAAAA////////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD///////////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB8fHx8fHx8fHwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+Pj4+Pj4+Pj4AAAAAAAAAAAAAAD4+Pj4+Pj4+PgA////////////AAAAAAAAAAAAAAD///////////8A////////////AAAAAAAAAAAAAAD///////////8ABz//////////8ODAgICAgIDAwOD/////////fw8AAAAAAQMHBw8PDx8fHx8fHx8fHw8PDw8HAwMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACHj4+Pj4+Pj44IAAAAAAAAAAAAAAAAAAAMDw+Pj4+Pj4+BgAAAABD3/////////84AAAAAAAAAAAAIDw/v///////z8HAAAAAAAAAAABD3/////////4wAAAAIDw/P///////z8HAAAAAAAAAAAAAAAAAAADD3/////////4/P///////z8HAQAAAAAAAAAAAAAAAAAAAAAAAAADHx8fHx8fHx8fHx8PAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACPj4+Pj4+Pj4gAAAAAAAAAAAAMD4+Pj4+Pj4+PiAAAAAAAAAAAAA4Pj4+Pj4+Pg4AAAAD//////////4gAAAAAAAgPz/////fw////////gAAAAAAADA/P///////38HAAAAAAAAH//////////4AACA+P////9/BwAAAA////////AAAMD8/////////wcAAAAAAAAAAAABH//////////4//////8PAAAAAAAAAR////////j/////////DwAAAAAAAAAAAAAAAAABHx8fHx8fHx8fHw8AAAAAAAAAAAAAAR8fHx8fHx8fHx8fAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAYOPj4+Pj4+PjgwAAAAAAAAAAAAIDg8Pj4+Pj4+HgYCAAAAAAAAAEHDz9///////748MDg+Pz//////z8fBwMAAAAAAAAAAAAAAAAAAACB4///////////////58EAAAAAAAAAAAAAAAAAAADA4Pj8//////8/HwcDBw8/f//////+/PDggAAAAAAAEBgeHx8fHx8fDwcBAAAAAAAAAAAAAAMHHx8fHx8fHxwYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAg4+Pj4+Pj4+PDggAAAAAAAAAAAAIDA8Pj4+Pj4+Pg4GAAAAAAAAQcPP3///////vzw4IDA8Pj+//////8/HwcDAAAAAAAAAAAAAAAAAAEDDx////////////8/DwcBAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP///////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHx8fHx8fHx8fAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+PgAAAEBAQEBAQEBAQEBAYHh8fn9//////9/Px8HAwEAAAAAAAAAgMDg8Pz+//////9/Hw8HAwAAAAAAAAAAgMDg+Pz+//////+/n4+DgYCAgICAgICAgICAgIAAHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA8PDw8PDw8PDw8PDw8PDwBwcHBwcHBwcHBwcHBwcHAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
_FONT_BLOB = binascii.a2b_base64(_FONT_B64)   # 1bitグリフの連結(MONO_VLSB形式)


def _glyph_fb(ch):
    info = _GLYPHS.get(ch)
    if info is None:
        return None, 0
    w, off = info
    n = w * (GLYPH_H // 8)
    fb = framebuf.FrameBuffer(bytearray(_FONT_BLOB[off:off + n]), w, GLYPH_H, framebuf.MONO_VLSB)
    return fb, w


def draw_label(s, gap=2):
    """埋め込みフォントで s を画面中央に描く。
    対応外の文字があれば、従来の拡大8x8にフォールバックする。"""
    total = 0
    for ch in s:
        info = _GLYPHS.get(ch)
        if info is None:
            draw_big_center(s, TEXT_SCALE, DISPLAY_BOLD)
            return
        total += info[0] + gap
    if s:
        total -= gap

    x = (OLED_W - total) // 2
    if x < 0:
        x = 0
    y = (OLED_H - GLYPH_H) // 2
    if y < 0:
        y = 0

    oled.fill(0)
    for ch in s:
        fb, w = _glyph_fb(ch)
        oled.blit(fb, x, y)
        x += w + gap
    oled_show()


# ============================================================
# 起動画面（スプラッシュ）
#   左：54x54のアイコン（0/1のバイナリ）  右：Train / Mascon の2行
# ============================================================

# アイコンの0/1データ。ここに 54行×54文字 を貼るとそれを表示します。
# 空のままなら、下の ICON_FILE（AE-RP2040内のファイル）を読みに行きます。
ICON_TEXT = """
000000000000000000000000000000000000000000000000000000
000000000000000000000000000000000000000000000000000000
000000000000000000000000000000000000000000000000000000
000000000000000000000000000000000000000000000000000000
000000000000000000000000011100000000000000000000000000
000000000011111111111111111111111111111111110000000000
000000000111111111111111111111111111111111111000000000
000000001111111111111111111111111111111111111100000000
000000011111111111111111111111111111111111111110000000
000000011111000000000000011110000000000000111110000000
000000011110000000000000011110000000000000011110000000
000000011110000000000000011110000000000000011110000000
000000011110000000000000011110000000000000011110000000
000000011110000000000000011110000000000000011110000000
000000011110000000000000011110000000000000011110000000
000000011110000000000000011110000000000000011110000000
000000011110000000000000011110000000000000011110000000
000000011110000000000000011110000000000000011110000000
000000011110000000000000011110000000000000011110000000
000000011110000000000000011110000000000000011110000000
000000011110000000000000011110000000000000011110000000
000000011110000000000000011110000000000000011110000000
000000011111000000000000111111000000000000111110000000
000000011111111111111111111111111111111111111110000000
000000011111111111111111111111111111111111111110000000
000000011111111111111111111111111111111111111110000000
000000011111111111111111111111111111111111111110000000
000000011110000000000000000000000000000000011110000000
000000011110000000000000000000000000000000011110000000
000000011110000000000000000000000000000000011110000000
000000011110000000000000000000000000000000011110000000
000000011110000000000000000000000000000000011110000000
000000011110000011110000000000000011110000011110000000
000000011110000011110000000000000011110000011110000000
000000011110000011110000000000000011110000011110000000
000000011110000001100000000000000001100000011110000000
000000011110000000000000000000000000000000011110000000
000000011110000000000000000000000000000000011110000000
000000011110000000000000000000000000000000011110000000
000000011111000000000000000000000000000000111110000000
000000011111100001100000000000000001100011111110000000
000000001111111111111111111111111111111111111100000000
000000001111111111111111111111111111111111111100000000
000000000111111111111111111111111111111111111000000000
000000000001111111111111111111111111111111100000000000
000000000000011111100000000000000001111110000000000000
000000000000011111000000000000000000111110000000000000
000000000000111111000000000000000000111111000000000000
000000000000111110000000000000000000011111000000000000
000000000001111100000000000000000000001111100000000000
000000000000111100000000000000000000001111000000000000
000000000000010000000000000000000000000010000000000000
000000000000000000000000000000000000000000000000000000
000000000000000000000000000000000000000000000000000000
"""
# （ICON_FILE / ICON_SIZE / ICON_PAD / BOOT_TEXT / BOOT_HOLD_S は先頭の設定にまとめました）


def _parse_icon(text):
    """0/1のテキストを、各行を文字列にしたリストへ変換する。"""
    rows = []
    for line in text.split("\n"):
        row = "".join(c for c in line if c in "01")
        if row:
            rows.append(row)
    return rows


def load_icon():
    """ICON_TEXT かファイルから 0/1 データを読み込む。無ければ None。"""
    if ICON_TEXT.strip():
        return _parse_icon(ICON_TEXT)
    try:
        with open(ICON_FILE) as f:
            return _parse_icon(f.read())
    except OSError:
        return None


def draw_icon(rows, x, y):
    """0/1データの '1' の位置に点を打つ。"""
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == "1":
                oled.pixel(x + c, y + r, 1)


def draw_boot_screen():
    """起動画面を描く。左にアイコン、右に BOOT_TEXT。"""
    oled.fill(0)

    # アイコン：左に ICON_PAD の余白。縦は中央（54は64にほぼ一杯なので上下約5px）
    icon_x = ICON_PAD
    icon_y = (OLED_H - ICON_SIZE) // 2
    rows = load_icon()
    if rows:
        draw_icon(rows, icon_x, icon_y)
    else:
        # データ未配置のときは、配置が分かるように枠だけ描く
        oled.rect(icon_x, icon_y, ICON_SIZE, ICON_SIZE, 1)

    # テキスト：画像の右 ICON_PAD の位置から。縦は画面中央にそろえる
    text_x = icon_x + ICON_SIZE + ICON_PAD      # 10 + 54 + 10 = 74
    gap = 4
    block_h = len(BOOT_TEXT) * FONT_H + (len(BOOT_TEXT) - 1) * gap
    ty = (OLED_H - block_h) // 2
    for t in BOOT_TEXT:
        oled.text(t, text_x, ty, 1)
        ty += FONT_H + gap

    oled_show()


def _draw_center_text(s, y):
    """標準8pxフォントで、文字列sを水平中央に描く。"""
    x = (OLED_W - len(s) * FONT_W) // 2
    if x < 0:
        x = 0
    oled.text(s, x, y)


def draw_waiting(dots):
    """接続待ち画面。'Waiting for connection' の後に dots 個(0〜3)の '.' を表示。
    ドット数が変わっても位置がずれないよう、常に3文字幅で描く。"""
    oled.fill(0)
    line1 = "Waiting for"
    line2 = "connection" + "." * dots + " " * (3 - dots)
    _draw_center_text(line1, 22)
    _draw_center_text(line2, 34)
    oled_show()


def wait_for_connection():
    """USBホストに認識される(is_open)まで、待ち画面をアニメ表示して待つ。
    給電のみ(モバイルバッテリー等)では is_open にならないので、ここで待ち続ける。"""
    n = 0
    while not (_kb is not None and _kb.is_open()):
        draw_waiting(n % 4)      # 0,1,2,3 の順で 0.5秒ごとに切替（2秒周期）
        n += 1
        time.sleep_ms(500)


# ============================================================
# QRコード（Flash Modeで表示）
#   URL: https://y-trm1doc.base44.app をエンコード（バージョン2 / 25x25マス）。
#   0/1の各行がQRの1行。1=黒モジュール。
# ============================================================
QR_TEXT = """
1111111011001011001111111
1000001011101000101000001
1011101010110000101011101
1011101011010111101011101
1011101000001111101011101
1000001010001010101000001
1111111010101010101111111
0000000001010000000000000
1100111000000001000101111
1000110011110111100111010
0011101100010001101101100
1010010000110011000010110
1011011110100000011001111
1110110000010101110010010
0001011011111101000111100
0011100101110011110110110
1110111100001000111111100
0000000010110111100010000
1111111001010010101010000
1000001010101011100011110
1011101011011010111111110
1011101001011101011100111
1011101000010010001001010
1000001010111001010111110
1111111011100011000000111
"""
QR_SCALE = 2      # 1マスの拡大率[px]
QR_QUIET = 3      # 周囲の余白(クワイエットゾーン)のマス数


def draw_qr():
    """QRを白地・黒モジュールで中央に描く（読み取り用の余白付き）。"""
    rows = _parse_icon(QR_TEXT)      # 0/1テキストを行リストに（アイコンと共用）
    oled.fill(0)
    if not rows:
        _draw_center_text("Flash Mode", 28)
        oled_show()
        return
    n = len(rows)
    total = (n + 2 * QR_QUIET) * QR_SCALE      # 余白込みの一辺[px]
    x0 = (OLED_W - total) // 2
    y0 = (OLED_H - total) // 2
    if x0 < 0:
        x0 = 0
    if y0 < 0:
        y0 = 0
    # 白地（クワイエットゾーン込み）を敷いてから、黒モジュールを打つ
    oled.fill_rect(x0, y0, total, total, 1)
    off = QR_QUIET * QR_SCALE
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == "1":
                oled.fill_rect(x0 + off + c * QR_SCALE,
                               y0 + off + r * QR_SCALE,
                               QR_SCALE, QR_SCALE, 0)
    oled_show()


# 起動画面。ボタン1を押しながら起動（安全モード）のときは
# 代わりに「Flash Mode」と表示する。
if SAFE_MODE:
    # まず「Flash Mode」を3秒表示 → そのあとQRに切り替え → REPLへ
    oled.fill(0)
    _draw_center_text("Flash Mode", 28)
    oled_show()
    time.sleep(3)
    draw_qr()          # 説明ページのQRを表示（この後REPLに落ちる）
else:
    # 通常の起動画面。起動処理中から見えるよう、ここで先に描いておく
    draw_boot_screen()


# ============================================================
# USBキーボード（HID）
#   AE-RP2040をUSBキーボードとしてPCに認識させ、キー入力を送ります。
#   ・USBデバイス対応の公式MicroPython(v1.24以降推奨)が必要です。
#   ・事前にパッケージの導入が必要: usb-device-keyboard
#     （ViperIDEのパッケージマネージャから導入できます）
# ============================================================

# （USE_HID / DEVICE_NAME / MANUFACTURER / USB_VID / USB_PID / USB_SERIAL /
#   USB_MAX_POWER は先頭の設定にまとめました）


def _usb_kwargs():
    """init に渡すUSB設定を組み立てる（None の項目は渡さない＝既定のまま）。"""
    kw = {"builtin_driver": True}
    if DEVICE_NAME:            kw["product_str"] = DEVICE_NAME
    if MANUFACTURER:           kw["manufacturer_str"] = MANUFACTURER
    if USB_VID is not None:    kw["id_vendor"] = USB_VID
    if USB_PID is not None:    kw["id_product"] = USB_PID
    if USB_SERIAL is not None: kw["serial_str"] = USB_SERIAL
    if USB_MAX_POWER is not None: kw["max_power_ma"] = USB_MAX_POWER
    return kw


_kb = None
if USE_HID and not SAFE_MODE:
    try:
        import usb.device
        from usb.device.keyboard import KeyboardInterface
        # init を呼ぶとUSBが再列挙され、シリアル(REPL)が一瞬切れます。
        # 対話実行中なら、この待ち時間の間に Ctrl-C で止められます。
        time.sleep(1)
        _kb = KeyboardInterface()
        usb.device.get().init(_kb, **_usb_kwargs())   # デバイス名・各種プロパティを反映
        time.sleep(2)     # PC側が新しいキーボードを認識するまで少し待つ
    except Exception as e:
        # よくある原因:
        #  1) パッケージ未導入 → ViperIDEのパッケージマネージャで usb-device-keyboard
        #  2) 非対応ファーム(machine.USBDevice無し) → 公式MicroPythonにする
        #  3) リセットせず再実行 → 一度ハードリセット(抜き差し)してから
        print("HID初期化に失敗:", e)
        print("→ usb-device-keyboard 未導入 / 非対応ファーム / 要リセット の可能性")
        _kb = None


# HIDのキーコード（USキーボード配列）。値はHIDのusage番号。
_HID_UNSHIFTED = {
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
    "g": 0x0a, "h": 0x0b, "i": 0x0c, "j": 0x0d, "k": 0x0e, "l": 0x0f,
    "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
    "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1a, "x": 0x1b,
    "y": 0x1c, "z": 0x1d,
    "1": 0x1e, "2": 0x1f, "3": 0x20, "4": 0x21, "5": 0x22,
    "6": 0x23, "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    "\n": 0x28, "\t": 0x2b, " ": 0x2c,
    "-": 0x2d, "=": 0x2e, "[": 0x2f, "]": 0x30, "\\": 0x31,
    ";": 0x33, "'": 0x34, "`": 0x35, ",": 0x36, ".": 0x37, "/": 0x38,
}

# Shiftを押しながら打つ文字（記号）。値は上と同じキーのusage番号。
_HID_SHIFTED = {
    "!": 0x1e, "@": 0x1f, "#": 0x20, "$": 0x21, "%": 0x22,
    "^": 0x23, "&": 0x24, "*": 0x25, "(": 0x26, ")": 0x27,
    "_": 0x2d, "+": 0x2e, "{": 0x2f, "}": 0x30, "|": 0x31,
    ":": 0x33, "\"": 0x34, "~": 0x35, "<": 0x36, ">": 0x37, "?": 0x38,
}

_LEFT_SHIFT = -0x02   # モディファイア(左Shift)。この実装では負の値で表す。

# 印字されない特殊キー。キー配列やボタンで "RIGHT" のように名前で指定する。
# 値はHIDのusage番号。
_HID_SPECIAL = {
    "RIGHT": 0x4f,      # → 右矢印
    "LEFT":  0x50,      # ← 左矢印
    "DOWN":  0x51,      # ↓ 下矢印
    "UP":    0x52,      # ↑ 上矢印
    "ENTER": 0x28,      # Enter（"\n" でも可）
    "ESC":   0x29,
    "BACKSPACE": 0x2a,
    "TAB":   0x2b,
    "DELETE": 0x4c,
}


def _char_to_key(ch):
    """1文字または特殊キー名を (usage番号, Shiftが必要か) に変換。対応外は None。"""
    if ch in _HID_SPECIAL:                         # "RIGHT" などの特殊キー名
        return (_HID_SPECIAL[ch], False)
    if len(ch) != 1:                               # 特殊名でない複数文字は対象外
        return None
    if ch in _HID_UNSHIFTED:
        return (_HID_UNSHIFTED[ch], False)
    if ch in _HID_SHIFTED:
        return (_HID_SHIFTED[ch], True)
    if "A" <= ch <= "Z":                           # 大文字 = Shift + 小文字
        return (_HID_UNSHIFTED[ch.lower()], True)
    return None


def _build_keys(chars):
    """今 押し続けている文字の集合を、send_keys用のリストに変換する。
    修飾キー(Shift)は負の値で表す約束。"""
    keys = []
    shift = False
    for ch in chars:
        r = _char_to_key(ch)
        if r is None:
            continue
        usage, sh = r
        keys.append(usage)
        if sh:
            shift = True
    if shift:
        keys.insert(0, _LEFT_SHIFT)
    return keys


def hid_report(chars):
    """USBキーボードの“今この瞬間 押されているキー”を報告する。
    chars が空なら全キーを離す。押し続けている間はホスト(PC)がリピートする。

    send_keys は前のレポートが送信中だと最大 timeout_ms ブロックする。
    そこで短めのタイムアウトで1回だけ送る（リトライで待ちを重ねない）。
    間に合わなければ諦める＝ごく稀に取りこぼすが、固まらないことを優先する。"""
    if _kb is None or not _kb.is_open():
        return
    try:
        _kb.send_keys(_build_keys(chars), HID_TIMEOUT_MS)
    except Exception:
        pass                     # 送れない状況でもループは止めない


# ============================================================
# キーボード本体
# ============================================================

class PotKeyboard:
    def __init__(self):
        self.layer_idx = 0
        self.key_idx = None      # None = どの範囲にも入っていない
        self.voltage = 0.0
        self.buffer = ""

        # ボタンごとの状態（各ボタンは独立に扱う）
        n = len(buttons)
        self.btn_down = [False] * n          # 今押されているか（電気的な状態）
        self.btn_last_change = [0] * n       # 最後に状態が変わった時刻（チャタ除去用）
        self.btn_hold = [None] * n           # 各ボタンが今“押し続けている”文字（Noneなら離している）

        # 可変抵抗まわり
        self.pot_ready = False               # 起動直後の誤入力を防ぐフラグ
        self.pot_hold = None                 # POT_REPEAT時に可変抵抗が押し続けている文字

        # 表示まわり
        self.last_drawn = None               # 直前にOLEDへ描いた文字列（変化時のみ再描画）

    # --- レイヤー / キー選択 ---------------------------------
    @property
    def layer_name(self):
        return LAYER_ORDER[self.layer_idx]

    @property
    def table(self):
        return LAYERS[self.layer_name]

    @property
    def current_key(self):
        # 入力(TYPE)に使う文字＝タプルの3番目
        if self.key_idx is None:
            return None
        return self.table[self.key_idx][2]

    @property
    def current_disp(self):
        # OLED表示に使う文字列＝タプルの4番目
        # 4番目が無いタプルのときは、3番目のキー文字で代用する
        if self.key_idx is None:
            return None
        entry = self.table[self.key_idx]
        if len(entry) >= 4:
            return entry[3]
        return entry[2]

    def update_key_index(self):
        """電圧から今の範囲を求める。範囲が変わった瞬間にそのキーを入力する。"""
        v = read_voltage()
        self.voltage = v
        table = self.table
        old_idx = self.key_idx

        # いま同じ範囲(ヒステリシス付き)に留まっているか判定
        staying = False
        if self.key_idx is not None and self.key_idx < len(table):
            lo, hi = table[self.key_idx][0], table[self.key_idx][1]
            if (lo - POT_HYST_V) <= v < (hi + POT_HYST_V):
                staying = True

        if not staying:
            # 範囲を探し直す
            new_idx = None
            for i, entry in enumerate(table):
                lo, hi = entry[0], entry[1]
                if lo <= v < hi:
                    new_idx = i
                    break
            self.key_idx = new_idx
            new_ch = table[new_idx][2] if new_idx is not None else None

            # 起動直後の初回だけは、位置合わせのため入力しない
            if self.pot_ready:
                if POT_REPEAT:
                    # 範囲内なら そのキーを押し続ける／範囲外なら離す
                    self.pot_hold = new_ch
                    self.refresh_hid()
                    if new_ch is not None and new_idx != old_idx:
                        self.record(new_ch)
                else:
                    # タップ：範囲が変わった瞬間に1回だけ入力
                    if new_ch is not None and new_idx != old_idx:
                        self.tap(new_ch)
                        self.record(new_ch)
            self.pot_ready = True
        else:
            # 同じ範囲に留まり続けている
            #   POT_REPEAT=True のときは、上で押し続けたキーをそのまま保持する
            #   （報告を送り直す必要はない。連続入力はPC側が行う）
            pass

    # --- 入力の共通処理 -------------------------------------
    def held_chars(self):
        """今この瞬間 押し続けている文字を全部集める（ボタン＋可変抵抗）。"""
        chars = [c for c in self.btn_hold if c]
        if self.pot_hold:
            chars.append(self.pot_hold)
        return chars

    def refresh_hid(self):
        """押し続けているキー集合をUSBキーボードとして報告する。"""
        hid_report(self.held_chars())

    def tap(self, ch):
        """瞬間的に1回だけ入力する（押してすぐ離す）。
        押しっぱなしのボタン等は保持したまま、ch だけを一瞬足す。

        押下と解放を連続で送るとホストが押下を拾う前に解放が届き、
        取りこぼしで「押しっぱなし固まり」を起こすことがある。
        間に TAP_MS の待ちを入れて、押下→解放を確実に届ける。"""
        base = self.held_chars()
        hid_report(base + [ch])   # ch を押す（保持中のキーは押したまま）
        time.sleep_ms(TAP_MS)     # ホストが押下を拾う時間を確保
        hid_report(base)          # ch を離す（保持中のキーはそのまま）

    def record(self, ch):
        """内部バッファへの記録とデバッグ表示（HIDとは別。動作確認用）。"""
        if not ch:
            return
        self.buffer += ch
        if len(self.buffer) > MAX_BUFFER:
            self.buffer = self.buffer[-MAX_BUFFER:]
        print("KEY:", repr(ch))

    # --- ボタン入力 -----------------------------------------
    def poll_buttons(self):
        """各ボタンを独立に見る。押した瞬間からキーを押し続け、離した瞬間に解除する。
        （長押し中の“同じ文字の連続入力”はPC側が行う。ここでは連打しない。）"""
        now = time.ticks_ms()
        for i, b in enumerate(buttons):
            pressed = (b.value() == 0)      # GND接続なので0が押下

            if pressed == self.btn_down[i]:
                continue                    # 状態変化なし → 何もしない（押し続けたまま）

            # 状態が変わった瞬間（チャタリングが速すぎるものは無視）
            if time.ticks_diff(now, self.btn_last_change[i]) < DEBOUNCE_MS:
                continue
            self.btn_last_change[i] = now
            self.btn_down[i] = pressed

            key = BUTTON_KEYS[i]
            if pressed:
                # 押した瞬間
                if len(key) == 1 or key in _HID_SPECIAL:
                    # 1キー（通常文字 or "RIGHT"等）→ そのキーを“押し続ける”（本物の長押し）
                    self.btn_hold[i] = key
                    self.refresh_hid()
                else:
                    # 複数文字の文字列は押し続けられないので、その場で順に打つ
                    for c in key:
                        self.tap(c)
                self.record(key)
            else:
                # 離した瞬間 → 押し続けを解除
                if self.btn_hold[i]:
                    self.btn_hold[i] = None
                    self.refresh_hid()

    # --- 表示 -----------------------------------------------
    def draw(self):
        # 可変抵抗で今選んでいるマスコンのラベル(タプルの4番目)を、
        # 埋め込みフォントで大きくきれいに表示する。
        # 表示が変わったときだけ書き込む（I2C負荷を抑えENODEV対策）。
        s = self.current_disp
        if s is None:
            s = "-"          # どの範囲にも入っていないとき
        if s == self.last_drawn:
            return
        self.last_drawn = s
        draw_label(s)

    # --- メインループ ---------------------------------------
    def run(self):
        # ウォッチドッグ：万一ループが固まっても、feed が途絶えれば自動リセットで復帰。
        wdt = None
        if USE_WATCHDOG:
            try:
                from machine import WDT
                wdt = WDT(timeout=WATCHDOG_MS)
            except Exception:
                wdt = None      # 対応していない環境なら無効のまま続行

        tick = 0
        while True:
            try:
                self.update_key_index()
                self.poll_buttons()
                self.draw()
            except Exception as e:
                # 1回のエラーでプログラム全体を止めない（次のループで復帰を試みる）
                print("loop error:", e)

            if wdt:
                wdt.feed()      # 生きている印。これが途絶えると自動リセット

            # 長時間動かすとメモリが断片化してMemoryErrorで固まることがあるので、
            # ときどき明示的にゴミ回収しておく。
            tick += 1
            if tick >= 200:
                tick = 0
                gc.collect()

            time.sleep_ms(10)


if __name__ == "__main__":
    if SAFE_MODE:
        # ボタン1を押しながら起動 → 何も始めずここで終了し、REPLに戻る。
        # ウォッチドッグもループも無いので、落ち着いてソースを書き換えられる。
        print("SAFE MODE: メインを開始しません。REPLで編集できます。")
    else:
        # 1) 起動画面（上で描画済み）を BOOT_HOLD_S 秒見せる
        time.sleep(BOOT_HOLD_S)

        # 2) USBホスト(PC)に認識されるまで "Waiting for connection..." で待つ
        #    給電のみ(モバイルバッテリー等)ではここで待ち続け、マスコンには移行しない
        if USE_HID and _kb is not None:
            wait_for_connection()

        # 3) 接続された → マスコンを開始
        PotKeyboard().run()