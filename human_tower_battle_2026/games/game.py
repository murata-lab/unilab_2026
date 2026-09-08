import pymunk


def create_space(width, height):
    space = pymunk.Space()

    # 物理演算の最適化設定（滑らかな動きのため）
    space.iterations = 20  # 物理演算の反復回数を増やして滑らかさを向上
    space.sleep_time_threshold = 0.3
    space.idle_speed_threshold = 4.0

    # 重力加速度をウィンドウサイズに比例させる
    # 基準サイズ: 1440x2489 での重力 600 を基準とする（重力をさらに下げて落ちにくくする）
    base_width, base_height = 1440, 2489
    base_gravity = 600

    # ウィンドウの高さに比例して重力を調整
    gravity_scale = height / base_height
    gravity_y = base_gravity * gravity_scale

    space.gravity = (0, gravity_y)
    print(f"重力加速度: (0, {gravity_y:.1f}) - ウィンドウサイズ: {width}x{height}")

    # 床の物理演算は削除（描画のみ）

    # 台のサイズをウィンドウサイズに比例させる
    # 基準サイズ: 1440x2489 での台のサイズを基準とする
    base_platform_width = 800  # 台の幅を小さく
    base_platform_height = 40  # 台の高さを小さく
    base_platform_y_offset = 300  # 床からの距離

    # ウィンドウサイズに比例して台のサイズを調整
    size_scale = min(width / base_width, height / base_height)  # 小さい方に合わせる
    platform_width = int(base_platform_width * size_scale)
    platform_height = int(base_platform_height * size_scale)
    platform_y_offset = int(base_platform_y_offset * size_scale)

    platform_x = (width - platform_width) // 2
    platform_y = height - platform_y_offset  # 床からの距離を比例調整

    # 四隅の座標
    p1 = (platform_x, platform_y)
    p2 = (platform_x + platform_width, platform_y)
    platform = pymunk.Segment(space.static_body, p1, p2, platform_height // 2)
    platform.friction = 5.0  # 摩擦係数をさらに上げて滑りにくくする
    platform.elasticity = 0.05  # 反発係数をさらに下げてより安定した積み重ねに
    space.add(platform)

    # 台の情報も返す
    platform_rect = {
        "x1": platform_x,
        "x2": platform_x + platform_width,
        "y": platform_y
    }

    return space, platform_rect
