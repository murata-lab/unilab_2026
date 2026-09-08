import os
import platform

import cv2


def parse_camera_indices(default_count=8):
    raw_value = os.environ.get("HTB_CAMERA_INDEX", "").strip()
    if raw_value:
        indices = []
        for item in raw_value.split(","):
            item = item.strip()
            if item:
                indices.append(int(item))
        return indices
    return list(range(default_count))


def camera_backend():
    if platform.system() == "Darwin":
        return cv2.CAP_AVFOUNDATION
    return 0


def open_camera(camera_id, width=640, height=480, fps=30):
    backend = camera_backend()
    cap = cv2.VideoCapture(camera_id, backend) if backend else cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        cap.release()
        return None, None

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    frame = None
    for _ in range(8):
        ret, candidate = cap.read()
        if ret and candidate is not None:
            frame = candidate
            break

    if frame is None:
        cap.release()
        return None, None

    return cap, frame


def print_camera_help():
    print("カメラを開けませんでした。macOSの場合は次を確認してください。")
    print("1. システム設定 > プライバシーとセキュリティ > カメラ")
    print("2. 使用しているターミナル、または Python にカメラ権限を付ける")
    print("3. 権限を変更したらターミナルを再起動してからゲームを起動する")
    print("4. 外付けカメラを固定する場合: HTB_CAMERA_INDEX=1 .venv_macos313/bin/python games/main.py")
