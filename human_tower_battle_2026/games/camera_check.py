from pathlib import Path

import cv2
import numpy as np

from camera_utils import open_camera, parse_camera_indices, print_camera_help
from photo import detect_person_box


OUTPUT_DIR = Path(__file__).resolve().parent.parent / "camera_check_output"


def labeled_frame(camera_id, frame):
    result = frame.copy()
    height, width = result.shape[:2]
    person_box = detect_person_box(result)
    if person_box is not None:
        x1, y1, x2, y2 = [int(value) for value in person_box]
        cv2.rectangle(result, (x1, y1), (x2, y2), (60, 220, 100), 4)
        status_text = "PERSON OK"
        status_color = (60, 220, 100)
    else:
        guide = (
            int(width * 0.05),
            int(height * 0.03),
            int(width * 0.95),
            int(height * 0.98),
        )
        cv2.rectangle(result, guide[:2], guide[2:], (30, 210, 240), 3)
        status_text = "NO FULL BODY"
        status_color = (30, 120, 255)
    cv2.putText(
        result,
        f"Camera {camera_id}",
        (24, 48),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (0, 0, 0),
        6,
        cv2.LINE_AA,
    )
    cv2.putText(
        result,
        f"Camera {camera_id}",
        (24, 48),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        result,
        status_text,
        (24, height - 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 0, 0),
        6,
        cv2.LINE_AA,
    )
    cv2.putText(
        result,
        status_text,
        (24, height - 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        status_color,
        2,
        cv2.LINE_AA,
    )
    return result


def save_contact_sheet(frames):
    if not frames:
        return None

    labeled = []
    for camera_id, frame in frames:
        resized = cv2.resize(frame, (320, 240))
        labeled.append(labeled_frame(camera_id, resized))

    rows = []
    for start in range(0, len(labeled), 3):
        row_frames = labeled[start:start + 3]
        while len(row_frames) < 3:
            row_frames.append(np.zeros_like(labeled[0]))
        rows.append(cv2.hconcat(row_frames))

    sheet = cv2.vconcat(rows)
    output_path = OUTPUT_DIR / "contact_sheet.jpg"
    cv2.imwrite(str(output_path), sheet)
    return output_path


def main():
    found = False
    saved_frames = []
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for camera_id in parse_camera_indices(default_count=10):
        print(f"カメラ{camera_id}を確認中...")
        cap, frame = open_camera(camera_id, width=640, height=480, fps=30)
        if cap is None:
            print(f"  NG: 開けない、またはフレーム取得不可")
            continue

        found = True
        print(f"  OK: {frame.shape[1]}x{frame.shape[0]}")
        output_path = OUTPUT_DIR / f"camera_{camera_id}.jpg"
        cv2.imwrite(str(output_path), labeled_frame(camera_id, frame))
        print(f"  保存: {output_path}")
        saved_frames.append((camera_id, frame))
        cap.release()

    if not found:
        print_camera_help()
        return 1

    contact_sheet = save_contact_sheet(saved_frames)
    if contact_sheet:
        print(f"比較画像: {contact_sheet}")

    print("使いたい番号を HTB_CAMERA_INDEX に指定してください。例: HTB_CAMERA_INDEX=1 .venv_macos313/bin/python games/main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
