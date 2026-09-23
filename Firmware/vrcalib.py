# -*- coding: utf-8 -*-
"""
可変抵抗(VR)の電圧測定ツール  /  AE-RP2040 + MicroPython

マスコンのレバーを各ノッチに合わせながら、このスクリプトを実行して
表示される電圧を読み取ってください。その値をもとに、本体コード
(pot_keyboard.py) の LAYERS の電圧しきい値を決められます。

配線（本体コードと同じ）
  可変抵抗の中点 → ADC0 (GP26)、両端は 3V3 と GND

使い方
  このファイルを実行すると、電圧を繰り返し表示し続けます。
  レバーを各位置に止めて、そのときの電圧をメモしてください。
  止めるときは Ctrl-C（Thonnyなら停止ボタン）。
"""

from machine import ADC, Pin
import time

# ---- 設定（本体コードに合わせています）----
PIN_POT = 26          # ADC0
VREF = 3.3            # ADCの基準電圧[V]
SAMPLES = 16          # 平均化するサンプル数（多いほど安定、少ないほど反応が速い）
INTERVAL_MS = 200     # 表示の更新間隔[ms]

pot = ADC(PIN_POT)


def read_voltage():
    """可変抵抗の電圧[V]と、生の16bit値を返す。"""
    total = 0
    for _ in range(SAMPLES):
        total += pot.read_u16()
    raw = total // SAMPLES
    return raw / 65535.0 * VREF, raw


def main():
    print("VR電圧測定を開始します。レバーを各位置に止めて電圧を読んでください。")
    print("止めるには Ctrl-C（Thonnyなら停止ボタン）。")
    print("-" * 40)

    vmin = 99.0        # これまでに見た最小/最大（ノッチのブレ確認用）
    vmax = 0.0
    try:
        while True:
            v, raw = read_voltage()
            if v < vmin:
                vmin = v
            if v > vmax:
                vmax = v
            pct = v / VREF * 100
            # 例:  1.234 V  | raw 24512 | 37.4% | min 0.001 max 3.299
            print("{:5.3f} V | raw {:5d} | {:5.1f}% | min {:.3f} max {:.3f}"
                  .format(v, raw, pct, vmin, vmax))
            time.sleep_ms(INTERVAL_MS)
    except KeyboardInterrupt:
        print("-" * 40)
        print("終了しました。")


if __name__ == "__main__":
    main()