import os
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from camera_utils import open_camera, parse_camera_indices, print_camera_help


LAST_CAPTURE_ERROR = ""


def set_capture_error(message):
    global LAST_CAPTURE_ERROR
    LAST_CAPTURE_ERROR = message
    if message:
        print(message)


def get_last_capture_error():
    return LAST_CAPTURE_ERROR

# OpenCV画像（BGR）をPillow画像（RGB）に変換
def put_japanese_text(img, text, position, font_path="C:/Windows/Fonts/msgothic.ttc", font_size=32):
    # OpenCV (BGR) -> PIL (RGB)
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

    # 日本語フォント指定
    font_candidates = [
        font_path,
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/Arial Unicode MS.ttf",
    ]
    font = None
    for candidate in font_candidates:
        try:
            font = ImageFont.truetype(candidate, font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(img_pil)
    draw.text(position, text, font=font, fill=(255,0, 0))

    # PIL (RGB) -> OpenCV (BGR)
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def create_fallback_capture(frame=None, width=640, height=480):
    """Create a playable placeholder when a camera or SAM2 is unavailable."""
    if frame is None:
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = (245, 245, 245)
        cv2.circle(frame, (width // 2, height // 3), width // 10, (80, 140, 240), -1)
        cv2.rectangle(
            frame,
            (width // 2 - width // 9, height // 3 + width // 10),
            (width // 2 + width // 9, height // 3 + width // 10 + height // 4),
            (80, 140, 240),
            -1,
        )
    else:
        frame = frame.copy()
        height, width = frame.shape[:2]

    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.circle(mask, (width // 2, height // 3), max(12, width // 10), 255, -1)
    cv2.ellipse(
        mask,
        (width // 2, int(height * 0.58)),
        (max(18, width // 7), max(28, height // 4)),
        0,
        0,
        360,
        255,
        -1,
    )
    return frame, mask


def detect_person_box(frame):
    # OpenCV 5 の一部ビルドでは従来の HOG 人物検出器が含まれない。
    # その場合も SAM2 のポイントプロンプトだけで切り抜きを続行する。
    if not hasattr(cv2, "HOGDescriptor"):
        print("OpenCVにHOG人物検出器がないため、ポイント指定でSAM2を実行します。")
        return None

    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    boxes, weights = hog.detectMultiScale(
        frame,
        winStride=(8, 8),
        padding=(16, 16),
        scale=1.05,
    )
    if len(boxes) == 0:
        return None

    height, width = frame.shape[:2]
    detections = list(zip(boxes, weights))

    # 位置に関係なく、十分な大きさの人物を小さい背景人物より優先する。
    preferred = []
    for box, weight in detections:
        x, y, w, h = box
        area_ratio = w * h / max(1, width * height)
        height_ratio = h / height
        if area_ratio >= 0.035 and height_ratio >= 0.28:
            preferred.append((box, weight))
    candidates = preferred or detections

    def score_box(item):
        box, weight = item
        x, y, w, h = box
        confidence = float(np.ravel(weight)[0])
        center_x_ratio = (x + w / 2) / width
        center_y_ratio = (y + h / 2) / height
        area_ratio = w * h / max(1, width * height)
        height_ratio = h / height

        confidence_score = 1.0 - np.exp(-max(0.0, confidence))
        horizontal_score = max(0.0, 1.0 - abs(center_x_ratio - 0.50) / 0.50)
        # 画面中央より少し下（約62%）を人物の主な立ち位置として扱う。
        vertical_score = max(0.0, 1.0 - abs(center_y_ratio - 0.62) / 0.62)
        area_score = min(1.0, area_ratio / 0.22)
        height_score = min(1.0, height_ratio / 0.75)
        side_edge_penalty = 0.25 if x <= 1 or x + w >= width - 2 else 0.0
        return (
            confidence_score * 0.12
            + area_score * 0.38
            + height_score * 0.27
            + horizontal_score * 0.10
            + vertical_score * 0.12
            - side_edge_penalty
        )

    x, y, w, h = max(candidates, key=score_box)[0]
    pad_x = int(w * 0.12)
    pad_y = int(h * 0.08)
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(width - 1, x + w + pad_x)
    y2 = min(height - 1, y + h + pad_y)
    return np.array([x1, y1, x2, y2], dtype=np.float32)


def person_prompt_points(
    width,
    height,
    box=None,
    focus="standard",
    center_x_ratio=0.50,
):
    if box is not None:
        x1, y1, x2, y2 = [float(value) for value in box]
        box_width = max(1.0, x2 - x1)
        box_height = max(1.0, y2 - y1)
        center_x = x1 + box_width * 0.5
        positive = [
            (center_x, y1 + box_height * 0.22),
            (center_x, y1 + box_height * 0.48),
            (center_x, y1 + box_height * 0.74),
        ]
    elif focus == "lower":
        # HOGが人物を見つけられない場合でも、中央下側に立つ人物の
        # 胸・腰・脚へポジティブ点が入るようにする。
        positive = [
            (width * center_x_ratio, height * 0.48),
            (width * center_x_ratio, height * 0.66),
            (width * center_x_ratio, height * 0.82),
        ]
    else:
        positive = [
            (width * center_x_ratio, height * 0.28),
            (width * center_x_ratio, height * 0.50),
            (width * center_x_ratio, height * 0.72),
        ]
    negative = [
        (width * 0.08, height * 0.08),
        (width * 0.92, height * 0.08),
        (width * 0.08, height * 0.92),
        (width * 0.92, height * 0.92),
    ]
    points = np.array(positive + negative, dtype=np.float32)
    labels = np.array([1] * len(positive) + [0] * len(negative), dtype=np.int32)
    return points, labels


def person_prompt_variants(width, height, box=None):
    if box is not None:
        return [person_prompt_points(width, height, box)]
    # 下側を先に、左・中央・右の順で試す。従来の高さも残す。
    horizontal_positions = (0.22, 0.50, 0.78)
    return [
        person_prompt_points(
            width,
            height,
            focus=focus,
            center_x_ratio=center_x_ratio,
        )
        for focus in ("lower", "standard")
        for center_x_ratio in horizontal_positions
    ]


def manual_point_prompt(width, height, point):
    """Build a SAM2 point prompt that keeps the clicked subject selected."""
    point_x = float(np.clip(point[0], 0, max(0, width - 1)))
    point_y = float(np.clip(point[1], 0, max(0, height - 1)))
    negative = [
        (width * 0.03, height * 0.03),
        (width * 0.97, height * 0.03),
        (width * 0.03, height * 0.97),
        (width * 0.97, height * 0.97),
    ]
    points = np.array([(point_x, point_y)] + negative, dtype=np.float32)
    labels = np.array([1, 0, 0, 0, 0], dtype=np.int32)
    return points, labels


def normalized_prompt_to_frame(
    width,
    height,
    point=None,
    box=None,
    mirrored=False,
):
    """Map a normalized preview selection onto the captured camera frame."""

    def frame_point(normalized_point):
        normalized_x = float(np.clip(normalized_point[0], 0.0, 1.0))
        normalized_y = float(np.clip(normalized_point[1], 0.0, 1.0))
        if mirrored:
            normalized_x = 1.0 - normalized_x
        return np.array(
            [normalized_x * max(0, width - 1), normalized_y * max(0, height - 1)],
            dtype=np.float32,
        )

    mapped_point = frame_point(point) if point is not None else None
    mapped_box = None
    if box is not None:
        first = frame_point((box[0], box[1]))
        second = frame_point((box[2], box[3]))
        mapped_box = np.array(
            [
                min(first[0], second[0]),
                min(first[1], second[1]),
                max(first[0], second[0]),
                max(first[1], second[1]),
            ],
            dtype=np.float32,
        )
    return mapped_point, mapped_box


def mask_bounds(mask):
    rows, cols = np.nonzero(mask)
    if len(rows) == 0:
        return None
    return int(cols.min()), int(rows.min()), int(cols.max()), int(rows.max())


def clean_person_mask(mask):
    binary = (mask > 0).astype(np.uint8) * 255
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if count <= 1:
        return binary
    largest_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    cleaned = np.where(labels == largest_label, 255, 0).astype(np.uint8)
    kernel = np.ones((5, 5), np.uint8)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel, iterations=2)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cleaned


def box_iou(first, second):
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second
    intersection_width = max(0, min(ax2, bx2) - max(ax1, bx1))
    intersection_height = max(0, min(ay2, by2) - max(ay1, by1))
    intersection = intersection_width * intersection_height
    first_area = max(1, (ax2 - ax1) * (ay2 - ay1))
    second_area = max(1, (bx2 - bx1) * (by2 - by1))
    return intersection / max(1, first_area + second_area - intersection)


def person_mask_score(
    mask,
    sam_score,
    image_shape,
    person_box=None,
    prompt_point=None,
):
    height, width = image_shape[:2]
    binary = mask > 0
    ratio = np.count_nonzero(binary) / binary.size
    bounds = mask_bounds(binary)
    if bounds is None:
        return -1000.0

    x1, y1, x2, y2 = bounds
    mask_width = max(1, x2 - x1)
    mask_height = max(1, y2 - y1)
    center_x = (x1 + x2) / 2 / width
    center_y = (y1 + y2) / 2 / height
    center_distance = abs(center_x - 0.5)
    vertical_center_distance = abs(center_y - 0.62)
    verticality = min(2.0, mask_height / mask_width)
    area_preference = 1.0 - min(1.0, abs(ratio - 0.20) / 0.20)
    border_penalty = sum((x1 <= 1, y1 <= 1, x2 >= width - 2, y2 >= height - 2)) * 0.18

    score = (
        float(sam_score)
        + verticality * 0.16
        + area_preference * 0.14
        - center_distance * 0.06
        - vertical_center_distance * 0.08
        - border_penalty
    )
    if person_box is not None:
        score += box_iou(bounds, person_box) * 0.65
    if prompt_point is not None:
        point_x = int(np.clip(round(float(prompt_point[0])), 0, width - 1))
        point_y = int(np.clip(round(float(prompt_point[1])), 0, height - 1))
        if binary[point_y, point_x]:
            score += 0.80
    return score


def choose_best_mask(
    masks,
    scores,
    image_shape=None,
    person_box=None,
    prompt_point=None,
):
    if len(masks) == 0:
        return None
    if image_shape is None or scores is None or len(scores) == 0:
        return masks[0]
    ranked = [
        person_mask_score(mask, score, image_shape, person_box, prompt_point)
        for mask, score in zip(masks, scores)
    ]
    return masks[int(np.argmax(ranked))]


def choose_best_valid_mask(
    masks,
    scores,
    image_shape,
    person_box=None,
    prompt_point=None,
):
    """Choose the best valid person instead of rejecting after only one mask."""
    if len(masks) == 0:
        return None, "SAM2がマスク候補を作れませんでした", None

    if scores is None or len(scores) == 0:
        scores = np.zeros(len(masks), dtype=np.float32)

    evaluated = []
    for mask, sam_score in zip(masks, scores):
        cleaned = clean_person_mask(mask)
        score = person_mask_score(
            cleaned,
            sam_score,
            image_shape,
            person_box,
            prompt_point,
        )
        is_valid, reason = validate_person_mask(
            cleaned,
            image_shape,
            person_box,
            prompt_point,
        )
        evaluated.append((score, is_valid, reason, cleaned))

    valid = [candidate for candidate in evaluated if candidate[1]]
    if valid:
        best = max(valid, key=lambda candidate: candidate[0])
        return best[3], "", best[3]

    best_failure = max(evaluated, key=lambda candidate: candidate[0])
    return None, best_failure[2], best_failure[3]


def validate_person_mask(mask, image_shape, person_box=None, prompt_point=None):
    height, width = image_shape[:2]
    ratio = np.count_nonzero(mask) / mask.size
    if ratio < 0.015:
        return False, f"人物マスクが小さすぎます（画面比 {ratio:.1%}）"
    if ratio > 0.68:
        return False, f"背景を人物として選択しています（画面比 {ratio:.1%}）"

    bounds = mask_bounds(mask)
    if bounds is None:
        return False, "人物マスクが空です"
    x1, y1, x2, y2 = bounds
    mask_width = max(1, x2 - x1)
    mask_height = max(1, y2 - y1)
    center_x = (x1 + x2) / 2 / width

    if mask_height < height * 0.30:
        return False, "人物が小さすぎます。頭から足まで大きく映してください"
    if not 0.05 <= center_x <= 0.95:
        return False, "人物が画面外へ寄りすぎています。全身が映るようにしてください"

    if prompt_point is not None:
        point_x = int(np.clip(round(float(prompt_point[0])), 0, width - 1))
        point_y = int(np.clip(round(float(prompt_point[1])), 0, height - 1))
        radius = max(3, int(min(width, height) * 0.012))
        area = mask[
            max(0, point_y - radius) : min(height, point_y + radius + 1),
            max(0, point_x - radius) : min(width, point_x + radius + 1),
        ]
        if not np.any(area):
            return False, "クリックした人物を含むマスクを作れませんでした。胴体をクリックしてください"

    if person_box is None:
        if mask_height / mask_width < 1.05:
            return False, "人物らしい縦長の輪郭を検出できません。カメラ角度と全身の映りを確認してください"
        if y1 <= 1 or x1 <= 1 or x2 >= width - 2:
            return False, "マスクが画面端につながっています。人物の周囲に余白を作ってください"
    else:
        if box_iou(bounds, person_box) < 0.12:
            return False, "人物検出枠とマスクが一致しません。全身を画面内に入れて撮り直してください"

    return True, ""


def save_segmentation_debug(frame, mask, box, reason, prompt_point=None):
    if os.environ.get("HTB_SAVE_SEGMENT_DEBUG") != "1":
        return
    output_dir = Path(__file__).resolve().parent.parent / "segmentation_debug"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    annotated = frame.copy()
    if box is not None:
        x1, y1, x2, y2 = [int(value) for value in box]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (40, 220, 80), 3)
    if prompt_point is not None:
        point = tuple(int(round(float(value))) for value in prompt_point)
        cv2.circle(annotated, point, 10, (40, 220, 255), 3)
        cv2.drawMarker(annotated, point, (40, 220, 255), cv2.MARKER_CROSS, 24, 3)
    if mask is not None:
        tint = np.zeros_like(annotated)
        tint[:, :, 1] = 220
        selected = mask > 0
        annotated[selected] = cv2.addWeighted(annotated[selected], 0.55, tint[selected], 0.45, 0)
        cv2.imwrite(str(output_dir / f"{timestamp}_mask.png"), mask)
    annotated = put_japanese_text(annotated, reason or "OK", (16, 10), font_size=22)
    cv2.imwrite(str(output_dir / f"{timestamp}_frame.jpg"), annotated)


def _predict_mask(frame, predictor, prompt_point=None, prompt_box=None):
    if predictor is None:
        set_capture_error("SAM2を利用できません。モデルの読み込み状態を確認してください")
        return None

    import torch

    height, width = frame.shape[:2]
    manual_prompt = prompt_point is not None or prompt_box is not None
    box = prompt_box if prompt_box is not None else None
    if not manual_prompt:
        box = detect_person_box(frame)

    image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    predictor.set_image(image)

    all_masks = []
    all_scores = []
    if prompt_point is not None:
        prompt_variants = [manual_point_prompt(width, height, prompt_point)]
    else:
        prompt_variants = person_prompt_variants(width, height, box)
    with torch.inference_mode():
        for points, labels in prompt_variants:
            masks, scores, _ = predictor.predict(
                point_coords=points,
                point_labels=labels,
                box=box,
                mask_input=None,
                multimask_output=True,
            )
            all_masks.extend(list(masks))
            all_scores.extend(list(scores))

    final_mask, reason, diagnostic_mask = choose_best_valid_mask(
        all_masks,
        all_scores,
        frame.shape,
        box,
        prompt_point,
    )
    if final_mask is None:
        set_capture_error(reason or "SAM2が有効な人物マスクを作れませんでした")
        save_segmentation_debug(
            frame,
            diagnostic_mask,
            box,
            get_last_capture_error(),
            prompt_point,
        )
        return None
    save_segmentation_debug(frame, final_mask, box, "", prompt_point)
    set_capture_error("")
    return final_mask



def capture_and_segment(predictor, allow_fallback=False):
    set_capture_error("")
    # 複数のカメラを順番に試す
    cameras_to_try = parse_camera_indices()

    cap = None
    frame = None
    for camera_id in cameras_to_try:
        print(f"カメラ{camera_id}を試しています...")
        cap, frame = open_camera(camera_id, width=1280, height=720, fps=30)
        if cap is not None:
            print(f"カメラ{camera_id}が使用可能です")
            break

    if not cap or not cap.isOpened():
        print("使用可能なカメラが見つかりませんでした。")
        print_camera_help()
        set_capture_error("カメラを開けません。カメラ番号とmacOSの権限を確認してください")
        if allow_fallback:
            return create_fallback_capture()
        return None, None

    print("Enterキーで撮影・確認、ESCキーで終了")

    while True:
        if frame is None:
            ret, frame = cap.read()
            if not ret:
                print("カメラから画像が取得できませんでした")
                break

        height, width = frame.shape[:2]
        center = np.array([[width // 2, height // 2]])
        labels = np.array([1])

        # 表示用ポイント
        preview_frame = frame.copy()
        for pt in center:
            cv2.circle(preview_frame, tuple(pt), 5, (0, 0, 255), -1)

        # プレビュー画面を大きくする
        preview_width = 1280  # プレビュー画面の幅
        preview_height = 720  # プレビュー画面の高さ
        preview_frame_resized = cv2.resize(preview_frame, (preview_width, preview_height))

        cv2.imshow("Live Preview (ESC to quit, Enter to capture)", preview_frame_resized)
        key = cv2.waitKey(1)

        if key == 27:  # ESC
            break

        elif key in (10, 13):  # Enter / Return
            clean_frame = frame.copy()
            try:
                final_mask = _predict_mask(clean_frame, predictor)
            except Exception as exc:
                print(f"SAM2の推論に失敗しました: {exc}")
                set_capture_error(f"SAM2の推論に失敗しました: {exc}")
                final_mask = None
            if final_mask is None:
                if allow_fallback:
                    _, final_mask = create_fallback_capture(clean_frame)
                else:
                    print("人物マスクを作れませんでした。SAM2 checkpoint と立ち位置を確認してください。")
                    frame = None
                    continue

            # 表示用：マスクはグレースケール
            mask_display = cv2.cvtColor(final_mask, cv2.COLOR_GRAY2BGR)
            combined = cv2.hconcat([clean_frame, mask_display])
            message = "この結果で良ければ 'y' キーをだめなら'n'キーをおしてください"
            combined = put_japanese_text(combined, message, (30, height - 40))  # 高さ少し上げて調整

            # 確認画面も大きくする
            check_width = 1300  # 確認画面の幅（1600から300小さく）
            check_height = 600  # 確認画面の高さ
            combined_resized = cv2.resize(combined, (check_width, check_height))

            cv2.imshow("check", combined_resized)

            key = cv2.waitKey(0)
            if key == ord("y"):
                print("撮影完了")
                cap.release()
                cv2.destroyAllWindows()
                return clean_frame, final_mask
            if key == ord("n"):
                print("再撮影します...")
                cv2.destroyWindow("check")
                frame = None
                continue

        frame = None

    cap.release()
    cv2.destroyAllWindows()
    if allow_fallback:
        return create_fallback_capture()
    return None, None


def capture_from_existing_camera(
    camera_cap,
    predictor,
    allow_fallback=False,
    normalized_prompt_point=None,
    normalized_prompt_box=None,
    prompt_is_mirrored=False,
):
    """既に開いているカメラから直接撮影してセグメンテーションを行う"""
    set_capture_error("")
    if not camera_cap or not camera_cap.isOpened():
        set_capture_error("カメラが利用できません。接続とカメラ番号を確認してください")
        if allow_fallback:
            return create_fallback_capture()
        return None, None

    # 現在のフレームを取得
    ret, frame = camera_cap.read()
    if not ret:
        set_capture_error("カメラから画像が取得できませんでした")
        if allow_fallback:
            return create_fallback_capture()
        return None, None

    # セグメンテーション実行
    clean_frame = frame.copy()
    height, width = clean_frame.shape[:2]
    prompt_point, prompt_box = normalized_prompt_to_frame(
        width,
        height,
        normalized_prompt_point,
        normalized_prompt_box,
        mirrored=prompt_is_mirrored,
    )
    try:
        final_mask = _predict_mask(
            clean_frame,
            predictor,
            prompt_point=prompt_point,
            prompt_box=prompt_box,
        )
    except Exception as exc:
        print(f"SAM2の推論に失敗しました: {exc}")
        set_capture_error(f"SAM2の推論に失敗しました: {exc}")
        final_mask = None
    if final_mask is None:
        if allow_fallback:
            _, final_mask = create_fallback_capture(clean_frame)
        else:
            if not get_last_capture_error():
                set_capture_error("人物マスクを作れませんでした。立ち位置を確認してください")
            return None, None

    print("撮影完了")
    return clean_frame, final_mask
