import pygame
import pymunk
import numpy as np
import cv2


def create_default_inputs(width=240, height=320):
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[:] = (245, 245, 245)
    cv2.circle(rgb, (width // 2, height // 4), width // 8, (80, 140, 240), -1)
    cv2.ellipse(
        rgb,
        (width // 2, int(height * 0.58)),
        (width // 5, height // 4),
        0,
        0,
        360,
        (80, 140, 240),
        -1,
    )

    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.circle(mask, (width // 2, height // 4), width // 8, 255, -1)
    cv2.ellipse(
        mask,
        (width // 2, int(height * 0.58)),
        (width // 5, height // 4),
        0,
        0,
        360,
        255,
        -1,
    )
    return rgb, mask


def normalize_inputs(rgb, mask):
    if rgb is None or mask is None:
        print("RGBまたはマスク画像がないため、仮の画像を使います。")
        return create_default_inputs()

    if mask.ndim == 3:
        mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)

    if rgb.shape[:2] != mask.shape[:2]:
        mask = cv2.resize(mask, (rgb.shape[1], rgb.shape[0]))

    return rgb, mask


def crop_inputs_to_mask(rgb, mask, padding_ratio=0.04):
    """Trim transparent surroundings while keeping a small visual margin."""
    rgb, mask = normalize_inputs(rgb, mask)
    mask_bin = (mask > 127).astype(np.uint8)
    points = cv2.findNonZero(mask_bin)
    if points is None:
        return rgb, mask

    x, y, width, height = cv2.boundingRect(points)
    padding = max(4, int(max(width, height) * padding_ratio))
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(rgb.shape[1], x + width + padding)
    y2 = min(rgb.shape[0], y + height + padding)
    return rgb[y1:y2, x1:x2].copy(), mask[y1:y2, x1:x2].copy()


def scale_for_target_mask_area(mask, target_area, fallback_scale=1.0):
    """Return a scale that makes the visible foreground approach target_area."""
    if target_area is None or target_area <= 0:
        return float(fallback_scale)
    foreground_area = int(np.count_nonzero(mask > 127))
    if foreground_area <= 0:
        return float(fallback_scale)
    return float(np.sqrt(float(target_area) / foreground_area))


def scaled_dimensions(image, scale):
    height, width = image.shape[:2]
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def scaled_mask_centroid(mask, scale):
    """Return the true foreground center after the same resize/flip as rendering."""
    if mask.ndim == 3:
        mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    _, mask_bin = cv2.threshold(mask, 250, 255, cv2.THRESH_BINARY)
    mask_bin = cv2.resize(
        mask_bin,
        scaled_dimensions(mask_bin, scale),
        interpolation=cv2.INTER_NEAREST,
    )
    mask_bin = cv2.flip(mask_bin, 1)
    moments = cv2.moments(mask_bin, binaryImage=True)
    if abs(moments["m00"]) <= 1e-6:
        return None
    return moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]


def create_transparent_surface(rgb, mask, scale=1.0):
    rgb, mask = normalize_inputs(rgb, mask)

    # マスク画像の白い部分を物体として使う（そのまま alpha に）
    _, mask_bin = cv2.threshold(mask, 250, 255, cv2.THRESH_BINARY)

    # アルファチャンネルとして使用（物体=白）
    masked_rgb = cv2.bitwise_and(rgb, rgb, mask=mask_bin)
    result = cv2.merge([masked_rgb[:, :, 0], masked_rgb[:, :, 1], masked_rgb[:, :, 2], mask_bin])

    # スケーリング
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    result = cv2.resize(result, scaled_dimensions(result, scale), interpolation=interpolation)

    # 水平反転（プレビューカメラと同じ鏡像にする）
    result = cv2.flip(result, 1)  # 1 = 水平反転

    # Pygame Surfaceに変換
    result = cv2.cvtColor(result, cv2.COLOR_BGRA2RGBA)
    surface = pygame.image.frombuffer(result.tobytes(), result.shape[1::-1], "RGBA")

    return surface

class Animal:
    def __init__(
        self,
        space,
        x,
        y,
        rgb=None,
        mask=None,
        scale=0.1,
        target_mask_area=None,
    ):
        self.space = space
        self.x = x
        self.y = y
        rgb, mask = normalize_inputs(rgb, mask)
        rgb, mask = crop_inputs_to_mask(rgb, mask)
        self.target_mask_area = target_mask_area
        self.source_mask_area = int(np.count_nonzero(mask > 127))
        self.scale = scale_for_target_mask_area(mask, target_mask_area, scale)

        # 回転キャッシュ（パフォーマンス向上）
        self._rotation_cache = {}
        self._cache_size_limit = 360



        self.image = create_transparent_surface(rgb, mask, self.scale)

        # 輪郭（物理ポリゴン）も mask から取得
        self.points = self.load_mask_points(mask, self.scale)
        if self.points:
            foreground_center = scaled_mask_centroid(mask, self.scale)
            if foreground_center is not None:
                center_x, center_y = foreground_center
            else:
                center_x = np.mean([p[0] for p in self.points])
                center_y = np.mean([p[1] for p in self.points])
            self.center_x = center_x
            self.center_y = center_y

            points_shifted = [(px - center_x, py - center_y) for (px, py) in self.points]

            self.body = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
            self.body.position = (x, y)

            # 物理演算の最適化: ポリゴンの頂点数を制限
            if len(points_shifted) > 20:
                # 頂点数が多い場合は簡素化
                simplified_points = self.simplify_polygon(points_shifted, tolerance=2.0)
                self.shape = pymunk.Poly(self.body, simplified_points)
            else:
                self.shape = pymunk.Poly(self.body, points_shifted)

            self.shape.friction = 3.5
            self.shape.elasticity = 0.1
            # 全形状に平らな足場を付けるとアンバランスさが消えるため、
            # 衝突判定には実際の人物輪郭だけを使う。
            self.shapes = [self.shape]
            # 密度は設定しない（質量で調整するため）
            self.space.add(self.body, *self.shapes)
            self.points = points_shifted
        else:
            raise ValueError("輪郭が見つかりませんでした")

        self.falling = False

    def simplify_polygon(self, points, tolerance=2.0):
        """ポリゴンの頂点数を削減して物理演算を軽量化"""
        if len(points) <= 8:
            return points

        # 簡易的な頂点削減アルゴリズム
        simplified = [points[0]]
        for i in range(1, len(points) - 1):
            p1 = simplified[-1]
            p2 = points[i]
            p3 = points[i + 1]

            # 3点間の距離を計算
            dist1 = np.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
            dist2 = np.sqrt((p3[0] - p2[0])**2 + (p3[1] - p2[1])**2)

            # 距離が一定以上ある場合のみ頂点を保持
            if dist1 > tolerance or dist2 > tolerance:
                simplified.append(p2)

        simplified.append(points[-1])
        return simplified

    def remove_from_space(self):
        """物理空間からこの動物を削除する"""
        for shape in getattr(self, "shapes", []):
            if shape in self.space.shapes:
                self.space.remove(shape)
        if hasattr(self, 'body') and self.body:
            if self.body in self.space.bodies:
                self.space.remove(self.body)

    def load_mask_points(self, mask, scale):
        _, mask = normalize_inputs(None, mask) if mask is None else (None, mask)
        if mask.ndim == 3:
            mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)

        _, mask_bin = cv2.threshold(mask, 250, 255, cv2.THRESH_BINARY)
        mask_bin = cv2.resize(
            mask_bin,
            scaled_dimensions(mask_bin, scale),
            interpolation=cv2.INTER_NEAREST,
        )

        # 水平反転（プレビューカメラと同じ鏡像にする）
        mask_bin = cv2.flip(mask_bin, 1)  # 1 = 水平反転

        contours, _ = cv2.findContours(mask_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            largest_area = max(cv2.contourArea(contour) for contour in contours)
            if largest_area < 10:
                return None
            significant = [
                contour
                for contour in contours
                if cv2.contourArea(contour) >= max(10.0, largest_area * 0.02)
            ]
            hull = cv2.convexHull(np.vstack(significant))
            epsilon = max(1.0, 0.01 * cv2.arcLength(hull, True))
            approx = cv2.approxPolyDP(hull, epsilon, True)
            points = [(int(pt[0][0]), int(pt[0][1])) for pt in approx]
            points = list(dict.fromkeys(points))

            if len(points) > 30:
                step = max(1, len(points) // 30)
                points = points[::step]
            if len(points) >= 3:
                return points
        return None

    def start_fall(self):
        self.body.body_type = pymunk.Body.DYNAMIC

        # さらに軽い質量設定（より軽快な動きに）
        mass = 0.05  # 0.1から0.05に軽量化

        if self.image and self.points:
            moment = pymunk.moment_for_poly(mass, self.points)
        else:
            moment = pymunk.moment_for_box(mass, (50, 50))

        self.body.mass = mass
        # 回転慣性を大きくして、接触時に勢いよく転がるのを抑える。
        self.body.moment = moment * 3.0
        self.body.velocity = (0, 0)
        self.body.angular_velocity = 0  # 角速度を初期化
        self.falling = True

    def stabilize_motion(self):
        """落下中の横滑りと回転を緩やかに減衰させ、積み上げを安定させる。"""
        if not self.falling or self.body.body_type != pymunk.Body.DYNAMIC:
            return

        velocity_x, velocity_y = self.body.velocity
        velocity_x *= 0.96
        angular_velocity = self.body.angular_velocity

        # 大きな回転は形状由来の挙動として残す。ほぼ静止した後の
        # 微小な揺れだけを減衰させ、いつまでも震え続けるのを防ぐ。
        if abs(velocity_y) < 8.0 and abs(angular_velocity) < 0.25:
            angular_velocity *= 0.94
        else:
            angular_velocity *= 0.995

        if abs(velocity_x) < 0.8:
            velocity_x = 0.0
        if abs(angular_velocity) < 0.025:
            angular_velocity = 0.0

        self.body.velocity = (velocity_x, velocity_y)
        self.body.angular_velocity = angular_velocity



    def draw(self, screen):
        x, y = self.body.position
        angle = -self.body.angle * 57.2958  # pymunkは反時計回り → 度に変換

        if self.image:
            offset = pygame.Vector2(self.center_x, self.center_y)

            # 回転キャッシュを使用（パフォーマンス向上）
            angle_rounded = round(angle)

            if angle_rounded not in self._rotation_cache:
                # キャッシュサイズを制限
                if len(self._rotation_cache) >= self._cache_size_limit:
                    # 最も古いキャッシュを削除（LRU方式）
                    oldest_key = min(self._rotation_cache.keys())
                    del self._rotation_cache[oldest_key]

                # 高品質な回転処理
                rotated_image = pygame.transform.rotate(self.image, angle_rounded)
                # 回転後の画像を最適化
                rotated_image = rotated_image.convert_alpha()
                self._rotation_cache[angle_rounded] = rotated_image

            rotated_image = self._rotation_cache[angle_rounded]
            image_rect = self.image.get_rect()
            rotated_rect = rotated_image.get_rect()

            # 画像中心に対する相対オフセット（回転前）
            offset_from_center = offset - pygame.Vector2(image_rect.width / 2, image_rect.height / 2)

            # 回転角度を反転して、pymunkと一致させる
            rotated_offset = offset_from_center.rotate(-angle_rounded)

            # 左上座標で貼る
            draw_pos = (x - rotated_offset.x - rotated_rect.width / 2,
                        y - rotated_offset.y - rotated_rect.height / 2)

            screen.blit(rotated_image, draw_pos)
