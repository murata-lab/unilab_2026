import pygame
import os
from animal import Animal
from game import create_space
from photo import (
    capture_from_existing_camera,
    detect_person_box,
    get_last_capture_error,
)
from screens import StartScreen, GameOverScreen
from ranking import RankingManager
from camera_utils import open_camera, parse_camera_indices, print_camera_help
from paths import (
    BACKGROUND_IMAGE,
    SAM2_CHECKPOINT,
    SAM2_CONFIG,
    ensure_sam2_import_path,
)
import cv2

# ウィンドウを外部モニターに配置（pygame.init()の前に設定）
# 外部モニターは1440×2489、メインディスプレイは1536×960
# 外部モニターが左側にある場合（負の座標を使用）
BASE_WIDTH, BASE_HEIGHT = 1440,2489

NAVY = (8, 22, 54)
PANEL = (11, 32, 72, 220)
PANEL_LIGHT = (22, 58, 108, 220)
CYAN = (44, 210, 224)
GREEN = (74, 224, 145)
CORAL = (255, 94, 112)
GOLD = (255, 198, 78)
WHITE = (246, 250, 255)
MUTED = (184, 205, 232)

CAMERA_PREVIEW_RECT = pygame.Rect(850, 120, 540, 405)
ACTION_PANEL_RECT = pygame.Rect(70, 360, 720, 175)
PIECE_TARGET_MASK_AREA = max(5_000, int(os.environ.get("HTB_PIECE_MASK_AREA", "20250")))
window_x = -1440 + 50  # 外部モニターの左端から50ピクセル（負の座標）
window_y = 50  # 上端から50ピクセル下
if os.environ.get("HTB_USE_EXTERNAL_MONITOR") == "1":
    os.environ['SDL_VIDEO_WINDOW_POS'] = f"{window_x},{window_y}"


def fit_size(max_width, max_height):
    scale = min(max_width / BASE_WIDTH, max_height / BASE_HEIGHT)
    scale *= float(os.environ.get("HTB_WINDOW_SCALE", "1.0"))
    width = max(1, int(BASE_WIDTH * scale))
    height = max(1, int(BASE_HEIGHT * scale))
    return width, height


def initial_window_size(display_width, display_height):
    explicit_width = os.environ.get("HTB_WINDOW_WIDTH")
    explicit_height = os.environ.get("HTB_WINDOW_HEIGHT")
    if explicit_width and explicit_height:
        return int(explicit_width), int(explicit_height)

    if os.environ.get("HTB_USE_EXTERNAL_MONITOR") == "1":
        return BASE_WIDTH, BASE_HEIGHT

    margin_x = int(os.environ.get("HTB_WINDOW_MARGIN_X", "80"))
    margin_y = int(os.environ.get("HTB_WINDOW_MARGIN_Y", "120"))
    max_width = max(360, display_width - margin_x)
    max_height = max(480, display_height - margin_y)
    return fit_size(max_width, max_height)


def draw_base_surface(target, source):
    target_width, target_height = target.get_size()
    scale = min(target_width / BASE_WIDTH, target_height / BASE_HEIGHT)
    scaled_width = max(1, int(BASE_WIDTH * scale))
    scaled_height = max(1, int(BASE_HEIGHT * scale))
    x = (target_width - scaled_width) // 2
    y = (target_height - scaled_height) // 2

    target.fill((0, 0, 0))
    scaled_surface = pygame.transform.smoothscale(source, (scaled_width, scaled_height))
    target.blit(scaled_surface, (x, y))


def window_to_base(position):
    """Convert a resizable-window mouse position into the fixed game canvas."""
    target_width, target_height = screen.get_size()
    scale = min(target_width / BASE_WIDTH, target_height / BASE_HEIGHT)
    scaled_width = BASE_WIDTH * scale
    scaled_height = BASE_HEIGHT * scale
    offset_x = (target_width - scaled_width) / 2
    offset_y = (target_height - scaled_height) / 2
    x = (position[0] - offset_x) / scale
    y = (position[1] - offset_y) / scale
    if 0 <= x < BASE_WIDTH and 0 <= y < BASE_HEIGHT:
        return int(x), int(y)
    return None


def base_to_preview_normalized(position, clamp=False):
    """Convert a fixed-canvas mouse position into the mirrored preview space."""
    if position is None:
        return None
    if not clamp and not CAMERA_PREVIEW_RECT.collidepoint(position):
        return None
    relative_x = (position[0] - CAMERA_PREVIEW_RECT.left) / CAMERA_PREVIEW_RECT.width
    relative_y = (position[1] - CAMERA_PREVIEW_RECT.top) / CAMERA_PREVIEW_RECT.height
    return (
        max(0.0, min(1.0, relative_x)),
        max(0.0, min(1.0, relative_y)),
    )


def game_font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc" if bold else "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for candidate in candidates:
        try:
            return pygame.font.Font(candidate, size)
        except Exception:
            continue
    return pygame.font.Font(None, size)


def draw_translucent_panel(surface, rect, fill=PANEL, border=CYAN, radius=24, border_width=2):
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(panel, fill, panel.get_rect(), border_radius=radius)
    pygame.draw.rect(panel, (*border, 210), panel.get_rect(), border_width, border_radius=radius)
    surface.blit(panel, rect.topleft)


def load_game_background():
    try:
        image = pygame.image.load(str(BACKGROUND_IMAGE)).convert()
        return pygame.transform.smoothscale(image, (BASE_WIDTH, BASE_HEIGHT))
    except Exception as exc:
        print(f"背景画像を読み込めません。グラデーションで続行します: {exc}")
        surface = pygame.Surface((BASE_WIDTH, BASE_HEIGHT))
        for y in range(BASE_HEIGHT):
            ratio = y / BASE_HEIGHT
            color = (int(7 + 9 * ratio), int(18 + 24 * ratio), int(48 + 38 * ratio))
            pygame.draw.line(surface, color, (0, y), (BASE_WIDTH, y))
        return surface



# 初期設定
pygame.init()

display_info = pygame.display.Info()
window_width, window_height = initial_window_size(display_info.current_w, display_info.current_h)

screen = pygame.display.set_mode((window_width, window_height), pygame.RESIZABLE)
pygame.display.set_caption("人間タワーバトル 2026")

clock = pygame.time.Clock()
background_surface = load_game_background()

# macOSでKEYDOWNイベントが取りこぼされた場合に備え、操作キーの状態も監視する。
CONTROL_KEYS = (
    pygame.K_SPACE,
    pygame.K_RETURN,
    pygame.K_KP_ENTER,
    pygame.K_d,
    pygame.K_DELETE,
    pygame.K_BACKSPACE,
    pygame.K_1,
    pygame.K_2,
    pygame.K_3,
    pygame.K_KP1,
    pygame.K_KP2,
    pygame.K_KP3,
)
previous_control_key_state = {key: False for key in CONTROL_KEYS}



# Pymunkスペース作成 & 台の座標も取得（BASE_WIDTH, BASE_HEIGHTで固定）
space, platform_rect = create_space(BASE_WIDTH, BASE_HEIGHT)

def load_sam2_predictor():
    """Load SAM2 if available; fall back to simple masks for local testing."""
    if os.environ.get("HTB_DEMO_MODE") == "1":
        print("HTB_DEMO_MODE=1 のため、SAM2を読み込まず簡易マスクで動作します。")
        return None

    if not SAM2_CONFIG.exists():
        print(f"SAM2 config が見つかりません: {SAM2_CONFIG}")
        return None
    if not SAM2_CHECKPOINT.exists():
        print(f"SAM2 checkpoint が見つかりません: {SAM2_CHECKPOINT}")
        return None
    if not checkpoint_looks_complete(SAM2_CHECKPOINT):
        print(f"SAM2 checkpoint が壊れている可能性があります。再取得してください: {SAM2_CHECKPOINT}")
        return None

    try:
        ensure_sam2_import_path()
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor

        device = os.environ.get("HTB_SAM2_DEVICE", "cpu")
        model = build_sam2(str(SAM2_CONFIG), str(SAM2_CHECKPOINT), device=device)
        print(f"SAM2を読み込みました: device={device}")
        return SAM2ImagePredictor(model)
    except Exception as exc:
        print(f"SAM2の読み込みに失敗しました。簡易マスクで続行します: {exc}")
        return None


def checkpoint_looks_complete(path):
    try:
        size = path.stat().st_size
        if size < 100_000_000:
            return False
        with path.open("rb") as f:
            f.seek(max(0, size - 65557))
            tail = f.read()
        return b"PK\x05\x06" in tail
    except OSError:
        return False


# SAM2 セグメンテーションモデルの読み込み
predictor = load_sam2_predictor()

# ゲーム状態の初期化
animal_ingame = []
current_animal = None
number = 0
running = True
game_state = "start"  # "start", "playing", "game_over"
debug_exit_after_frames = int(os.environ.get("HTB_EXIT_AFTER_FRAMES", "0"))
debug_frame_count = 0
debug_screenshot_path = os.environ.get("HTB_SCREENSHOT_PATH", "").strip()
allow_fallback_capture = os.environ.get("HTB_DEMO_MODE") == "1" or os.environ.get("HTB_ALLOW_FAKE_CAPTURE") == "1"
status_message = ""
status_frames = 0

# ランキングマネージャーの初期化
ranking_manager = RankingManager()

# 画面の初期化
start_screen = StartScreen(window_width, window_height)
game_over_screen = None

# カメラプレビュー用の変数
camera_cap = None
preview_surface = None
preview_person_box = None
preview_person_detected = False
preview_detection_counter = 24
manual_prompt_point = None
manual_prompt_box = None
manual_drag_start = None
manual_drag_current = None



# プリセット位置の矢印を描画する関数
def draw_preset_arrows(surface, platform_rect):
    """Drop-position controls rendered directly above the platform."""
    positions = [
        (platform_rect["x1"] + 200, "1", "左"),
        ((platform_rect["x1"] + platform_rect["x2"]) // 2, "2", "中央"),
        (platform_rect["x2"] - 200, "3", "右"),
    ]
    number_font = game_font(52, bold=True)
    label_font = game_font(28, bold=True)
    arrow_y = platform_rect["y"] - 260

    for x, key_num, label in positions:
        card = pygame.Rect(x - 76, arrow_y - 84, 152, 108)
        draw_translucent_panel(surface, card, fill=(18, 60, 110, 232), border=GOLD, radius=24, border_width=3)
        key_surface = number_font.render(key_num, True, WHITE)
        surface.blit(key_surface, key_surface.get_rect(center=(x, arrow_y - 45)))
        label_surface = label_font.render(label, True, GOLD)
        surface.blit(label_surface, label_surface.get_rect(center=(x, arrow_y - 2)))

        arrow_points = [
            (x, arrow_y + 36),
            (x - 28, arrow_y + 74),
            (x + 28, arrow_y + 74),
        ]
        pygame.draw.polygon(surface, GOLD, arrow_points)
        pygame.draw.polygon(surface, WHITE, arrow_points, 3)


def draw_game_hud(
    surface,
    ranking_manager,
    score,
    camera_ready,
    person_ready,
    waiting_piece,
    prompt_mode=None,
):
    """Draw score, ranking, camera readiness, and the primary action."""
    daily_rankings = ranking_manager.get_daily_rankings()
    best_score = daily_rankings[0]["score"] if daily_rankings else 0

    hud_rect = pygame.Rect(60, 65, 720, 250)
    draw_translucent_panel(surface, hud_rect, fill=PANEL, border=CYAN, radius=30, border_width=3)

    eyebrow_font = game_font(28, bold=True)
    score_font = game_font(104, bold=True)
    value_font = game_font(44, bold=True)
    small_font = game_font(30, bold=True)

    eyebrow = eyebrow_font.render("HUMAN TOWER BATTLE", True, CYAN)
    surface.blit(eyebrow, (hud_rect.x + 30, hud_rect.y + 22))
    score_label = small_font.render("積み上げ", True, MUTED)
    surface.blit(score_label, (hud_rect.x + 32, hud_rect.y + 78))
    score_text = score_font.render(str(score), True, WHITE)
    surface.blit(score_text, (hud_rect.x + 28, hud_rect.y + 102))
    people_text = value_font.render("人", True, GOLD)
    surface.blit(people_text, (hud_rect.x + 150, hud_rect.y + 145))

    divider_x = hud_rect.x + 250
    pygame.draw.line(surface, (70, 116, 166), (divider_x, hud_rect.y + 78), (divider_x, hud_rect.bottom - 26), 2)
    best_label = small_font.render("今日のベスト", True, MUTED)
    surface.blit(best_label, (divider_x + 34, hud_rect.y + 86))
    best_text = value_font.render(f"{best_score} 人", True, GOLD)
    surface.blit(best_text, (divider_x + 34, hud_rect.y + 132))

    action_color = CYAN
    if waiting_piece:
        title = "落とす位置を選ぶ"
        detail = "1 左　　2 中央　　3 右　｜　D 撮り直し"
        action_color = GOLD
    elif not camera_ready:
        title = "カメラを確認してください"
        detail = "接続・権限・カメラ番号を確認"
        action_color = CORAL
    elif prompt_mode:
        title = "ENTER で指定した人物を撮影"
        detail = "選び直す: 再クリック・ドラッグ　｜　解除: 右クリック"
        action_color = GREEN
    elif person_ready:
        title = "切り抜く人物をクリック"
        detail = "1回クリックで選択　｜　ドラッグで全身を囲む"
        action_color = GOLD
    else:
        title = "切り抜く人物を選んでください"
        detail = "胴体をクリック　｜　複数人なら全身をドラッグで囲む"
        action_color = GOLD

    draw_translucent_panel(surface, ACTION_PANEL_RECT, fill=(10, 34, 74, 230), border=action_color, radius=30, border_width=4)
    action_font = game_font(42, bold=True)
    action_detail_font = game_font(27, bold=True)
    title_surface = action_font.render(title, True, WHITE)
    surface.blit(title_surface, (ACTION_PANEL_RECT.x + 34, ACTION_PANEL_RECT.y + 30))
    detail_surface = action_detail_font.render(detail, True, action_color)
    surface.blit(detail_surface, (ACTION_PANEL_RECT.x + 34, ACTION_PANEL_RECT.y + 98))


def draw_camera_card(
    surface,
    preview_surface,
    person_ready,
    camera_ready,
    prompt_mode=None,
):
    outer = CAMERA_PREVIEW_RECT.inflate(28, 100)
    outer.y -= 66
    selection_ready = prompt_mode is not None
    draw_translucent_panel(
        surface,
        outer,
        fill=PANEL,
        border=GREEN if person_ready or selection_ready else CYAN,
        radius=28,
        border_width=3,
    )
    label_font = game_font(29, bold=True)
    status_font = game_font(23, bold=True)
    title = label_font.render("LIVE CAMERA", True, WHITE)
    surface.blit(title, (outer.x + 22, outer.y + 15))

    if prompt_mode == "box":
        status_text, status_color = "範囲指定済み", GREEN
    elif prompt_mode == "point":
        status_text, status_color = "クリック指定済み", GREEN
    elif person_ready:
        status_text, status_color = "人物を検出", GREEN
    elif camera_ready:
        status_text, status_color = "全身を映してください", GOLD
    else:
        status_text, status_color = "未接続", CORAL
    pygame.draw.circle(surface, status_color, (outer.right - 202, outer.y + 32), 9)
    status = status_font.render(status_text, True, status_color)
    surface.blit(status, (outer.right - 182, outer.y + 17))

    if preview_surface is not None:
        surface.blit(preview_surface, CAMERA_PREVIEW_RECT.topleft)
    else:
        pygame.draw.rect(surface, (7, 18, 43), CAMERA_PREVIEW_RECT, border_radius=12)
        missing = status_font.render("カメラ映像がありません", True, MUTED)
        surface.blit(missing, missing.get_rect(center=CAMERA_PREVIEW_RECT.center))
    pygame.draw.rect(surface, status_color, CAMERA_PREVIEW_RECT, 4, border_radius=12)


def manual_prompt_mode():
    if manual_prompt_box is not None:
        return "box"
    if manual_prompt_point is not None:
        return "point"
    return None


def draw_manual_prompt(frame):
    """Draw the operator's point/box selection on the mirrored preview."""
    height, width = frame.shape[:2]

    def pixel(point):
        return (
            int(round(point[0] * max(0, width - 1))),
            int(round(point[1] * max(0, height - 1))),
        )

    display_box = manual_prompt_box
    if manual_drag_start is not None and manual_drag_current is not None:
        display_box = (
            min(manual_drag_start[0], manual_drag_current[0]),
            min(manual_drag_start[1], manual_drag_current[1]),
            max(manual_drag_start[0], manual_drag_current[0]),
            max(manual_drag_start[1], manual_drag_current[1]),
        )

    if display_box is not None:
        first = pixel((display_box[0], display_box[1]))
        second = pixel((display_box[2], display_box[3]))
        cv2.rectangle(frame, first, second, (80, 230, 255), 5)
        cv2.rectangle(frame, first, second, (30, 70, 90), 1)
    elif manual_prompt_point is not None:
        selected = pixel(manual_prompt_point)
        cv2.circle(frame, selected, 15, (80, 230, 255), 5)
        cv2.drawMarker(frame, selected, (20, 60, 90), cv2.MARKER_CROSS, 28, 3)


def should_exit_for_debug():
    global debug_frame_count
    if debug_exit_after_frames <= 0:
        return False
    debug_frame_count += 1
    return debug_frame_count >= debug_exit_after_frames


def set_status_message(message, frames=180):
    global status_message, status_frames
    status_message = message
    status_frames = frames


def draw_status_message(surface):
    global status_frames
    if not status_message or status_frames <= 0:
        return

    font_size = 34
    font = game_font(font_size, bold=True)
    text = font.render(status_message, True, WHITE)
    while text.get_width() > BASE_WIDTH - 120 and font_size > 22:
        font_size -= 2
        font = game_font(font_size, bold=True)
        text = font.render(status_message, True, WHITE)
    rect = text.get_rect(center=(BASE_WIDTH // 2, 620))
    bg_rect = rect.inflate(54, 34)
    pygame.draw.rect(surface, (151, 39, 63), bg_rect, border_radius=20)
    pygame.draw.rect(surface, CORAL, bg_rect, 4, border_radius=20)
    surface.blit(text, rect)
    status_frames -= 1


def show_capture_in_progress():
    """SAM2の同期処理中も、Enter入力を受け取ったことを画面に示す。"""
    overlay = screen.copy()
    shade = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
    shade.fill((0, 0, 0, 110))
    overlay.blit(shade, (0, 0))

    try:
        progress_font = pygame.font.Font(
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            max(24, min(screen.get_width(), screen.get_height()) // 18),
        )
    except Exception:
        progress_font = pygame.font.Font(
            None,
            max(24, min(screen.get_width(), screen.get_height()) // 18),
        )

    message = progress_font.render("撮影・人物切り抜き中…", True, (255, 255, 255))
    message_rect = message.get_rect(center=screen.get_rect().center)
    background_rect = message_rect.inflate(56, 36)
    pygame.draw.rect(overlay, (25, 55, 90), background_rect, border_radius=16)
    pygame.draw.rect(overlay, (40, 190, 210), background_rect, 4, border_radius=16)
    overlay.blit(message, message_rect)
    screen.blit(overlay, (0, 0))
    pygame.display.flip()
    pygame.event.pump()

# カメラプレビューを初期化
def init_camera_preview():
    global camera_cap
    cameras_to_try = parse_camera_indices()

    for camera_id in cameras_to_try:
        print(f"プレビュー用カメラ{camera_id}を試しています...")
        camera_cap, first_frame = open_camera(camera_id, width=640, height=480, fps=30)
        if camera_cap is not None:
            print(f"プレビュー用カメラ{camera_id}が使用可能です")
            if first_frame is not None:
                print(f"初回フレーム取得OK: {first_frame.shape[1]}x{first_frame.shape[0]}")
            return True
        camera_cap = None

    print("プレビュー用カメラが見つかりませんでした")
    print_camera_help()
    return False

# カメラプレビューを初期化
init_camera_preview()

# メインループ
while running:
    dt = 1 / 120.0  # 物理演算の精度を上げるためにタイムステップを小さく

    # KEYDOWNとキー状態の立ち上がりを併用する。通常のKEYDOWNが来ている場合は
    # 合成イベントを追加しないため、1回の押下が二重処理されることはない。
    events = pygame.event.get()
    pressed_keys = pygame.key.get_pressed()
    keydown_keys = {
        event.key
        for event in events
        if event.type == pygame.KEYDOWN and hasattr(event, "key")
    }
    for control_key in CONTROL_KEYS:
        is_pressed = bool(pressed_keys[control_key])
        if (
            is_pressed
            and not previous_control_key_state[control_key]
            and control_key not in keydown_keys
        ):
            events.append(pygame.event.Event(pygame.KEYDOWN, key=control_key))
        previous_control_key_state[control_key] = is_pressed

    for event in events:
        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.VIDEORESIZE:
            window_width, window_height = event.w, event.h
            screen = pygame.display.set_mode((window_width, window_height), pygame.RESIZABLE)

            # 物理座標はBASEサイズ固定なので、ウィンドウサイズ変更では重力を変えない
            gravity_y = 600
            space.gravity = (0, gravity_y)

            # 画面オブジェクトを新しいサイズで再作成
            start_screen = StartScreen(window_width, window_height)
            if game_over_screen:
                game_over_screen = GameOverScreen(window_width, window_height, number, ranking_manager)

            print(f"ウィンドウサイズ変更: 重力加速度: (0, {gravity_y:.1f}) - ウィンドウサイズ: {window_width}x{window_height}")

        # ゲーム状態に応じてイベント処理
        if game_state == "start":
            if start_screen.handle_event(event):
                game_state = "playing"
                print("ゲーム開始！")
        elif game_state == "game_over":
            if game_over_screen:
                result = game_over_screen.handle_event(event)
                if result == "restart":
                    # ゲームをリセット
                    # 古い動物の物理オブジェクトを削除
                    for animal in animal_ingame:
                        animal.remove_from_space()
                    animal_ingame = []
                    current_animal = None
                    number = 0
                    manual_prompt_point = None
                    manual_prompt_box = None
                    manual_drag_start = None
                    manual_drag_current = None
                    game_over_screen = None  # ゲームオーバー画面をクリア
                    game_state = "playing"
                    print("ゲームをリスタートしました")
                elif result == "quit":
                    running = False
        elif game_state == "playing":
            if event.type == pygame.MOUSEBUTTONDOWN:
                base_position = window_to_base(event.pos)
                preview_position = base_to_preview_normalized(base_position)
                if event.button == 3 and preview_position is not None:
                    manual_prompt_point = None
                    manual_prompt_box = None
                    manual_drag_start = None
                    manual_drag_current = None
                    set_status_message("人物の指定を解除しました", frames=90)
                elif event.button == 1 and preview_position is not None:
                    if current_animal and not current_animal.falling:
                        set_status_message("先に待機中の人物を落とすか、Dで破棄してください")
                    elif not camera_cap or not camera_cap.isOpened():
                        set_status_message("カメラが接続されていません")
                    else:
                        manual_drag_start = preview_position
                        manual_drag_current = preview_position
                elif (
                    event.button == 1
                    and base_position
                    and ACTION_PANEL_RECT.collidepoint(base_position)
                ):
                    events.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
            elif event.type == pygame.MOUSEMOTION and manual_drag_start is not None:
                base_position = window_to_base(event.pos)
                preview_position = base_to_preview_normalized(base_position, clamp=True)
                if preview_position is not None:
                    manual_drag_current = preview_position
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if manual_drag_start is not None:
                    base_position = window_to_base(event.pos)
                    preview_position = base_to_preview_normalized(base_position, clamp=True)
                    end_position = preview_position or manual_drag_current or manual_drag_start
                    width_pixels = abs(end_position[0] - manual_drag_start[0]) * CAMERA_PREVIEW_RECT.width
                    height_pixels = abs(end_position[1] - manual_drag_start[1]) * CAMERA_PREVIEW_RECT.height
                    if width_pixels >= 18 and height_pixels >= 18:
                        manual_prompt_box = (
                            min(manual_drag_start[0], end_position[0]),
                            min(manual_drag_start[1], end_position[1]),
                            max(manual_drag_start[0], end_position[0]),
                            max(manual_drag_start[1], end_position[1]),
                        )
                        manual_prompt_point = None
                        set_status_message("人物を枠で指定しました。Enterで撮影します", frames=120)
                    else:
                        manual_prompt_point = end_position
                        manual_prompt_box = None
                        set_status_message("人物をクリックで指定しました。Enterで撮影します", frames=120)
                    manual_drag_start = None
                    manual_drag_current = None
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    print(f"撮影キーを受信しました: {pygame.key.name(event.key)}")
                    if current_animal and not current_animal.falling:
                        set_status_message("先に 1・2・3 で落とすか、Dで破棄してください")
                        continue

                    # Enterキーで撮影して動物生成（既存のカメラから直接撮影）
                    # 動物が落ちていない時は撮影できない
                    show_capture_in_progress()
                    rgb, mask = capture_from_existing_camera(
                        camera_cap,
                        predictor,
                        allow_fallback=allow_fallback_capture,
                        normalized_prompt_point=manual_prompt_point,
                        normalized_prompt_box=manual_prompt_box,
                        prompt_is_mirrored=True,
                    )
                    if rgb is None or mask is None:
                        set_status_message(
                            get_last_capture_error()
                            or "人物を切り抜けません。カメラ映像と立ち位置を確認してください"
                        )
                        continue

                    # 現在の動物の最大高さを取得
                    max_y = 50  # デフォルトの高さ
                    if animal_ingame:
                        max_y = min([animal.body.position.y for animal in animal_ingame])
                        # 最大高さから800ピクセル上に配置（より上に移動）
                        spawn_y = max_y - 800
                    else:
                        # 最初の動物は台の上に配置（より上に移動）
                        spawn_y = platform_rect["y"] - 800

                    try:
                        current_animal = Animal(
                            space,
                            BASE_WIDTH // 2,
                            spawn_y,
                            rgb=rgb,
                            mask=mask,
                            scale=0.6,
                            target_mask_area=PIECE_TARGET_MASK_AREA,
                        )
                    except Exception as exc:
                        print(f"動物の生成に失敗しました: {exc}")
                        current_animal = None
                        continue

                    print("A")
                    animal_ingame.append(current_animal)
                    manual_prompt_point = None
                    manual_prompt_box = None
                    manual_drag_start = None
                    manual_drag_current = None
                    set_status_message("撮影できました。1・2・3で落とす位置を選んでください", frames=150)

                elif (
                    event.key in (pygame.K_d, pygame.K_DELETE, pygame.K_BACKSPACE)
                    and current_animal
                    and not current_animal.falling
                ):
                    # 落とす前の人物はカウントせずに破棄する。
                    current_animal.remove_from_space()
                    animal_ingame.remove(current_animal)
                    current_animal = None
                    print("現在の動物を破棄しました")
                elif event.key in (pygame.K_1, pygame.K_KP1) and current_animal and not current_animal.falling:
                    # 1キーで左端に配置
                    current_animal.body.position = (platform_rect["x1"] + 200, current_animal.body.position.y)
                    current_animal.start_fall()
                    number += 1
                    print("左端に配置して落下開始")
                elif event.key in (pygame.K_2, pygame.K_KP2) and current_animal and not current_animal.falling:
                    # 2キーで中央に配置
                    center_x = (platform_rect["x1"] + platform_rect["x2"]) // 2
                    current_animal.body.position = (center_x, current_animal.body.position.y)
                    current_animal.start_fall()
                    number += 1
                    print("中央に配置して落下開始")
                elif event.key in (pygame.K_3, pygame.K_KP3) and current_animal and not current_animal.falling:
                    # 3キーで右端に配置
                    current_animal.body.position = (platform_rect["x2"] - 200, current_animal.body.position.y)
                    current_animal.start_fall()
                    number += 1
                    print("右端に配置して落下開始")

    # ゲーム状態に応じて画面を描画
    if game_state == "start":
        start_screen.draw(screen)
        pygame.display.flip()
        clock.tick(60)
        if should_exit_for_debug():
            running = False
        continue
    elif game_state == "game_over":
        if game_over_screen:
            game_over_screen.draw(screen)
            pygame.display.flip()
            clock.tick(60)
            if should_exit_for_debug():
                running = False
            continue
    elif game_state == "playing":
        # 仮描画サーフェス（BASEサイズ）
        base_surface = pygame.Surface((BASE_WIDTH, BASE_HEIGHT))

    # 背景は起動時に一度だけ読み込み、フレームごとのディスクアクセスを避ける。
    base_surface.blit(background_surface, (0, 0))

    # カメラプレビューを更新・表示
    camera_ready = bool(camera_cap and camera_cap.isOpened())
    if camera_ready:
        ret, frame = camera_cap.read()
        if ret:
            preview_width, preview_height = CAMERA_PREVIEW_RECT.size
            frame_mirrored = cv2.flip(frame, 1)
            frame_resized = cv2.resize(frame_mirrored, (preview_width, preview_height))

            preview_detection_counter += 1
            if preview_detection_counter >= 24:
                preview_detection_counter = 0
                preview_person_box = detect_person_box(frame_resized)
                preview_person_detected = preview_person_box is not None

            guide_x1 = int(preview_width * 0.05)
            guide_y1 = int(preview_height * 0.03)
            guide_x2 = int(preview_width * 0.95)
            guide_y2 = int(preview_height * 0.98)
            if manual_prompt_mode() is not None or manual_drag_start is not None:
                draw_manual_prompt(frame_resized)
            elif preview_person_box is not None:
                x1, y1, x2, y2 = [int(value) for value in preview_person_box]
                cv2.rectangle(frame_resized, (x1, y1), (x2, y2), (80, 230, 130), 4)
            else:
                guide_color = (224, 210, 44)
                cv2.rectangle(frame_resized, (guide_x1, guide_y1), (guide_x2, guide_y2), guide_color, 3)
                corner = 34
                for x, y, dx, dy in (
                    (guide_x1, guide_y1, 1, 1),
                    (guide_x2, guide_y1, -1, 1),
                    (guide_x1, guide_y2, 1, -1),
                    (guide_x2, guide_y2, -1, -1),
                ):
                    cv2.line(frame_resized, (x, y), (x + corner * dx, y), (80, 230, 255), 7)
                    cv2.line(frame_resized, (x, y), (x, y + corner * dy), (80, 230, 255), 7)

            frame_rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
            preview_surface = pygame.surfarray.make_surface(frame_rgb.swapaxes(0, 1))
        else:
            preview_surface = None
            preview_person_box = None
            preview_person_detected = False
    else:
        preview_surface = None
        preview_person_box = None
        preview_person_detected = False

    current_prompt_mode = manual_prompt_mode()
    draw_camera_card(
        base_surface,
        preview_surface,
        preview_person_detected,
        camera_ready,
        current_prompt_mode,
    )

    # 落下エリアを控えめに表示
    danger_surface = pygame.Surface((BASE_WIDTH, 90), pygame.SRCALPHA)
    danger_surface.fill((255, 68, 92, 32))
    base_surface.blit(danger_surface, (0, BASE_HEIGHT - 90))
    pygame.draw.line(base_surface, CORAL, (0, BASE_HEIGHT - 10), (BASE_WIDTH, BASE_HEIGHT - 10), 5)

    # 台をステージの発光と一体化して描画
    platform_width = platform_rect["x2"] - platform_rect["x1"]
    shadow_rect = pygame.Rect(platform_rect["x1"] - 30, platform_rect["y"] - 8, platform_width + 60, 58)
    pygame.draw.rect(base_surface, (3, 15, 39), shadow_rect, border_radius=24)
    platform_draw_rect = pygame.Rect(platform_rect["x1"], platform_rect["y"] - 30, platform_width, 54)
    pygame.draw.rect(base_surface, GOLD, platform_draw_rect, border_radius=22)
    pygame.draw.rect(base_surface, WHITE, platform_draw_rect, 4, border_radius=22)
    highlight_rect = pygame.Rect(platform_rect["x1"] + 26, platform_rect["y"] - 22, platform_width - 52, 10)
    pygame.draw.rect(base_surface, (255, 236, 164), highlight_rect, border_radius=5)

    # 動物を描画（base_surface に対して）
    for animal in animal_ingame:
        animal.draw(base_surface)

    # プリセット位置の矢印を描画（現在の動物が存在し、落下していない場合のみ）
    if current_animal and not current_animal.falling:
        draw_preset_arrows(base_surface, platform_rect)

    # HUD・操作ガイド
    draw_game_hud(
        base_surface,
        ranking_manager,
        number,
        camera_ready,
        preview_person_detected,
        bool(current_animal and not current_animal.falling),
        current_prompt_mode,
    )

    # 状態メッセージ表示
    draw_status_message(base_surface)

    # base_surface を縦横比を維持して画面に描画
    draw_base_surface(screen, base_surface)
    pygame.display.flip()

    # 物理演算の更新（滑らかな動きのため複数回ステップ実行）
    for _ in range(2):  # 物理演算を2回実行して滑らかさを向上
        space.step(dt)
    for animal in animal_ingame:
        animal.stabilize_motion()

    # ゲームオーバー判定
    for animal in animal_ingame:
        x, y = animal.body.position
        # 床に落ちた場合（動物の下部が床に触れた場合）
        animal_bottom = y + 50  # 動物の下部位置（概算）
        if animal_bottom > BASE_HEIGHT - 10:  # 床の位置（BASE_HEIGHT - 10）
            print("GAME OVER! 床に落ちました！")
            # 床まで落ちた最後の1体は、積み上げ成功数から除外する。
            number = max(0, number - 1)
            game_state = "game_over"
            game_over_screen = GameOverScreen(window_width, window_height, number, ranking_manager)
            break

    # フレームレートを安定化（滑らかな動きのため）
    clock.tick(120)  # フレームレートを120FPSに上げて滑らかさを向上
    if should_exit_for_debug():
        running = False
info = pygame.display.Info()

# カメラをリリース
if camera_cap:
    camera_cap.release()

if debug_screenshot_path:
    screenshot_dir = os.path.dirname(debug_screenshot_path)
    if screenshot_dir:
        os.makedirs(screenshot_dir, exist_ok=True)
    pygame.image.save(screen, debug_screenshot_path)
    print(f"スクリーンショットを保存しました: {debug_screenshot_path}")

pygame.quit()
