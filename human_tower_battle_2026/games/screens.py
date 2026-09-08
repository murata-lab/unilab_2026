import pygame

from ranking import RankingManager

try:
    from paths import BACKGROUND_IMAGE
except ImportError:
    BACKGROUND_IMAGE = "background_stage.png"


BASE_WIDTH, BASE_HEIGHT = 1440, 2489

NAVY = (10, 24, 55)
PANEL = (13, 31, 69, 224)
PANEL_LIGHT = (24, 54, 102, 220)
CYAN = (44, 210, 224)
CYAN_HOVER = (91, 231, 238)
CORAL = (255, 94, 112)
GOLD = (255, 198, 78)
WHITE = (246, 250, 255)
MUTED = (184, 205, 232)


def ui_font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc" if bold else "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for candidate in candidates:
        try:
            return pygame.font.Font(candidate, max(12, int(size)))
        except Exception:
            continue
    return pygame.font.Font(None, max(12, int(size)))


def load_background(size):
    try:
        image = pygame.image.load(str(BACKGROUND_IMAGE)).convert()
        return pygame.transform.smoothscale(image, size)
    except Exception as exc:
        print(f"背景画像を読み込めません。グラデーションで続行します: {exc}")
        surface = pygame.Surface(size)
        height = max(1, size[1])
        for y in range(height):
            ratio = y / height
            color = (
                int(8 + 9 * ratio),
                int(18 + 26 * ratio),
                int(50 + 45 * ratio),
            )
            pygame.draw.line(surface, color, (0, y), (size[0], y))
        return surface


def draw_panel(surface, rect, fill=PANEL, border=CYAN, radius=24, border_width=2):
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(panel, fill, panel.get_rect(), border_radius=radius)
    pygame.draw.rect(panel, (*border, 210), panel.get_rect(), border_width, border_radius=radius)
    surface.blit(panel, rect.topleft)


def draw_shadow_text(surface, text, font, color, center, shadow_offset=3):
    shadow = font.render(text, True, NAVY)
    shadow_rect = shadow.get_rect(center=(center[0] + shadow_offset, center[1] + shadow_offset))
    surface.blit(shadow, shadow_rect)
    rendered = font.render(text, True, color)
    rect = rendered.get_rect(center=center)
    surface.blit(rendered, rect)
    return rect


class Button:
    def __init__(
        self,
        x,
        y,
        width,
        height,
        text,
        font_size=32,
        color=CYAN,
        hover_color=CYAN_HOVER,
        text_color=NAVY,
    ):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = text
        self.color = color
        self.hover_color = hover_color
        self.text_color = text_color
        self.current_color = color
        self.font = ui_font(font_size, bold=True)

    def draw(self, surface):
        shadow_rect = self.rect.move(0, max(2, self.rect.height // 14))
        pygame.draw.rect(surface, (5, 18, 42), shadow_rect, border_radius=max(8, self.rect.height // 4))
        pygame.draw.rect(surface, self.current_color, self.rect, border_radius=max(8, self.rect.height // 4))
        pygame.draw.rect(surface, WHITE, self.rect, max(1, self.rect.height // 24), border_radius=max(8, self.rect.height // 4))
        label = self.font.render(self.text, True, self.text_color)
        surface.blit(label, label.get_rect(center=self.rect.center))

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.current_color = self.hover_color if self.rect.collidepoint(event.pos) else self.color
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            return self.rect.collidepoint(event.pos)
        return False


class StartScreen:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.scale = min(width / BASE_WIDTH, height / BASE_HEIGHT)
        self.ranking_manager = RankingManager()
        self.background = load_background((width, height))

        button_width = max(190, int(660 * self.scale))
        button_height = max(58, int(150 * self.scale))
        button_x = (width - button_width) // 2
        button_y = int(height * 0.70)
        self.start_button = Button(
            button_x,
            button_y,
            button_width,
            button_height,
            "ゲームスタート",
            max(22, int(52 * self.scale)),
        )

        self.eyebrow_font = ui_font(max(13, int(34 * self.scale)), bold=True)
        self.title_font = ui_font(max(31, int(104 * self.scale)), bold=True)
        self.subtitle_font = ui_font(max(16, int(42 * self.scale)))
        self.info_font = ui_font(max(14, int(34 * self.scale)), bold=True)
        self.ranking_font = ui_font(max(16, int(46 * self.scale)), bold=True)

    def draw(self, surface):
        surface.blit(self.background, (0, 0))
        shade = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        shade.fill((3, 12, 34, 42))
        surface.blit(shade, (0, 0))

        panel_width = min(self.width - 32, max(300, int(1080 * self.scale)))
        panel_height = min(self.height - 48, max(430, int(1250 * self.scale)))
        panel_rect = pygame.Rect(
            (self.width - panel_width) // 2,
            int(self.height * 0.15),
            panel_width,
            panel_height,
        )
        draw_panel(
            surface,
            panel_rect,
            fill=(8, 24, 61, 224),
            border=CYAN,
            radius=max(16, int(38 * self.scale)),
            border_width=max(2, int(4 * self.scale)),
        )

        center_x = self.width // 2
        eyebrow = self.eyebrow_font.render("CAMERA × PHYSICS", True, CYAN)
        surface.blit(eyebrow, eyebrow.get_rect(center=(center_x, panel_rect.top + int(panel_height * 0.12))))
        draw_shadow_text(
            surface,
            "人間タワー",
            self.title_font,
            WHITE,
            (center_x, panel_rect.top + int(panel_height * 0.26)),
        )
        draw_shadow_text(
            surface,
            "バトル",
            self.title_font,
            GOLD,
            (center_x, panel_rect.top + int(panel_height * 0.39)),
        )

        subtitle = self.subtitle_font.render("撮って、選んで、積み上げよう！", True, MUTED)
        surface.blit(subtitle, subtitle.get_rect(center=(center_x, panel_rect.top + int(panel_height * 0.51))))

        self.draw_rankings(surface, panel_rect)

        guide_text = self.info_font.render("ENTER 撮影　　1・2・3 配置", True, WHITE)
        guide_rect = guide_text.get_rect(center=(center_x, panel_rect.top + int(panel_height * 0.65)))
        guide_bg = guide_rect.inflate(max(30, int(80 * self.scale)), max(18, int(34 * self.scale)))
        pygame.draw.rect(surface, (17, 49, 92), guide_bg, border_radius=max(10, int(24 * self.scale)))
        pygame.draw.rect(surface, (77, 126, 180), guide_bg, max(1, int(3 * self.scale)), border_radius=max(10, int(24 * self.scale)))
        surface.blit(guide_text, guide_rect)

        self.start_button.draw(surface)

    def draw_rankings(self, surface, panel_rect):
        daily_rankings = self.ranking_manager.get_daily_rankings()
        rank_text = f"今日のベスト　{daily_rankings[0]['score']}人" if daily_rankings else "今日のベスト　--"
        rendered = self.ranking_font.render(rank_text, True, GOLD)
        center = (self.width // 2, panel_rect.top + int(panel_rect.height * 0.58))
        rect = rendered.get_rect(center=center)
        surface.blit(rendered, rect)

    def handle_event(self, event):
        return self.start_button.handle_event(event)


class GameOverScreen:
    def __init__(self, width, height, score=0, ranking_manager=None):
        self.width = width
        self.height = height
        self.score = score
        self.scale = min(width / BASE_WIDTH, height / BASE_HEIGHT)
        self.background = load_background((width, height))
        self.ranking_manager = ranking_manager or RankingManager()

        if score > 0:
            daily_rankings = self.ranking_manager.get_daily_rankings()
            if not any(entry["score"] == score for entry in daily_rankings):
                self.ranking_manager.add_score(score)

        button_width = max(190, int(620 * self.scale))
        button_height = max(54, int(130 * self.scale))
        button_x = (width - button_width) // 2
        button_y = int(height * 0.66)
        button_gap = max(14, int(42 * self.scale))
        self.restart_button = Button(
            button_x,
            button_y,
            button_width,
            button_height,
            "もう一度プレイ",
            max(19, int(44 * self.scale)),
        )
        self.quit_button = Button(
            button_x,
            button_y + button_height + button_gap,
            button_width,
            button_height,
            "終了",
            max(19, int(44 * self.scale)),
            color=CORAL,
            hover_color=(255, 133, 143),
            text_color=WHITE,
        )
        self.eyebrow_font = ui_font(max(13, int(32 * self.scale)), bold=True)
        self.title_font = ui_font(max(32, int(100 * self.scale)), bold=True)
        self.score_font = ui_font(max(36, int(126 * self.scale)), bold=True)
        self.label_font = ui_font(max(16, int(42 * self.scale)), bold=True)
        self.ranking_font = ui_font(max(17, int(48 * self.scale)), bold=True)

    def draw(self, surface):
        surface.blit(self.background, (0, 0))
        shade = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        shade.fill((3, 10, 31, 84))
        surface.blit(shade, (0, 0))

        panel_width = min(self.width - 32, max(300, int(1000 * self.scale)))
        panel_height = min(self.height - 48, max(470, int(1420 * self.scale)))
        panel_rect = pygame.Rect(
            (self.width - panel_width) // 2,
            int(self.height * 0.11),
            panel_width,
            panel_height,
        )
        draw_panel(surface, panel_rect, fill=(8, 23, 58, 232), border=CORAL, radius=max(16, int(38 * self.scale)))
        center_x = self.width // 2

        eyebrow = self.eyebrow_font.render("RESULT", True, CORAL)
        surface.blit(eyebrow, eyebrow.get_rect(center=(center_x, panel_rect.top + int(panel_height * 0.10))))
        draw_shadow_text(surface, "GAME OVER", self.title_font, WHITE, (center_x, panel_rect.top + int(panel_height * 0.21)))

        label = self.label_font.render("積み上げた人数", True, MUTED)
        surface.blit(label, label.get_rect(center=(center_x, panel_rect.top + int(panel_height * 0.34))))
        score = self.score_font.render(f"{self.score}", True, GOLD)
        surface.blit(score, score.get_rect(center=(center_x, panel_rect.top + int(panel_height * 0.44))))
        people = self.label_font.render("人", True, GOLD)
        surface.blit(people, people.get_rect(midleft=(center_x + score.get_width() // 2 + 8, panel_rect.top + int(panel_height * 0.44))))

        self.draw_rankings(surface, panel_rect)
        self.restart_button.draw(surface)
        self.quit_button.draw(surface)

    def draw_rankings(self, surface, panel_rect):
        daily_rankings = self.ranking_manager.get_daily_rankings()
        top_score = daily_rankings[0]["score"] if daily_rankings else 0
        player_rank = self.ranking_manager.get_player_rank(self.score)
        text = f"今日の1位  {top_score}人　｜　あなた  {player_rank}位"
        rendered = self.ranking_font.render(text, True, WHITE)
        rect = rendered.get_rect(center=(self.width // 2, panel_rect.top + int(panel_rect.height * 0.56)))
        badge = rect.inflate(max(30, int(70 * self.scale)), max(18, int(32 * self.scale)))
        pygame.draw.rect(surface, PANEL_LIGHT, badge, border_radius=max(10, int(22 * self.scale)))
        pygame.draw.rect(surface, (71, 116, 172), badge, max(1, int(3 * self.scale)), border_radius=max(10, int(22 * self.scale)))
        surface.blit(rendered, rect)

    def handle_event(self, event):
        if self.restart_button.handle_event(event):
            return "restart"
        if self.quit_button.handle_event(event):
            return "quit"
        return None
