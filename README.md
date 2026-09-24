# TrainMasconV1

自作ゲーム「[Tozai Sim Pro](https://tozai-sim.base44.app/)」用の、USBキーボードとして動作する自作マスコン（主幹制御器）コントローラーです。
可変抵抗（2連ボリューム）のレバー位置を読み取り、ノッチ（P4〜N〜B7〜EB）に応じたキー入力をPCへ送ります。
現在のノッチは0.96インチOLEDに大きく表示されます。

- マイコン: AE-RP2040（MicroPython）
- 表示: SSD1306 OLED 128x64（I2C）
- 入力: 可変抵抗 1個（ADC）＋ ボタン 3個
- 接続: USB HID キーボード

ドキュメント: <https://y-trm1doc.base44.app/>

## ディレクトリ構成

```
Firmware/
  LICENSE                               ソフトウェアのライセンス（MIT）
  main.py                               本体ファームウェア（ノッチ→キー入力、OLED表示、USB HID）
  vrcalib.py                            可変抵抗の電圧測定ツール（ノッチ境界の電圧調整用）
Hardware/
  Enclosure/                            3Dプリント用ケース
    TRM1-Case-Top.stl                   ケース上部
    TRM1-Case-Bottom.stl                ケース下部
    TRM1-Case-Handle.stl                ハンドル
    TRM1-Case-Handle-Stopper.stl        ハンドルのストッパー
  PCB/                                  基板データ
    ProPrj_Mascon_2026-09-23.epro2      EasyEDA Pro の原本
    kicad_output/                       KiCad 8 変換版
      Mascon.kicad_pro                  KiCad プロジェクトファイル
      Mascon.kicad_sch                  回路図
      Mascon.kicad_pcb                  基板
      Mascon.kicad_sym                  シンボルライブラリ
      Mascon.kicad_footprints.pretty/   フットプリントライブラリ（.kicad_mod 8点）
      fp-lib-table                      フットプリントライブラリ設定
      sym-lib-table                     シンボルライブラリ設定
      CONVERSION_NOTES.md               変換時の注意事項
  LICENSE                               ハードウェアのライセンス（CERN-OHL-P v2）
README.md                               このファイル
```

## 配線

| 部品 | ピン |
|---|---|
| OLED SDA / SCL | GP20 / GP19（SoftI2C, アドレス 0x3C） |
| ボタン1 / 2 / 3 | GP23 / GP24 / GP25（GND側に接続） |
| 可変抵抗（中点） | GP26 (ADC0)、両端は 3V3 と GND |

## セットアップ

1. AE-RP2040 に MicroPython を書き込みます。
2. 必要なライブラリを導入します。
   ```
   mpremote mip install ssd1306
   mpremote mip install usb-device-keyboard
   ```
3. `Firmware/main.py` を `main.py` として本体に転送します。
4. USBで接続すると、キーボードとして認識されます。

## ノッチの調整

1. `Firmware/vrcalib.py` を実行し、レバーを各ノッチに合わせたときの電圧を読み取ります。
2. `main.py` の `LAYERS` の電圧しきい値（下限V, 上限V）を書き換えます。

既定のキー割り当ては次のとおりです（電圧の低い側から）。

| ノッチ | P4 | P3 | P2 | P1 | N | B1〜B6 | B7 | EB |
|---|---|---|---|---|---|---|---|---|
| キー | 1 | 2 | 3 | 4 | → | 5, 6, 7, 8, 9, 0 | - | Space |

ボタン1を押しながら起動すると安全モード（HID初期化とメインループを行わない）になり、ファイルを編集できます。

## ハードウェア

- `Hardware/PCB/ProPrj_Mascon_2026-09-23.epro2` が基板の原本です。
- `Hardware/PCB/kicad_output/` は KiCad 8 向けの変換結果です（開く場合は `Mascon.kicad_pro` を指定します）。KiCad での動作確認は未実施のため、開く際は [CONVERSION_NOTES.md](Hardware/PCB/kicad_output/CONVERSION_NOTES.md) を確認してください。
- ケースのSTL（`Hardware/Enclosure/` 内の `TRM1-Case-*.stl` 4点）についての注意:
  - サポート材は含まれていません。造形方向やプリンターに応じて、必要ならスライサー側で追加してください。
  - 薄肉部分やクリアランス（はめ合いの隙間）は十分に考慮されていません。
  - そのため、3Dプリントサービスに発注するか、自分で造形する場合は精度の非常に高いプリンター（光造形など）が必要です。一般的なFDMプリンターでは、そのままでは組み立てられない可能性があります。

## ライセンス

ライセンスは、対象ごとにそれぞれのフォルダ内の `LICENSE` に記載されています。

| 対象 | ライセンス | ファイル |
|---|---|---|
| ハードウェア（`Hardware/` 配下: 基板、回路図、ケース） | [CERN-OHL-P v2](Hardware/LICENSE) | `Hardware/LICENSE` |
| ソフトウェア（`Firmware/` 配下） | [MIT](Firmware/LICENSE) | `Firmware/LICENSE` |

SPDX: `CERN-OHL-P-2.0`（ハードウェア）/ `MIT`（ソフトウェア）

[SCANOSS](https://www.scanoss.com/) によるスキャンでは、全ファイルで既存OSSとの一致は検出されませんでした（2026-09-24時点）。

---

# TrainMasconV1

A custom mascon (master controller) controller for my original game "[Tozai Sim Pro](https://tozai-sim.base44.app/)", which operates as a USB keyboard.
It reads the lever position of a variable resistor (dual-gang potentiometer) and sends key inputs to the PC according to the notch (P4〜N〜B7〜EB).
The current notch is displayed prominently on a 0.96-inch OLED.

- Microcontroller: AE-RP2040 (MicroPython)
- Display: SSD1306 OLED 128x64 (I2C)
- Input: 1 variable resistor (ADC) + 3 buttons
- Connection: USB HID keyboard

Documentation: <https://y-trm1doc.base44.app/>

## Directory Structure

```
Firmware/
  LICENSE                               Software license (MIT)
  main.py                               Main firmware (notch→key input, OLED display, USB HID)
  vrcalib.py                            Variable resistor voltage measurement tool (for adjusting notch boundary voltages)
Hardware/
  Enclosure/                            3D-printable case
    TRM1-Case-Top.stl                   Case top
    TRM1-Case-Bottom.stl                Case bottom
    TRM1-Case-Handle.stl                Handle
    TRM1-Case-Handle-Stopper.stl        Handle stopper
  PCB/                                  PCB data
    ProPrj_Mascon_2026-09-23.epro2      EasyEDA Pro original
    kicad_output/                       KiCad 8 converted version
      Mascon.kicad_pro                  KiCad project file
      Mascon.kicad_sch                  Schematic
      Mascon.kicad_pcb                  PCB layout
      Mascon.kicad_sym                  Symbol library
      Mascon.kicad_footprints.pretty/   Footprint library (8 .kicad_mod files)
      fp-lib-table                      Footprint library table
      sym-lib-table                     Symbol library table
      CONVERSION_NOTES.md               Notes on the conversion
  LICENSE                               Hardware license (CERN-OHL-P v2)
README.md                               This file
```

## Wiring

| Component | Pin |
|---|---|
| OLED SDA / SCL | GP20 / GP19（SoftI2C, address 0x3C） |
| Button 1 / 2 / 3 | GP23 / GP24 / GP25（connected to GND） |
| Variable resistor (center tap) | GP26 (ADC0), both ends to 3V3 and GND |

## Setup

1. Flash MicroPython onto the AE-RP2040.
2. Install the required libraries.
   ```
   mpremote mip install ssd1306
   mpremote mip install usb-device-keyboard
   ```
3. Transfer `Firmware/main.py` to the device as `main.py`.
4. When connected via USB, it will be recognized as a keyboard.

## Notch Adjustment

1. Run `Firmware/vrcalib.py` and measure the voltage when the lever is set to each notch.
2. Rewrite the voltage thresholds (lower limit V, upper limit V) in `LAYERS` in `main.py`.

The default key assignments are as follows (from the lower-voltage side).

| Notch | P4 | P3 | P2 | P1 | N | B1〜B6 | B7 | EB |
|---|---|---|---|---|---|---|---|---|
| Key | 1 | 2 | 3 | 4 | → | 5, 6, 7, 8, 9, 0 | - | Space |

Starting while holding Button 1 enters safe mode (HID initialization and the main loop are not executed), allowing files to be edited.

## Hardware

- `Hardware/PCB/ProPrj_Mascon_2026-09-23.epro2` is the original PCB design file.
- `Hardware/PCB/kicad_output/` contains the conversion results for KiCad 8 (open `Mascon.kicad_pro` to load the project). Since operation in KiCad has not been verified, check [CONVERSION_NOTES.md](Hardware/PCB/kicad_output/CONVERSION_NOTES.md) when opening the files.
- Notes on the case STL files (the four `TRM1-Case-*.stl` files in `Hardware/Enclosure/`):
  - Support material is not included. Add it in the slicer as necessary depending on the print orientation and printer.
  - Thin sections and clearances (gaps for fitting) have not been sufficiently taken into consideration.
  - Therefore, if ordering from a 3D printing service, or printing it yourself, a very high-precision printer (such as a resin printer) is required. With a typical FDM printer, it may not be possible to assemble it as-is.

## License

The license for each part is provided in the `LICENSE` file inside the corresponding folder.

| Target | License | File |
|---|---|---|
| Hardware (PCB, schematics, and case under `Hardware/`) | [CERN-OHL-P v2](Hardware/LICENSE) | `Hardware/LICENSE` |
| Software (under `Firmware/`) | [MIT](Firmware/LICENSE) | `Firmware/LICENSE` |

SPDX: `CERN-OHL-P-2.0` (hardware) / `MIT` (software)

According to a scan by [SCANOSS](https://www.scanoss.com/), no matches with existing OSS were detected across all files (as of 2026-09-24).
