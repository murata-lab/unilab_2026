# 声でスイカ割り！

Voskで認識した声だけでキャラクターを動かし、1分間にスイカを何個割れるかを競うゲームです。

## インストール

このゲームでは、次のツールを使用します。

- Node.js（`npm`はNode.jsと一緒にインストールされます）
- `uv`（PythonとPythonパッケージの管理に使用します）
- Python 3.13（後述の`uv`コマンドでインストールできます）

### macOS

#### 1. Node.jsとnpmをインストールする

[Node.js公式サイト](https://nodejs.org/ja)からLTS版のインストーラーをダウンロードし、案内に従ってインストールします。`npm`も一緒にインストールされます。

インストール後、新しくターミナルを開いて確認します。

```bash
node --version
npm --version
```

#### 2. uvをインストールする

ターミナルで次を実行します。

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

ターミナルを開き直してから確認します。

```bash
uv --version
```

`uv: command not found`と表示される場合は、次を実行してから、もう一度確認してください。

```bash
export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

### Windows

以下のコマンドは、コマンドプロンプトではなくPowerShellで実行してください。

#### 1. Node.jsとnpmをインストールする

[Node.js公式サイト](https://nodejs.org/ja)からLTS版のWindowsインストーラーをダウンロードし、案内に従ってインストールします。`npm`も一緒にインストールされます。

インストール後、開いているPowerShellをすべて閉じ、新しくPowerShellを開いて確認します。

```powershell
node --version
npm --version
```

#### 2. uvをインストールする

PowerShellで次を実行します。

```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

PowerShellを開き直してから確認します。

```powershell
uv --version
```

#### Windowsで「コマンドが見つからない」と表示される場合

`node`、`npm`、または`uv`が認識されない場合は、インストール先が環境変数`Path`に登録されていない可能性があります。

まず、現在開いているPowerShellだけで使えるようにします。

```powershell
$env:Path += ";C:\Program Files\nodejs;$env:USERPROFILE\.local\bin"
```

続いて、次回以降に開くPowerShellでも使えるように、ユーザーの`Path`へ登録します。

```powershell
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$addPath = @("C:\Program Files\nodejs", "$env:USERPROFILE\.local\bin")
$newPath = (($userPath -split ";") + $addPath | Where-Object { $_ } | Select-Object -Unique) -join ";"
[Environment]::SetEnvironmentVariable("Path", $newPath, "User")
```

PowerShellをすべて閉じて開き直し、次のコマンドで確認してください。

```powershell
node --version
npm --version
uv --version
```

Node.jsのインストール先を変更した場合は、`C:\Program Files\nodejs`を実際のインストール先に置き換えてください。

### ゲームに必要なものをインストールする（macOS・Windows共通）

ターミナルまたはPowerShellで、このリポジトリのフォルダーへ移動してから、次のコマンドを順番に実行します。

```bash
uv python install 3.13
npm install
uv venv --python 3.13
uv sync
```

`uv run`が仮想環境を自動的に使用するため、仮想環境を手動で有効化する必要はありません。

Voskの日本語モデルは、音声接続の初回に自動でダウンロードされます。

## 起動方法

ターミナルまたはPowerShellを2つ開き、どちらもこのリポジトリのフォルダーへ移動します。

1つ目で音声認識サーバーを起動します。

```bash
uv run python main.py
```

2つ目でゲームを起動します。

```bash
npm run dev
```

ブラウザで <http://127.0.0.1:5173> が自動的に開きます。ゲーム右上の表示が「マイク：ON」になれば音声で操作できます。

macOSでは、初回起動時にターミナルのマイク使用を許可してください。

### ビルド版の起動

先にフロントエンドをビルドすると、FastAPIがゲームも配信します。

```bash
npm run build
uv run python main.py
```

ブラウザで <http://127.0.0.1:8000> を開いてください。

## 基本的な遊び方

- 縦5×横7のグリッドを、キャラクターが向いている方向を基準に移動
- 「すすめ」1回で、向いている方向へ1マスを約1秒で移動
- 「とまれ」で現在の1マスを移動し終えて停止
- 「みぎ」「ひだり」で90度方向転換
- 「たたけ」で停止してから、正面1マス先のスイカを叩く
- 通常スイカは1点、10%で出る金のスイカは3点
- カニを叩くと2点。カニは止まって点滅し、1秒後に消える
- カニとの接触と攻撃が同時に成立した場合は、攻撃が優先される
- フィールド上には常に3個のスイカを配置
- 開始10秒後にカニが1体、残り30秒から最大2体が左右どちらかの画面端から横断
- Hardモードでは開始時からカニが2体、開始30秒後から最大4体が横断し、再出現も1〜2秒と速くなる
- カニは出現する列の画面端に1秒間の警告を表示し、横断後は2〜5秒後に再出現
- カニに触れるとキャラクターが赤く点滅し、3秒間すべての操作が無効
- タイトル画面で「通常モード」「Hardモード」「単語変更モード」から選択
- 単語変更モードでは、5つの操作へ空白なしのひらがなを1語ずつ登録
- 登録内容は開始後15秒まで表示し、その後5秒間点滅して消える
- Spaceキーで3秒のカウントダウンを開始し、制限時間は60秒
- 終了後は同じ言葉で再挑戦、単語の再登録、タイトルへ戻る操作を選択

音声認識が使えない場合も、矢印キーとSpaceキーで全操作を確認できます。画面内の「全画面」ボタンまたは`F`キーで全画面表示を切り替えられます。`G`キーを押すと開発確認用のグリッドを表示します。

制限時間や移動時間、カニの出現間隔などのゲーム設定は`src/game/config.ts`で変更できます。開発サーバー（ポート5173）は変更を自動反映します。ビルド版（ポート8000）で確認する場合は、変更後に`npm run build`を実行して`dist`を更新してください。

## 使用技術

- ゲーム：Phaser 3.90.0、TypeScript、Vite
- サーバー：FastAPI、WebSocket
- 音声認識：Vosk
- マイク入力：sounddevice

## 音声入力の設定

既定以外のマイクや、展開済みのVoskモデルを使う場合は環境変数で指定できます。

macOSの場合：

```bash
AUDIO_DEVICE=0 uv run python main.py
VOSK_MODEL_PATH=/path/to/vosk-model-small-ja-0.22 uv run python main.py
```

Windows PowerShellの場合：

```powershell
$env:AUDIO_DEVICE = "0"
uv run python main.py
```

```powershell
$env:VOSK_MODEL_PATH = "C:\path\to\vosk-model-small-ja-0.22"
uv run python main.py
```

利用可能なマイクは次のコマンドで確認できます。

```bash
uv run python -m test.vosk_microphone --list-devices
```

マイク認識だけを試す場合は次を実行します。

```bash
uv run python -m test.vosk_microphone
```

## テスト

```bash
npm run build
uv run --with pytest python -m pytest -q
```

## 画像素材

- 背景：`assets/backgrounds/beach.png`
- キャラクター：`assets/sprites/character-pose-sheet.png`
- スイカ：`assets/sprites/watermelon-break-sheet-normalized.png`
- カニ：`assets/sprites/crab-walk-sheet-normalized.png`

生成元のマゼンタ背景付き画像は`assets/sprites/source/`に保存しています。

変更がうまく反映されない場合は、ブラウザを強制再読み込みしてください。macOSでは`Command + Shift + R`、Windowsでは`Ctrl + F5`で実行できます。
