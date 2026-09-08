# Human Tower Battle 2026

ゲーム本体は `games/main.py` です。仮想環境とSAM2 checkpointは容量が大きく、PCごとに作り直せるため、このリポジトリには含めません。

## 新しいPCでの初回セットアップ（macOS）

リポジトリをcloneまたはコピーした後、このディレクトリへ移動します。

```bash
cd human_tower_battle_2026
```

iCloudによる退避を避けるため、仮想環境はDesktop外に作ります。

```bash
mkdir -p ~/.venvs
python3 -m venv ~/.venvs/human_tower_battle_2026
~/.venvs/human_tower_battle_2026/bin/python -m pip install --upgrade pip
~/.venvs/human_tower_battle_2026/bin/python -m pip install -r requirements.txt
```

SAM2 checkpoint（約856 MiB）を取得します。

```bash
bash sam2/checkpoints/download_ckpts.sh
```

## 起動

まずカメラ番号を確認します。

```bash
~/.venvs/human_tower_battle_2026/bin/python games/camera_check.py
open camera_check_output/contact_sheet.jpg
```

比較画像で確認した番号を指定して起動します。次はカメラ2番の例です。

```bash
HTB_CAMERA_INDEX=2 ~/.venvs/human_tower_battle_2026/bin/python games/main.py
```

頭から足までをプレビュー内に入れ、切り抜きたい人物の胴体をクリックしてください。複数人が映る場合は対象の全身をドラッグで囲みます。右上が緑色の「クリック指定済み」または「範囲指定済み」になったら `Enter` で撮影します。右クリックで指定を解除できます。指定しない場合は従来の自動検出が使われます。

カメラやSAM2を使わず画面と物理挙動だけ確認する場合:

```bash
HTB_DEMO_MODE=1 ~/.venvs/human_tower_battle_2026/bin/python games/main.py
```

外部モニター左側の縦画面に出す場合:

```bash
HTB_USE_EXTERNAL_MONITOR=1 ~/.venvs/human_tower_battle_2026/bin/python games/main.py
```

ウィンドウサイズや倍率も指定できます。

```bash
HTB_WINDOW_WIDTH=720 HTB_WINDOW_HEIGHT=1245 ~/.venvs/human_tower_battle_2026/bin/python games/main.py
HTB_WINDOW_SCALE=0.9 ~/.venvs/human_tower_battle_2026/bin/python games/main.py
```

macOSでカメラが拒否される場合は、「システム設定 > プライバシーとセキュリティ > カメラ」で使用するターミナルまたはPythonを許可し、ターミナルを再起動してください。

人物の切り抜きに失敗する場合は、診断画像を保存してマスクと人物検出枠を確認できます。

```bash
HTB_SAVE_SEGMENT_DEBUG=1 HTB_CAMERA_INDEX=2 ~/.venvs/human_tower_battle_2026/bin/python games/main.py
open segmentation_debug
```

診断画像は `segmentation_debug/` に保存され、Gitには含まれません。

## 移行時に含めないもの

- `.venv*`: Python仮想環境（移行先で再作成）
- `sam2/checkpoints/*.pt*`: SAM2モデル（スクリプトで再取得）
- `camera_check_output/`: カメラ確認時の一時画像
- `segmentation_debug/`: 人物切り抜きの診断画像
- `__pycache__/`, `.DS_Store`: 自動生成キャッシュ
