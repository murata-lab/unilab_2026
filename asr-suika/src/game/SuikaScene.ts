import Phaser from "phaser";

import beachUrl from "../../assets/backgrounds/beach.png?url";
import characterUrl from "../../assets/sprites/character-pose-sheet.png?url";
import crabUrl from "../../assets/sprites/crab-walk-sheet-normalized.png?url";
import watermelonUrl from "../../assets/sprites/watermelon-break-sheet-normalized.png?url";
import {
  COMMANDS,
  GAME_CONFIG,
  type CustomCommands,
  type VoiceCommand,
} from "./config";

const WIDTH = 1200;
const HEIGHT = 900;
const ROWS = 5;
const COLUMNS = 7;
const PLAYER_SPRITE_SCALE = 0.61;
const PLAYER_GROUND_OFFSET = 5;
const WALK_FRAME_SAFE_HEIGHT = 400;
const GRID_ROW_Y = [455, 535, 620, 710, 800] as const;
const GRID_ROW_WIDTH = [920, 970, 1020, 1070, 1120] as const;
const CRAB_OFFSCREEN_X = 95;
const CRAB_COLORS = ["red", "blue", "orange"] as const;
type GameMode = "normal" | "hard" | "custom";
type SceneData = {
  autoStart?: boolean;
  mode?: GameMode;
  customCommands?: Partial<CustomCommands>;
};
type MicrophoneState = "connecting" | "connected" | "error" | "disconnected";
type CrabColor = (typeof CRAB_COLORS)[number];
type HorizontalDirection = -1 | 1;

enum Direction {
  North,
  East,
  South,
  West,
}

type GridPosition = {
  row: number;
  column: number;
};

type Fruit = GridPosition & {
  container: Phaser.GameObjects.Container;
  sprite: Phaser.GameObjects.Sprite;
  golden: boolean;
  breaking: boolean;
};

type Crab = {
  slot: number;
  row: number;
  direction: HorizontalDirection;
  container: Phaser.GameObjects.Container;
  sprite: Phaser.GameObjects.Sprite;
  color: CrabColor;
  hasHitPlayer: boolean;
  defeated: boolean;
  moveTween?: Phaser.Tweens.Tween;
};

type VoiceMessage =
  | {
      type: "status";
      microphone: MicrophoneState;
      message?: string;
    }
  | {
      type: "command";
      command: VoiceCommand;
      raw: string;
      confidence?: number;
    }
  | {
      type: "ping";
    };

export class SuikaScene extends Phaser.Scene {
  private player!: Phaser.GameObjects.Container;
  private playerSprite!: Phaser.GameObjects.Sprite;
  private playerShadow!: Phaser.GameObjects.Ellipse;
  private gridGraphics!: Phaser.GameObjects.Graphics;
  private timerText!: Phaser.GameObjects.Text;
  private scoreText!: Phaser.GameObjects.Text;
  private commandText!: Phaser.GameObjects.Text;
  private microphoneText!: Phaser.GameObjects.Text;
  private microphoneDot!: Phaser.GameObjects.Arc;
  private countdownText!: Phaser.GameObjects.Text;
  private countdownShade!: Phaser.GameObjects.Rectangle;
  private resultObjects: Phaser.GameObjects.GameObject[] = [];
  private resultActionPending = false;
  private commandGuide?: Phaser.GameObjects.Text;
  private commandGuideEvent?: Phaser.Time.TimerEvent;

  private playerPosition: GridPosition = { row: 4, column: 3 };
  private direction = Direction.North;
  private fruits: Fruit[] = [];
  private crabs: Crab[] = [];
  private crabSlotsEnabled: boolean[] = [];
  private pendingCrabSlots = new Set<number>();
  private crabEvents: Phaser.Time.TimerEvent[] = [];
  private crabWarnings: Phaser.GameObjects.Container[] = [];
  private score = 0;
  private roundStartedAt = 0;
  private gameMode?: GameMode;
  private customCommands: Partial<CustomCommands> = {};
  private waitingToStart = true;
  private roundActive = false;
  private timeExpired = false;
  private moving = false;
  private striking = false;
  private pendingStrike = false;
  private pendingTurns = 0;
  private playerStunned = false;
  private moveTween?: Phaser.Tweens.Tween;
  private stunBlinkEvent?: Phaser.Time.TimerEvent;
  private stunEndEvent?: Phaser.Time.TimerEvent;
  private socket?: WebSocket;
  private reconnectEvent?: Phaser.Time.TimerEvent;
  private destroyed = false;

  constructor() {
    super("suika");
  }

  preload(): void {
    this.load.image("beach", beachUrl);
    this.load.spritesheet("character", characterUrl, {
      frameWidth: 418,
      frameHeight: 418,
    });
    this.load.spritesheet("watermelons", watermelonUrl, {
      frameWidth: 443,
      frameHeight: 443,
    });
    this.load.spritesheet("crabs", crabUrl, {
      frameWidth: 512,
      frameHeight: 512,
    });
  }

  create(data: SceneData = {}): void {
    this.resetRoundState();
    this.gameMode = data.mode;
    this.customCommands = { ...data.customCommands };
    const commandHint = document.querySelector<HTMLElement>(".commands");
    if (commandHint) {
      commandHint.textContent =
        data.mode === "custom"
          ? "登録した5つの言葉で操作"
          : "「すすめ」「とまれ」「みぎ」「ひだり」「たたけ」";
    }
    this.destroyed = false;
    this.add
      .image(WIDTH / 2, HEIGHT / 2, "beach")
      .setDisplaySize(WIDTH, HEIGHT)
      .setDepth(-100);
    this.add
      .rectangle(WIDTH / 2, 625, WIDTH, 550, 0xffe4a0, 0.04)
      .setBlendMode(Phaser.BlendModes.SCREEN)
      .setDepth(-90);

    this.createAnimations();
    this.createGrid();
    this.createPlayer();
    this.createUi();
    this.bindKeyboard();
    this.connectVoiceSocket();

    for (let index = 0; index < GAME_CONFIG.fruit.initialCount; index += 1) {
      this.spawnFruit();
    }

    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => this.shutdown());
    if (data.autoStart && data.mode) {
      this.startCountdown();
    } else {
      this.scene.start("title");
    }
  }

  update(time: number): void {
    if (!this.moving && !this.striking && !this.playerStunned) {
      this.playerSprite.y = PLAYER_GROUND_OFFSET + Math.sin(time / 360) * 1.2;
    }

    if (!this.roundActive) {
      return;
    }

    this.checkCrabCollisions();

    const remaining = Math.max(
      0,
      GAME_CONFIG.round.durationMs - (time - this.roundStartedAt),
    );
    this.timerText.setText(String(Math.ceil(remaining / 1000)).padStart(2, "0"));
    if (remaining <= GAME_CONFIG.round.timerWarningMs) {
      this.timerText.setColor("#ff775f");
    }

    if (remaining === 0) {
      this.expireRound();
    }
  }

  private createAnimations(): void {
    const directions = [
      { key: "front", idle: 0, walk: 3 },
      { key: "side", idle: 1, walk: 4 },
      { key: "back", idle: 2, walk: 5 },
    ];

    for (const direction of directions) {
      this.anims.create({
        key: `walk-${direction.key}`,
        frames: [
          { key: "character", frame: direction.idle },
          { key: "character", frame: direction.walk },
        ],
        // 1マス（1秒）で2周期。終了直前の余分な足の切り替えを防ぐ。
        frameRate: 4,
        repeat: 1,
      });
    }

    CRAB_COLORS.forEach((color, index) => {
      this.anims.create({
        key: `crab-walk-${color}`,
        frames: [
          { key: "crabs", frame: index * 2 },
          { key: "crabs", frame: index * 2 + 1 },
        ],
        frameRate: 3.5,
        repeat: -1,
      });
    });
  }

  private scheduleCrabEncounters(): void {
    const warningTimes =
      this.gameMode === "hard"
        ? GAME_CONFIG.crab.hardSlotWarningTimesMs
        : GAME_CONFIG.crab.normalSlotWarningTimesMs;
    this.crabSlotsEnabled = warningTimes.map(() => false);
    warningTimes.forEach((warningAt, slot) => {
      const event = this.time.delayedCall(warningAt, () => {
        if (!this.roundActive || this.timeExpired) {
          return;
        }
        this.crabSlotsEnabled[slot] = true;
        if (this.gameMode === "hard" && warningAt === 0) {
          this.spawnCrab(
            slot,
            Phaser.Math.Between(0, ROWS - 1),
            Math.random() < 0.5 ? 1 : -1,
          );
          return;
        }
        this.showCrabWarning(slot);
      });
      this.crabEvents.push(event);
    });
  }

  private showCrabWarning(slot: number): void {
    if (
      !this.roundActive ||
      !this.crabSlotsEnabled[slot] ||
      this.pendingCrabSlots.has(slot) ||
      this.crabs.some((crab) => crab.slot === slot)
    ) {
      return;
    }

    this.pendingCrabSlots.add(slot);
    const row = Phaser.Math.Between(0, ROWS - 1);
    const direction: HorizontalDirection = Math.random() < 0.5 ? 1 : -1;
    const y = this.gridPoint(row, 0).y;
    const x = direction === 1 ? 38 : WIDTH - 38;
    const badge = this.add
      .circle(0, 0, 27, 0xe7442e, 0.96)
      .setStrokeStyle(4, 0xfff4a8, 1);
    const label = this.add
      .text(0, -2, "!", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "38px",
        fontStyle: "bold",
        color: "#ffffff",
        stroke: "#8e1e16",
        strokeThickness: 3,
      })
      .setOrigin(0.5);
    const warning = this.add
      .container(x, y - 42, [badge, label])
      .setScale(this.rowScale(row))
      .setDepth(9_000);
    this.crabWarnings.push(warning);
    this.tweens.add({
      targets: warning,
      alpha: 0.35,
      scaleX: warning.scaleX * 1.12,
      scaleY: warning.scaleY * 1.12,
      duration: 170,
      yoyo: true,
      repeat: -1,
    });

    const event = this.time.delayedCall(
      GAME_CONFIG.crab.warningDurationMs,
      () => {
        this.removeCrabWarning(warning);
        this.pendingCrabSlots.delete(slot);
        if (this.roundActive && this.crabSlotsEnabled[slot]) {
          this.spawnCrab(slot, row, direction);
        }
      },
    );
    this.crabEvents.push(event);
  }

  private spawnCrab(
    slot: number,
    row: number,
    direction: HorizontalDirection,
  ): void {
    if (this.crabs.length >= GAME_CONFIG.crab.maxCount) {
      this.queueCrabRespawn(slot);
      return;
    }

    const color = Phaser.Utils.Array.GetRandom([...CRAB_COLORS]);
    const colorIndex = CRAB_COLORS.indexOf(color);
    const y = this.gridPoint(row, 0).y;
    const startX = direction === 1 ? -CRAB_OFFSCREEN_X : WIDTH + CRAB_OFFSCREEN_X;
    const endX = direction === 1 ? WIDTH + CRAB_OFFSCREEN_X : -CRAB_OFFSCREEN_X;
    const shadow = this.add.ellipse(0, -1, 300, 42, 0x5b482c, 0.16);
    const sprite = this.add
      .sprite(0, 0, "crabs", colorIndex * 2)
      .setOrigin(0.5, 464 / 512)
      .setFlipX(direction === -1);
    const container = this.add.container(startX, y, [shadow, sprite]);
    const crab: Crab = {
      slot,
      row,
      direction,
      container,
      sprite,
      color,
      hasHitPlayer: false,
      defeated: false,
    };

    this.updateCrabPerspective(crab);
    sprite.play(`crab-walk-${color}`, true);
    this.crabs.push(crab);
    const speed = 82 + row * 8;
    crab.moveTween = this.tweens.add({
      targets: container,
      x: endX,
      duration: ((WIDTH + CRAB_OFFSCREEN_X * 2) / speed) * 1_000,
      ease: "Linear",
      onComplete: () => this.removeCrab(crab, true),
    });
  }

  private removeCrab(crab: Crab, respawn: boolean): void {
    if (!this.crabs.includes(crab)) {
      return;
    }
    this.crabs = this.crabs.filter((candidate) => candidate !== crab);
    this.tweens.killTweensOf(crab.container);
    crab.moveTween = undefined;
    crab.container.destroy();
    if (respawn && this.roundActive && this.crabSlotsEnabled[crab.slot]) {
      this.queueCrabRespawn(crab.slot);
    }
  }

  private queueCrabRespawn(slot: number): void {
    const hardMode = this.gameMode === "hard";
    const event = this.time.delayedCall(
      Phaser.Math.Between(
        hardMode
          ? GAME_CONFIG.crab.hardRespawnMinMs
          : GAME_CONFIG.crab.respawnMinMs,
        hardMode
          ? GAME_CONFIG.crab.hardRespawnMaxMs
          : GAME_CONFIG.crab.respawnMaxMs,
      ),
      () => this.showCrabWarning(slot),
    );
    this.crabEvents.push(event);
  }

  private removeCrabWarning(warning: Phaser.GameObjects.Container): void {
    this.crabWarnings = this.crabWarnings.filter(
      (candidate) => candidate !== warning,
    );
    this.tweens.killTweensOf(warning);
    warning.destroy();
  }

  private updateCrabPerspective(crab: Crab): void {
    crab.container.setScale(0.24 + crab.row * 0.03);
    crab.container.setDepth(100 + crab.container.y);
  }

  private checkCrabCollisions(): void {
    if (this.playerStunned) {
      return;
    }

    for (const crab of this.crabs) {
      if (crab.hasHitPlayer || crab.defeated) {
        continue;
      }
      const perspective = this.rowScale(crab.row);
      const touching =
        Math.abs(crab.container.x - this.player.x) <= 92 * perspective &&
        Math.abs(crab.container.y - this.player.y) <= 34 * perspective;
      if (touching) {
        crab.hasHitPlayer = true;
        this.stunPlayer();
        return;
      }
    }
  }

  private stunPlayer(): void {
    this.playerStunned = true;
    this.pendingStrike = false;
    this.pendingTurns = 0;
    if (this.moving && this.moveTween) {
      this.moveTween.pause();
      this.playerSprite.anims.pause();
    }

    let tinted = true;
    this.playerSprite.setTint(0xff2f2f);
    this.stunBlinkEvent = this.time.addEvent({
      delay: 150,
      repeat: GAME_CONFIG.crab.stunDurationMs / 150 - 1,
      callback: () => {
        tinted = !tinted;
        if (tinted) {
          this.playerSprite.setTint(0xff2f2f);
        } else {
          this.playerSprite.clearTint();
        }
      },
    });
    this.stunEndEvent = this.time.delayedCall(
      GAME_CONFIG.crab.stunDurationMs,
      () => {
        this.stunEndEvent = undefined;
        this.clearPlayerStun(true);
      },
    );
  }

  private clearPlayerStun(resumeMovement: boolean): void {
    this.stunBlinkEvent?.destroy();
    this.stunBlinkEvent = undefined;
    this.stunEndEvent?.destroy();
    this.stunEndEvent = undefined;
    this.playerSprite?.clearTint();
    this.playerStunned = false;

    if (
      resumeMovement &&
      this.roundActive &&
      this.moving &&
      this.moveTween
    ) {
      this.moveTween.resume();
      this.playerSprite.anims.resume();
    }
  }

  private stopCrabEncounters(): void {
    this.crabEvents.forEach((event) => event.destroy());
    this.crabEvents = [];
    [...this.crabWarnings].forEach((warning) =>
      this.removeCrabWarning(warning),
    );
    this.pendingCrabSlots.clear();
    this.crabs.forEach((crab) => {
      crab.moveTween?.pause();
      crab.sprite.anims.pause();
    });
  }

  private createGrid(): void {
    this.gridGraphics = this.add.graphics().setDepth(2).setVisible(false);
    this.gridGraphics.lineStyle(2, 0xffffff, 0.5);

    for (let row = 0; row < ROWS; row += 1) {
      for (let column = 0; column < COLUMNS; column += 1) {
        const point = this.gridPoint(row, column);
        const nextColumn = this.gridPoint(row, Math.min(column + 1, COLUMNS - 1));
        const cellWidth = Math.abs(nextColumn.x - point.x) || 80;
        this.gridGraphics.strokeEllipse(point.x, point.y, cellWidth * 0.7, 24);
      }
    }
  }

  private createPlayer(): void {
    const point = this.gridPoint(this.playerPosition.row, this.playerPosition.column);
    this.playerShadow = this.add.ellipse(0, -4, 102, 21, 0x5b482c, 0.17);
    this.playerSprite = this.add
      .sprite(0, PLAYER_GROUND_OFFSET, "character", 2)
      .setOrigin(0.5, 1)
      .setScale(PLAYER_SPRITE_SCALE);
    this.playerSprite.on(
      Phaser.Animations.Events.ANIMATION_UPDATE,
      (
        _animation: Phaser.Animations.Animation,
        frame: Phaser.Animations.AnimationFrame,
      ) => this.cropWalkingFrame(Number(frame.textureFrame)),
    );
    this.player = this.add.container(point.x, point.y, [
      this.playerShadow,
      this.playerSprite,
    ]);
    this.applyPerspective(this.player, this.playerPosition.row);
    this.updateFacingFrame("idle");
    this.updatePlayerShadow();
    this.updateDepth(this.player);
  }

  private createUi(): void {
    const leftPanel = this.add.graphics().setDepth(10_000);
    leftPanel.fillStyle(0x063d5c, 0.88);
    leftPanel.fillRoundedRect(28, 24, 218, 112, 22);
    leftPanel.lineStyle(3, 0xffffff, 0.52);
    leftPanel.strokeRoundedRect(28, 24, 218, 112, 22);

    this.add
      .text(52, 39, "のこり時間", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "20px",
        fontStyle: "bold",
        color: "#bceeff",
      })
      .setDepth(10_001);
    this.timerText = this.add
      .text(52, 62, this.roundDurationSeconds(), {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "53px",
        fontStyle: "bold",
        color: "#ffffff",
        stroke: "#05324b",
        strokeThickness: 5,
      })
      .setDepth(10_001);
    this.add
      .text(168, 85, "秒", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "22px",
        fontStyle: "bold",
        color: "#ffffff",
      })
      .setDepth(10_001);

    const rightPanel = this.add.graphics().setDepth(10_000);
    rightPanel.fillStyle(0x063d5c, 0.9);
    rightPanel.fillRoundedRect(876, 24, 296, 178, 22);
    rightPanel.lineStyle(3, 0xffffff, 0.52);
    rightPanel.strokeRoundedRect(876, 24, 296, 178, 22);
    rightPanel.lineStyle(1, 0x8edff5, 0.25);
    rightPanel.lineBetween(898, 98, 1150, 98);

    this.add
      .text(900, 39, "SCORE", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "18px",
        fontStyle: "bold",
        color: "#85eaff",
      })
      .setDepth(10_001);
    this.scoreText = this.add
      .text(1145, 34, "0", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "48px",
        fontStyle: "bold",
        color: "#fff4a8",
        stroke: "#68410a",
        strokeThickness: 4,
      })
      .setOrigin(1, 0)
      .setDepth(10_001);

    this.add
      .text(900, 110, "きこえた言葉", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "15px",
        fontStyle: "bold",
        color: "#a9ddea",
      })
      .setDepth(10_001);
    this.commandText = this.add
      .text(1145, 103, "—", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "30px",
        fontStyle: "bold",
        color: "#ffffff",
      })
      .setOrigin(1, 0)
      .setDepth(10_001);

    this.microphoneDot = this.add.circle(909, 170, 7, 0xffb84d).setDepth(10_001);
    this.microphoneText = this.add
      .text(925, 157, "マイク：接続中", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "16px",
        fontStyle: "bold",
        color: "#d8f6ff",
      })
      .setDepth(10_001);
    this.countdownShade = this.add
      .rectangle(WIDTH / 2, HEIGHT / 2, WIDTH, HEIGHT, 0x06324b, 0.3)
      .setDepth(20_000);
    this.countdownText = this.add
      .text(WIDTH / 2, HEIGHT / 2, "3", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "180px",
        fontStyle: "bold",
        color: "#ffffff",
        stroke: "#075d79",
        strokeThickness: 15,
        shadow: {
          offsetX: 0,
          offsetY: 12,
          color: "#06324b",
          blur: 2,
          fill: true,
        },
      })
      .setOrigin(0.5)
      .setDepth(20_001);
  }

  private bindKeyboard(): void {
    const keyboard = this.input.keyboard;
    if (!keyboard) {
      return;
    }

    keyboard.on("keydown-UP", () => this.receiveCommand("すすめ"));
    keyboard.on("keydown-W", () => this.receiveCommand("すすめ"));
    keyboard.on("keydown-DOWN", () => this.receiveCommand("とまれ"));
    keyboard.on("keydown-S", () => this.receiveCommand("とまれ"));
    keyboard.on("keydown-LEFT", () => this.receiveCommand("ひだり"));
    keyboard.on("keydown-A", () => this.receiveCommand("ひだり"));
    keyboard.on("keydown-RIGHT", () => this.receiveCommand("みぎ"));
    keyboard.on("keydown-D", () => this.receiveCommand("みぎ"));
    keyboard.on("keydown-SPACE", () => {
      if (this.timeExpired && this.resultObjects.length > 0) {
        this.retrySameMode();
        return;
      }
      this.receiveCommand("たたけ");
    });
    keyboard.on("keydown-G", () => this.gridGraphics.setVisible(!this.gridGraphics.visible));
  }

  private startCountdown(): void {
    if (!this.waitingToStart) {
      return;
    }
    this.waitingToStart = false;
    this.tweens.killTweensOf(this.countdownText);
    this.countdownShade.setVisible(true);
    this.countdownText.setVisible(true);
    const labels = GAME_CONFIG.round.countdownLabels;
    labels.forEach((label, index) => {
      this.time.delayedCall(index * GAME_CONFIG.round.countdownStepMs, () => {
        this.countdownText.setText(label).setFontSize(label === "スタート！" ? 96 : 180);
        this.countdownText.setScale(0.65).setAlpha(1);
        this.tweens.add({
          targets: this.countdownText,
          scale: 1,
          alpha: label === "スタート！" ? 1 : 0.92,
          duration: 350,
          ease: "Back.Out",
        });
      });
    });

    this.time.delayedCall(
      labels.length * GAME_CONFIG.round.countdownStepMs,
      () => {
        this.countdownText.setVisible(false);
        this.countdownShade.setVisible(false);
        this.roundStartedAt = this.time.now;
        this.roundActive = true;
        this.timerText.setText(this.roundDurationSeconds()).setColor("#ffffff");
        this.scheduleCrabEncounters();
        this.showCommandGuide();
      },
    );
  }

  private showCommandGuide(): void {
    const commands = this.completeCustomCommands();
    if (this.gameMode !== "custom" || !commands) {
      return;
    }

    const firstLine = `みぎ → ${commands["みぎ"]}　　ひだり → ${commands["ひだり"]}`;
    const secondLine = `すすめ → ${commands["すすめ"]}　　とまれ → ${commands["とまれ"]}　　たたけ → ${commands["たたけ"]}`;
    this.commandGuide = this.add
      .text(WIDTH / 2, 24, `${firstLine}\n${secondLine}`, {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "20px",
        fontStyle: "bold",
        color: "#ffffff",
        backgroundColor: "rgba(6, 61, 92, 0.9)",
        padding: { x: 20, y: 12 },
        align: "center",
        lineSpacing: 6,
      })
      .setOrigin(0.5, 0)
      .setDepth(10_002);

    this.commandGuideEvent = this.time.delayedCall(
      GAME_CONFIG.customCommandGuide.visibleDurationMs,
      () => {
        if (!this.commandGuide) {
          return;
        }
        this.tweens.add({
          targets: this.commandGuide,
          alpha: 0.15,
          duration: 250,
          yoyo: true,
          repeat: 9,
          onComplete: () => {
            this.commandGuide?.destroy();
            this.commandGuide = undefined;
          },
        });
      },
    );
  }

  private receiveCommand(command: VoiceCommand, heardWord: string = command): void {
    this.commandText.setText(heardWord).setAlpha(1);
    this.tweens.killTweensOf(this.commandText);
    this.tweens.add({
      targets: this.commandText,
      alpha: 0.5,
      delay: 1_200,
      duration: 700,
    });

    if (
      !this.roundActive ||
      this.timeExpired ||
      this.striking ||
      this.playerStunned
    ) {
      return;
    }

    switch (command) {
      case "すすめ":
        this.pendingStrike = false;
        this.tryMove();
        break;
      case "とまれ":
        this.pendingStrike = false;
        break;
      case "みぎ":
        this.queueTurn(1);
        break;
      case "ひだり":
        this.queueTurn(-1);
        break;
      case "たたけ":
        this.pendingStrike = true;
        if (!this.moving) {
          this.beginStrike();
        }
        break;
    }
  }

  private queueTurn(amount: number): void {
    if (this.moving) {
      this.pendingTurns += amount;
      return;
    }
    this.turn(amount);
  }

  private turn(amount: number): void {
    this.direction = (this.direction + amount + 4) % 4;
    this.updateFacingFrame("idle");
    this.tweens.add({
      targets: this.playerSprite,
      angle: { from: amount > 0 ? -5 : 5, to: 0 },
      duration: 170,
      ease: "Back.Out",
    });
  }

  private tryMove(): void {
    if (
      this.moving ||
      this.striking ||
      this.playerStunned ||
      !this.roundActive ||
      this.timeExpired
    ) {
      return;
    }

    const target = this.positionAhead();
    if (!this.isInsideGrid(target) || this.fruitAt(target) !== undefined) {
      this.updateFacingFrame("idle");
      this.tweens.add({
        targets: this.player,
        x: this.player.x + (this.direction === Direction.East ? 5 : this.direction === Direction.West ? -5 : 0),
        y: this.player.y + (this.direction === Direction.South ? 4 : -4),
        duration: 90,
        yoyo: true,
        repeat: 1,
      });
      return;
    }

    this.moving = true;
    this.playWalkingAnimation();
    const point = this.gridPoint(target.row, target.column);
    const targetScale = this.rowScale(target.row);

    this.moveTween = this.tweens.add({
      targets: this.player,
      x: point.x,
      y: point.y,
      scaleX: targetScale,
      scaleY: targetScale,
      duration: GAME_CONFIG.player.moveDurationMs,
      ease: "Sine.InOut",
      onUpdate: () => this.updateDepth(this.player),
      onComplete: () => {
        this.playerPosition = target;
        this.moving = false;
        this.moveTween = undefined;
        this.updateDepth(this.player);
        this.updateFacingFrame("idle");

        if (this.pendingTurns !== 0) {
          const turnAmount = this.pendingTurns;
          this.pendingTurns = 0;
          this.turn(turnAmount);
        }

        if (this.pendingStrike) {
          this.pendingStrike = false;
          this.beginStrike();
          return;
        }

        if (this.timeExpired) {
          this.finishRound();
          return;
        }

      },
    });
  }

  private beginStrike(): void {
    if (
      this.striking ||
      this.moving ||
      this.playerStunned ||
      this.timeExpired ||
      !this.roundActive
    ) {
      return;
    }

    this.striking = true;
    this.pendingStrike = false;
    const strikePosition = this.positionAhead();
    const crabTarget = this.crabInStrikeRange(strikePosition);
    // 撃破を接触判定より先に確定し、同時に成立した場合は攻撃を優先する。
    if (crabTarget) {
      this.defeatCrab(crabTarget);
    }
    const target = crabTarget ? undefined : this.fruitAt(strikePosition);
    if (target) {
      target.breaking = true;
    }

    this.updateFacingFrame("strike");
    this.tweens.add({
      targets: this.playerSprite,
      scaleX: { from: 0.63, to: 0.61 },
      scaleY: { from: 0.59, to: 0.61 },
      duration: 250,
      ease: "Cubic.In",
      yoyo: true,
    });

    this.time.delayedCall(270, () => {
      if (!target) {
        return;
      }
      target.sprite.setFrame(target.golden ? 5 : 1);
      this.cameras.main.shake(90, 0.003);
      this.tweens.add({
        targets: target.container,
        angle: { from: -3, to: 3 },
        duration: 55,
        yoyo: true,
        repeat: 2,
      });
      this.addScore(target.golden ? 3 : 1, target.container.x, target.container.y - 85);
    });

    this.time.delayedCall(420, () => {
      if (target) {
        target.sprite.setFrame(target.golden ? 6 : 2);
      }
    });
    this.time.delayedCall(590, () => {
      if (target) {
        target.sprite.setFrame(target.golden ? 7 : 3);
      }
    });
    this.time.delayedCall(810, () => {
      this.striking = false;
      this.updateFacingFrame("idle");
      if (target) {
        this.removeFruit(target);
        if (!this.timeExpired) {
          this.spawnFruit();
        }
      }

      if (this.timeExpired) {
        this.finishRound();
      }
    });
  }

  private crabInStrikeRange(position: GridPosition): Crab | undefined {
    if (!this.isInsideGrid(position)) {
      return undefined;
    }
    const point = this.gridPoint(position.row, position.column);
    const perspective = this.rowScale(position.row);
    return this.crabs.find(
      (crab) =>
        !crab.defeated &&
        !crab.hasHitPlayer &&
        crab.row === position.row &&
        Math.abs(crab.container.x - point.x) <= 96 * perspective,
    );
  }

  private defeatCrab(crab: Crab): void {
    crab.defeated = true;
    crab.moveTween?.pause();
    crab.sprite.anims.pause();
    this.addScore(
      GAME_CONFIG.crab.score,
      crab.container.x,
      crab.container.y - 75 * this.rowScale(crab.row),
    );
    this.cameras.main.shake(90, 0.003);
    this.tweens.add({
      targets: crab.container,
      alpha: 0.18,
      duration: 100,
      yoyo: true,
      repeat: GAME_CONFIG.crab.defeatDurationMs / 200 - 1,
    });
    const event = this.time.delayedCall(
      GAME_CONFIG.crab.defeatDurationMs,
      () => this.removeCrab(crab, true),
    );
    this.crabEvents.push(event);
  }

  private addScore(points: number, x: number, y: number): void {
    this.score += points;
    this.scoreText.setText(String(this.score));
    this.scoreText.setScale(1.22);
    this.tweens.add({
      targets: this.scoreText,
      scale: 1,
      duration: 260,
      ease: "Back.Out",
    });

    const popup = this.add
      .text(x, y, `+${points}`, {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: points === 3 ? "44px" : "36px",
        fontStyle: "bold",
        color: points === 3 ? "#fff26d" : "#ffffff",
        stroke: points === 3 ? "#a85500" : "#0b6173",
        strokeThickness: 7,
      })
      .setOrigin(0.5)
      .setDepth(12_000);
    this.tweens.add({
      targets: popup,
      y: y - 55,
      alpha: 0,
      duration: 700,
      ease: "Cubic.Out",
      onComplete: () => popup.destroy(),
    });
  }

  private expireRound(): void {
    if (this.timeExpired) {
      return;
    }
    this.timeExpired = true;
    this.roundActive = false;
    this.pendingStrike = false;
    this.timerText.setText("00").setColor("#ff775f");
    this.stopCrabEncounters();
    this.clearPlayerStun(false);

    if (this.moving && this.moveTween) {
      this.moveTween.complete();
      return;
    }
    if (!this.striking) {
      this.finishRound();
    }
  }

  private finishRound(): void {
    if (this.resultObjects.length > 0) {
      return;
    }

    const shade = this.add
      .rectangle(WIDTH / 2, HEIGHT / 2, WIDTH, HEIGHT, 0x03263d, 0.62)
      .setDepth(30_000);
    const cardX = 210;
    const cardY = 215;
    const cardWidth = 780;
    const cardHeight = 480;
    const card = this.add.graphics().setDepth(30_001);
    card.fillStyle(0xfffbdf, 1);
    card.fillRoundedRect(cardX, cardY, cardWidth, cardHeight, 34);
    card.lineStyle(8, 0x28a8c2, 1);
    card.strokeRoundedRect(cardX, cardY, cardWidth, cardHeight, 34);

    const title = this.add
      .text(WIDTH / 2, 285, "タイムアップ！", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "49px",
        fontStyle: "bold",
        color: "#087a97",
      })
      .setOrigin(0.5)
      .setDepth(30_002);
    const label = this.add
      .text(WIDTH / 2, 370, "今回のスコア", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "24px",
        fontStyle: "bold",
        color: "#52646b",
      })
      .setOrigin(0.5)
      .setDepth(30_002);
    const score = this.add
      .text(WIDTH / 2, 460, String(this.score), {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "106px",
        fontStyle: "bold",
        color: "#ff8d35",
        stroke: "#a8461a",
        strokeThickness: 6,
      })
      .setOrigin(0.5)
      .setDepth(30_002);
    const unit = this.add
      .text(score.getBounds().right + 14, 466, "点", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "30px",
        fontStyle: "bold",
        color: "#a8461a",
      })
      .setDepth(30_002);
    const buttonY = 635;
    const buttonSpacing = this.gameMode === "custom" ? 220 : 250;
    const buttonStartX =
      WIDTH / 2 - (this.gameMode === "custom" ? buttonSpacing : buttonSpacing / 2);
    const createResultButton = (
      x: number,
      text: string,
      onClick: () => void,
    ): Phaser.GameObjects.DOMElement => {
      const element = document.createElement("button");
      element.type = "button";
      element.className = "result-action-button";
      element.textContent = text;
      const activate = (): void => {
        if (this.resultActionPending) {
          return;
        }
        this.resultActionPending = true;
        element.disabled = true;
        try {
          // Scene operations are already queued by Phaser for its next update.
          // Going through this Scene's clock first can strand the disabled button
          // if the finished round's clock no longer advances before the restart.
          onClick();
        } catch (error) {
          this.resultActionPending = false;
          element.disabled = false;
          throw error;
        }
      };
      element.addEventListener("click", activate);
      return this.add.dom(x, buttonY, element).setDepth(30_002);
    };
    const retry = createResultButton(buttonStartX, "もういちど", () => {
      this.retrySameMode();
    });
    const changeWords =
      this.gameMode === "custom"
        ? createResultButton(WIDTH / 2, "単語を変える", () => {
            this.changeCustomWords();
          })
        : undefined;
    const backX =
      this.gameMode === "custom" ? buttonStartX + buttonSpacing * 2 : buttonStartX + buttonSpacing;
    const back = createResultButton(backX, "もどる", () => {
      this.returnToModeSelection();
    });

    this.resultObjects = [
      shade,
      card,
      title,
      label,
      score,
      unit,
      retry,
      ...(changeWords ? [changeWords] : []),
      back,
    ];
    this.tweens.add({
      targets: [card, title, label, score, unit, retry, changeWords, back].filter(
        (object) => object !== undefined,
      ),
      scale: { from: 0.8, to: 1 },
      alpha: { from: 0, to: 1 },
      duration: 420,
      ease: "Back.Out",
    });
  }

  private spawnFruit(): void {
    const free: GridPosition[] = [];
    for (let row = 0; row < ROWS; row += 1) {
      for (let column = 0; column < COLUMNS; column += 1) {
        const position = { row, column };
        if (
          !this.samePosition(position, this.playerPosition) &&
          this.fruitAt(position) === undefined
        ) {
          free.push(position);
        }
      }
    }
    if (free.length === 0) {
      return;
    }

    const position = Phaser.Utils.Array.GetRandom(free);
    const golden = Math.random() < GAME_CONFIG.fruit.goldenChance;
    const point = this.gridPoint(position.row, position.column);
    const shadow = this.add.ellipse(0, -4, 88, 18, 0x4c3b25, 0.16);
    const sprite = this.add
      .sprite(0, 4, "watermelons", golden ? 4 : 0)
      .setOrigin(0.5, 1)
      .setScale(0.34);
    const container = this.add.container(point.x, point.y, [shadow, sprite]);
    this.applyPerspective(container, position.row);
    this.updateDepth(container);
    container.setScale(0);
    this.tweens.add({
      targets: container,
      scaleX: this.rowScale(position.row),
      scaleY: this.rowScale(position.row),
      duration: 330,
      ease: "Back.Out",
    });

    if (golden) {
      this.tweens.add({
        targets: sprite,
        alpha: 0.72,
        duration: 520,
        yoyo: true,
        repeat: -1,
      });
    }

    this.fruits.push({
      ...position,
      container,
      sprite,
      golden,
      breaking: false,
    });
  }

  private removeFruit(fruit: Fruit): void {
    this.fruits = this.fruits.filter((candidate) => candidate !== fruit);
    this.tweens.killTweensOf(fruit.sprite);
    this.tweens.add({
      targets: fruit.container,
      alpha: 0,
      scaleX: fruit.container.scaleX * 0.75,
      scaleY: fruit.container.scaleY * 0.75,
      duration: 180,
      onComplete: () => fruit.container.destroy(),
    });
  }

  private playWalkingAnimation(): void {
    const key =
      this.direction === Direction.North
        ? "back"
        : this.direction === Direction.South
          ? "front"
          : "side";
    this.playerSprite.setFlipX(this.direction === Direction.West);
    this.playerSprite.play(`walk-${key}`, true);
  }

  private updateFacingFrame(state: "idle" | "strike"): void {
    this.playerSprite.stop();
    this.playerSprite.setCrop();
    this.playerSprite.y = PLAYER_GROUND_OFFSET;
    const view =
      this.direction === Direction.North
        ? 2
        : this.direction === Direction.South
          ? 0
          : 1;
    this.playerSprite.setFrame(view + (state === "strike" ? 6 : 0));
    this.playerSprite.setFlipX(this.direction === Direction.West);
    this.playerSprite.setAngle(0);
    this.playerSprite.setScale(PLAYER_SPRITE_SCALE);
    this.updatePlayerShadow();
  }

  private cropWalkingFrame(frameIndex: number): void {
    if (frameIndex < 3 || frameIndex > 5) {
      this.playerSprite.setCrop();
      return;
    }

    // 生成画像では次の行のバット先端が歩行コマ下端へ数px入っている。
    this.playerSprite.setCrop(0, 0, 418, WALK_FRAME_SAFE_HEIGHT);
  }

  private updatePlayerShadow(): void {
    const sideView =
      this.direction === Direction.East || this.direction === Direction.West;
    this.playerShadow.setDisplaySize(sideView ? 76 : 102, 21);
  }

  private positionAhead(): GridPosition {
    const offsets: Record<Direction, GridPosition> = {
      [Direction.North]: { row: -1, column: 0 },
      [Direction.East]: { row: 0, column: 1 },
      [Direction.South]: { row: 1, column: 0 },
      [Direction.West]: { row: 0, column: -1 },
    };
    const offset = offsets[this.direction];
    return {
      row: this.playerPosition.row + offset.row,
      column: this.playerPosition.column + offset.column,
    };
  }

  private fruitAt(position: GridPosition): Fruit | undefined {
    return this.fruits.find(
      (fruit) => !fruit.breaking && this.samePosition(fruit, position),
    );
  }

  private samePosition(a: GridPosition, b: GridPosition): boolean {
    return a.row === b.row && a.column === b.column;
  }

  private isInsideGrid(position: GridPosition): boolean {
    return (
      position.row >= 0 &&
      position.row < ROWS &&
      position.column >= 0 &&
      position.column < COLUMNS
    );
  }

  private gridPoint(row: number, column: number): Phaser.Math.Vector2 {
    // 水際から手前まで砂浜全体を使う、緩やかな台形として配置する。
    const y = GRID_ROW_Y[row];
    const width = GRID_ROW_WIDTH[row];
    const x = WIDTH / 2 + (column - (COLUMNS - 1) / 2) * (width / COLUMNS);
    return new Phaser.Math.Vector2(x, y);
  }

  private rowScale(row: number): number {
    return 0.82 + row * 0.045;
  }

  private applyPerspective(
    object: Phaser.GameObjects.Container,
    row: number,
  ): void {
    object.setScale(this.rowScale(row));
  }

  private updateDepth(object: Phaser.GameObjects.Container): void {
    object.setDepth(100 + object.y);
  }

  private connectVoiceSocket(): void {
    if (this.destroyed) {
      return;
    }

    this.setMicrophoneState("connecting");
    const configuredUrl = import.meta.env.VITE_VOICE_WS_URL as string | undefined;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const developmentHost =
      window.location.port === "5173"
        ? `${window.location.hostname}:8000`
        : window.location.host;
    const url = configuredUrl || `${protocol}//${developmentHost}/ws/voice`;

    try {
      this.socket = new WebSocket(url);
    } catch {
      this.setMicrophoneState("error");
      this.scheduleReconnect();
      return;
    }

    const socket = this.socket;
    socket.addEventListener("open", () => {
      if (this.socket === socket) {
        this.sendVoiceConfiguration();
      }
    });
    socket.addEventListener("message", (event) => {
      if (this.socket !== socket) {
        return;
      }
      let message: VoiceMessage;
      try {
        message = JSON.parse(String(event.data)) as VoiceMessage;
      } catch {
        return;
      }
      if (message.type === "status") {
        this.setMicrophoneState(message.microphone);
      } else if (
        message.type === "command" &&
        COMMANDS.includes(message.command)
      ) {
        const heardWord =
          this.gameMode === "custom"
            ? this.customCommands[message.command] ?? message.raw
            : message.command;
        this.receiveCommand(message.command, heardWord);
      }
    });
    socket.addEventListener("close", () => {
      if (!this.destroyed && this.socket === socket) {
        this.socket = undefined;
        this.setMicrophoneState("disconnected");
        this.scheduleReconnect();
      }
    });
    socket.addEventListener("error", () => {
      if (this.socket === socket) {
        this.setMicrophoneState("error");
      }
    });
  }

  private completeCustomCommands(): CustomCommands | undefined {
    if (
      !COMMANDS.every(
        (command) => typeof this.customCommands[command] === "string",
      )
    ) {
      return undefined;
    }
    return { ...this.customCommands } as CustomCommands;
  }

  private sendVoiceConfiguration(): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN || !this.gameMode) {
      return;
    }
    const commands =
      this.gameMode === "custom" ? this.completeCustomCommands() : null;
    if (this.gameMode === "custom" && !commands) {
      return;
    }
    this.socket.send(JSON.stringify({ type: "configure", commands }));
  }

  private retrySameMode(): void {
    const mode = this.gameMode ?? "normal";
    this.scene.restart({
      autoStart: true,
      mode,
      customCommands: mode === "custom" ? this.customCommands : undefined,
    } satisfies SceneData);
  }

  private returnToModeSelection(): void {
    this.clearVoiceConfiguration();
    this.scene.start("title", { customSetup: false });
  }

  private changeCustomWords(): void {
    this.clearVoiceConfiguration();
    this.scene.start("title", { customSetup: true });
  }

  private clearVoiceConfiguration(): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      try {
        this.socket.send(JSON.stringify({ type: "configure", commands: null }));
      } catch {
        // Scene navigation must still work if the voice socket closes mid-click.
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectEvent || this.destroyed) {
      return;
    }
    this.reconnectEvent = this.time.delayedCall(
      GAME_CONFIG.voiceSocket.reconnectDelayMs,
      () => {
        this.reconnectEvent = undefined;
        this.connectVoiceSocket();
      },
    );
  }

  private setMicrophoneState(state: MicrophoneState): void {
    const labels: Record<MicrophoneState, string> = {
      connecting: "マイク：接続中",
      connected: "マイク：ON",
      error: "マイク：エラー",
      disconnected: "マイク：未接続",
    };
    const colors: Record<MicrophoneState, number> = {
      connecting: 0xffb84d,
      connected: 0x55e68b,
      error: 0xff654f,
      disconnected: 0xaab8be,
    };
    this.microphoneText?.setText(labels[state]);
    this.microphoneDot?.setFillStyle(colors[state]);
  }

  private roundDurationSeconds(): string {
    return String(Math.ceil(GAME_CONFIG.round.durationMs / 1_000)).padStart(
      2,
      "0",
    );
  }

  private shutdown(): void {
    this.destroyed = true;
    this.commandGuideEvent?.destroy();
    this.commandGuideEvent = undefined;
    if (this.commandGuide) {
      this.tweens.killTweensOf(this.commandGuide);
      this.commandGuide.destroy();
      this.commandGuide = undefined;
    }
    this.stopCrabEncounters();
    this.clearPlayerStun(false);
    this.reconnectEvent?.destroy();
    this.reconnectEvent = undefined;
    const socket = this.socket;
    this.socket = undefined;
    socket?.close();
    this.input.keyboard?.removeAllListeners();
  }

  private resetRoundState(): void {
    this.playerPosition = { row: 4, column: 3 };
    this.direction = Direction.North;
    this.fruits = [];
    this.crabs = [];
    this.crabSlotsEnabled = [];
    this.pendingCrabSlots = new Set<number>();
    this.crabEvents = [];
    this.crabWarnings = [];
    this.score = 0;
    this.roundStartedAt = 0;
    this.waitingToStart = true;
    this.roundActive = false;
    this.timeExpired = false;
    this.moving = false;
    this.striking = false;
    this.pendingStrike = false;
    this.pendingTurns = 0;
    this.playerStunned = false;
    this.moveTween = undefined;
    this.stunBlinkEvent = undefined;
    this.stunEndEvent = undefined;
    this.resultObjects = [];
    this.resultActionPending = false;
  }
}
