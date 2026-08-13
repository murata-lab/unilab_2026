# 電車ストップチャレンジ UI

ローカルサーバー経由で開くと、運転席風の画面が表示されます。

- 左: 下から上へ進む縦いっぱいの進行度
- 中央: カメラ映像
- 右: 加速中・減速中の表示、大きな速度計、経過時間

カメラ内で肩と両手首が見えるように立ちます。手首同士の水平距離を肩幅と比べて制御します。

- 手の間隔が肩幅より広い: アクセル
- 手の間隔が肩幅より狭い: ブレーキ
- 肩幅くらい: 速度キープ

手動で値を入れる場合は、ブラウザ上で次の関数を呼びます。

```js
window.updateTrainUI({
  positionMeters: 90,
  speedMps: 13.3,
});
```

カメラとAIモデルが起動すると、ポーズに合わせて自動で速度と進行度が動きます。
使用モデル : Google MediaPipe Tasks Vision

MediaPipeの実行ファイルと姿勢推定モデルは `assets/mediapipe/` にローカル配置しています。ネット接続なしでも、Pythonサーバー経由で開けばモデルを読み込めます。

## Pythonバックエンド

実機制御に近い形で動かす場合は、Pythonサーバーを起動します。

```bash
python3 train_control_server.py
```

カメラ入力なしでPython内部の擬似信号だけで動かす場合:

```bash
python3 train_control_server.py --control-source pseudo
```

このモードでは台車BへTCP接続せず、ローカルの簡易デモとして動きます。
デモの見た目の速さは `train_control_server.py` 上部の `LOCAL_DEMO_ACCELERATION_MPS2` / `LOCAL_DEMO_BRAKE_MPS2` で調整できます。これは台車へ送る `[A...]` には影響しません。

一定周期でなめらかに加減速させる場合:

```bash
python3 train_control_server.py --control-source pseudo --pseudo-pattern wave
```

ブラウザで開くURL:

```text
http://127.0.0.1:5173/
```

ブラウザは姿勢から得た `control` をWebSocketでPythonへ送り、Pythonが速度・位置・安全制御を管理します。Pythonが起動していない場合、ブラウザ内の簡易計算にフォールバックします。

実機とTCPでつなぐ場合:

```bash
python3 train_control_server.py
```

接続先IP、ポート、加速度、ブレーキは `train_control_server.py` 上部の `DEVICE_HOST` / `DEVICE_PORT` / `DEFAULT_ACCELERATION_MPS2` / `DEFAULT_BRAKE_MPS2` を書き換えます。

TCPでは角括弧で囲った短いコマンドを送受信します。

Pythonから台車へ送る加速度指令:

```text
[A100]
[A-300]
[A0]
```

`A` は加速度指令で、単位は `mm/s^2` です。正の値は加速、負の値は減速、0は加速度なしです。内部設定は `m/s^2` なので、たとえば `DEFAULT_ACCELERATION_MPS2 = 0.1` は最大加速時に `[A100]` を送ります。

台車からPythonへ返す停止目標までの残距離:

```text
[D1022]
[D-20]
[T1234]
```

`T` は台車から返す経過時間で、単位は `ms` です。たとえば `[T1234]` は `1.234秒` として扱います。`[T...]` を受信した後は、UIの経過時間表示はPC側のローカル時間ではなく、この受信値を使います。

`D` は停止目標までの残距離で、単位は `mm` です。正の値は目標手前、負の値は目標を通過した量として扱います。走り出してから最初に停止したと判定された時点の `D` が一発勝負のスコアになります。
UIの「停止位置まで」は、この `[D...]` の値をそのまま表示します。たとえば `[D1022]` は `あと 1022mm`、`[D-20]` は `20mm オーバー` と表示します。`[D...]` がまだ届いていない間は `未受信` と表示します。

停止判定は `train_control_server.py` 上部の次の値で調整します。

```python
DEFAULT_STOP_SPEED_THRESHOLD_MPS = 0.02
DEFAULT_STOP_HOLD_SECONDS = 0.5
DEFAULT_START_DISTANCE_THRESHOLD_MM = 5
```

- `DEFAULT_START_DISTANCE_THRESHOLD_MM`: 最初の `[D...]` から何mm変化したら「走り出した」とみなすか。初期値は `5mm` です。
- `DEFAULT_STOP_SPEED_THRESHOLD_MPS`: この速度以下なら「ほぼ停止」とみなします。初期値の `0.02m/s` は `20mm/s` です。
- `DEFAULT_STOP_HOLD_SECONDS`: 「ほぼ停止」の状態が何秒続いたら本当に停止と判定するか。初期値は `0.5秒` です。

判定の流れは、`[D...]` が最初に届く、`D` が `5mm` 以上変化して走行開始、速度が `0.02m/s` 以下になる、その状態が `0.5秒` 続いたら、その時点の `D` をスコアとして確定、という順です。

加速・ブレーキの強さは `train_control_server.py` 上部の `DEFAULT_ACCELERATION_MPS2` / `DEFAULT_BRAKE_MPS2` で調整できます。

## スコア計算

`T` キーを押すと、その時点で最後に受信した残距離と経過時間から100点満点のスコアを計算します。
計算に使う設定値は `script.js` 上部にあります。

```js
const SCORE_DISTANCE_WEIGHT = 0.7;
const SCORE_TIME_WEIGHT = 0.3;
const SCORE_SHORT_DECAY_RATE = 0.64;
const SCORE_OVERSHOOT_DECAY_RATE = 0.8;
const SCORE_OVERSHOOT_SOFT_LIMIT_METERS = 0.6;
const SCORE_MAX_OVERSHOOT_ERROR_METERS = 1.8;
const SCORE_BEST_ELAPSED_SECONDS = 9.5;
const SCORE_MAX_ELAPSED_SECONDS = 15;
const SCORE_MIN_TIME_SCORE = 1 / 3;
```

### 距離スコア

台車から受信した `[D...]` をmmからmへ変換し、目標位置からの誤差として使用します。`D` が正なら目標手前、負なら目標超過として扱います。

```text
手前距離(m) = D / 1000
手前距離スコア = exp(-0.64 × 手前距離) × 100

超過距離(m) = abs(D) / 1000

0.6mまでの超過:
超過距離スコア = exp(-0.8 × 超過距離) × 100

0.6mを超える超過:
0.6m超過時点スコア = 約62
進みすぎ率 = clamp((超過距離 - 0.6) / (1.8 - 0.6), 0, 1)
超過距離スコア = 0.6m超過時点スコア × (1 - 進みすぎ率) ^ 2
```

- `[D0]`: 距離スコア100点
- `[D200]`: 距離スコア約88点
- `[D500]`: 距離スコア約73点
- `[D1000]`: 距離スコア約53点
- `[D1500]`: 距離スコア約38点
- `[D2000]`: 距離スコア約28点
- `[D3000]`: 距離スコア約15点
- `[D4000]`: 距離スコア約8点
- `[D-200]`: 距離スコア約85点
- `[D-500]`: 距離スコア約67点
- `[D-600]`: 距離スコア約62点
- `[D-1000]`: 距離スコア約28点
- `[D-1500]`: 距離スコア約4点
- `[D-1800]` 以上の超過: 距離スコア0点
- `[D...]` が未受信: 距離スコア0点

### 時間スコア

台車から受信した `[T...]` をmsから秒へ変換して使用します。9.5秒までは満点、15秒以上でも約33点は残る設定です。

```text
経過時間(秒) = T / 1000

9.5秒以下:
時間スコア = 100

9.5秒を超える場合:
進み具合 = clamp(1 - (経過時間 - 9.5) / (15 - 9.5), 0, 1)
時間スコア = (1 / 3 + 2 / 3 × 進み具合) × 100
```

- `[T9500]` 以下: 時間スコア100点
- `[T10000]`: 時間スコア約94点
- `[T11000]`: 時間スコア約82点
- `[T12000]`: 時間スコア約70点
- `[T13000]`: 時間スコア約58点
- `[T14000]`: 時間スコア約45点
- `[T15000]` 以上: 時間スコア約33点

擬似モードでは台車から `[T...]` が届かないため、Python内部の疑似経過時間を使用し、最初に停止した時点で時間を止めます。

### 最終スコア

距離スコアを70%、時間スコアを30%として合成し、最後に四捨五入します。

```text
最終スコア = round(距離スコア × 0.7 + 時間スコア × 0.3)
```

例として、2m手前で経過時間が12秒の場合、距離スコア約28点、時間スコア約70点なので、最終スコアは約40点です。
1m超過で経過時間が12秒の場合、距離スコア約28点、時間スコア約70点なので、最終スコアは約40点です。
重み、手前側と超過側の許容誤差、時間が0点になる秒数は、上記の `script.js` の定数を変更して調整できます。

## TCP送受信だけ確認する

ゲームUIを起動せず、台車Bとの `[A...]` 送信と `[D...]` 受信だけを確認する場合:

```bash
python3 tcp_send_receive_probe.py
```

接続先は `tcp_send_receive_probe.py` 上部の `DEVICE_HOST` / `DEVICE_PORT` を書き換えます。標準では `[A100]`, `[A0]`, `[A-300]`, `[A0]` を1秒間隔で送ります。

送る値を起動時に変える場合:

```bash
python3 tcp_send_receive_probe.py --values 100,0,-300,0 --interval 1.0
```
