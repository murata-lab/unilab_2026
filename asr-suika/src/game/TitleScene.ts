import Phaser from "phaser";

import beachUrl from "../../assets/backgrounds/beach.png?url";
import {
  COMMANDS,
  COMMAND_SETUP_ORDER,
  type CustomCommands,
  type VoiceCommand,
} from "./config";

const WIDTH = 1200;
const HEIGHT = 900;
const CUSTOM_MODE_ENABLED = import.meta.env.VITE_ENABLE_CUSTOM_MODE === "true";
type TitlePhase = "mode" | "register" | "confirm";

export class TitleScene extends Phaser.Scene {
  private overlayObjects: Phaser.GameObjects.GameObject[] = [];
  private customCommands: Partial<CustomCommands> = {};
  private registrationIndex = 0;
  private phase: TitlePhase = "mode";

  constructor() {
    super("title");
  }

  preload(): void {
    this.load.image("title-beach", beachUrl);
  }

  create(data: { customSetup?: boolean } = {}): void {
    const commandHint = document.querySelector<HTMLElement>(".commands");
    if (commandHint) {
      commandHint.textContent = "モードを選んでゲームスタート";
    }
    this.add
      .image(WIDTH / 2, HEIGHT / 2, "title-beach")
      .setDisplaySize(WIDTH, HEIGHT);
    this.add.rectangle(WIDTH / 2, HEIGHT / 2, WIDTH, HEIGHT, 0x06324b, 0.38);

    this.input.keyboard?.on("keydown-SPACE", () => {
      if (this.phase === "confirm") {
        this.startCustomGame();
      }
    });
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.clearOverlay();
      this.input.keyboard?.removeAllListeners();
    });

    if (data.customSetup) {
      this.beginRegistration();
    } else {
      this.showModeSelection();
    }
  }

  private showModeSelection(): void {
    this.phase = "mode";
    this.customCommands = {};
    this.clearOverlay();

    const eyebrow = this.add
      .text(WIDTH / 2, 145, "VOICE CONTROLLED BEACH GAME", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "20px",
        fontStyle: "bold",
        color: "#85eaff",
        letterSpacing: 3,
      })
      .setOrigin(0.5);
    const title = this.add
      .text(WIDTH / 2, 245, "声でスイカ割り！", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "76px",
        fontStyle: "bold",
        color: "#ffffff",
        stroke: "#075d79",
        strokeThickness: 13,
      })
      .setOrigin(0.5);
    const subtitle = this.add
      .text(
        WIDTH / 2,
        350,
        CUSTOM_MODE_ENABLED
          ? "遊ぶモードをえらんでね"
          : "声でキャラクターを動かしてスイカを割ろう",
        {
          fontFamily: '"M PLUS Rounded 1c", sans-serif',
          fontSize: "31px",
          fontStyle: "bold",
          color: "#d5f5ff",
        },
      )
      .setOrigin(0.5);
    const normalX = CUSTOM_MODE_ENABLED ? 255 : 400;
    const hardX = CUSTOM_MODE_ENABLED ? 600 : 800;
    const normalButton = this.createButton(
      normalX,
      515,
      "通常モード",
      () => {
        this.scene.start("suika", { autoStart: true, mode: "normal" });
      },
    );
    const hardButton = this.createButton(hardX, 515, "Hardモード", () => {
      this.scene.start("suika", { autoStart: true, mode: "hard" });
    });
    const customButton = CUSTOM_MODE_ENABLED
      ? this.createButton(
          945,
          515,
          "単語変更モード",
          () => this.beginRegistration(),
        )
      : undefined;
    const normalHint = this.add
      .text(
        normalX,
        605,
        "いつもの5つの言葉で遊ぶ",
        {
          fontFamily: '"M PLUS Rounded 1c", sans-serif',
          fontSize: "20px",
          fontStyle: "bold",
          color: "#ffffff",
        },
      )
      .setOrigin(0.5);
    const hardHint = this.add
      .text(hardX, 605, "カニが最大4体・高頻度", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "20px",
        fontStyle: "bold",
        color: "#fff4a8",
      })
      .setOrigin(0.5);
    const customHint = CUSTOM_MODE_ENABLED
      ? this.add
          .text(945, 605, "5つの言葉を自分で決める", {
            fontFamily: '"M PLUS Rounded 1c", sans-serif',
            fontSize: "20px",
            fontStyle: "bold",
            color: "#ffffff",
          })
          .setOrigin(0.5)
      : undefined;
    this.overlayObjects.push(
      eyebrow,
      title,
      subtitle,
      normalButton,
      hardButton,
      normalHint,
      hardHint,
      ...(customButton ? [customButton] : []),
      ...(customHint ? [customHint] : []),
    );
  }

  private beginRegistration(): void {
    this.customCommands = {};
    this.registrationIndex = 0;
    this.showRegistrationStep();
  }

  private showRegistrationStep(errorMessage = ""): void {
    this.phase = "register";
    this.clearOverlay();

    const command = COMMAND_SETUP_ORDER[this.registrationIndex];
    const title = this.add
      .text(WIDTH / 2, 155, "言葉を登録しよう", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "55px",
        fontStyle: "bold",
        color: "#ffffff",
        stroke: "#075d79",
        strokeThickness: 10,
      })
      .setOrigin(0.5);
    const progress = this.add
      .text(
        WIDTH / 2,
        240,
        `${this.registrationIndex + 1} / ${COMMAND_SETUP_ORDER.length}`,
        {
          fontFamily: '"M PLUS Rounded 1c", sans-serif',
          fontSize: "24px",
          fontStyle: "bold",
          color: "#bceeff",
        },
      )
      .setOrigin(0.5);
    const prompt = this.add
      .text(WIDTH / 2, 350, `${command}  →`, {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "58px",
        fontStyle: "bold",
        color: "#fff4a8",
        stroke: "#68410a",
        strokeThickness: 7,
      })
      .setOrigin(0.5);

    const input = document.createElement("input");
    input.className = "command-word-input";
    input.type = "text";
    input.placeholder = "ひらがなを入力";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("aria-label", `${command}に割り当てる言葉`);
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing) {
        return;
      }
      event.preventDefault();
      this.registerCurrentWord(input.value);
    });
    const inputObject = this.add.dom(WIDTH / 2, 470, input);
    const rule = this.add
      .text(WIDTH / 2, 555, "空白なしのひらがなを入力して Enter", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "24px",
        fontStyle: "bold",
        color: "#d5f5ff",
      })
      .setOrigin(0.5);
    const error = this.add
      .text(WIDTH / 2, 610, errorMessage, {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "24px",
        fontStyle: "bold",
        color: "#ffcf70",
      })
      .setOrigin(0.5);
    const registered = this.add
      .text(WIDTH / 2, 700, this.registrationSummary(), {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "22px",
        fontStyle: "bold",
        color: "#ffffff",
        align: "center",
      })
      .setOrigin(0.5);
    const backButton = this.createButton(105, 70, "もどる", () => {
      this.showModeSelection();
    }, 20);

    this.overlayObjects.push(
      title,
      progress,
      prompt,
      inputObject,
      rule,
      error,
      registered,
      backButton,
    );
    this.time.delayedCall(0, () => input.focus());
  }

  private registerCurrentWord(value: string): void {
    if (!/^[ぁ-ゖー]+$/u.test(value)) {
      this.showRegistrationStep("空白なしのひらがなだけで入力してね");
      return;
    }
    if (Object.values(this.customCommands).includes(value)) {
      this.showRegistrationStep("その言葉はすでに登録されています");
      return;
    }

    const command = COMMAND_SETUP_ORDER[this.registrationIndex];
    this.customCommands[command] = value;
    this.registrationIndex += 1;
    if (this.registrationIndex < COMMAND_SETUP_ORDER.length) {
      this.showRegistrationStep();
      return;
    }
    this.showConfirmation();
  }

  private showConfirmation(): void {
    this.phase = "confirm";
    this.clearOverlay();

    const title = this.add
      .text(WIDTH / 2, 145, "この言葉で遊ぶよ", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "55px",
        fontStyle: "bold",
        color: "#ffffff",
        stroke: "#075d79",
        strokeThickness: 10,
      })
      .setOrigin(0.5);
    const mapping = this.add
      .text(WIDTH / 2, 390, this.registrationSummary(true), {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "34px",
        fontStyle: "bold",
        color: "#fff4a8",
        stroke: "#68410a",
        strokeThickness: 4,
        align: "left",
        lineSpacing: 11,
      })
      .setOrigin(0.5);
    const retryButton = this.createButton(
      455,
      655,
      "登録しなおす",
      () => this.beginRegistration(),
      24,
    );
    const startButton = this.createButton(
      745,
      655,
      "ゲームをはじめる",
      () => this.startCustomGame(),
      24,
    );
    const hint = this.add
      .text(WIDTH / 2, 755, "SPACE キーでもスタートできます", {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: "23px",
        fontStyle: "bold",
        color: "#d5f5ff",
      })
      .setOrigin(0.5);
    this.overlayObjects.push(title, mapping, retryButton, startButton, hint);
  }

  private startCustomGame(): void {
    const commands = this.completeCustomCommands();
    if (!commands) {
      return;
    }
    this.scene.start("suika", {
      autoStart: true,
      mode: "custom",
      customCommands: commands,
    });
  }

  private completeCustomCommands(): CustomCommands | undefined {
    if (!COMMANDS.every((command) => this.customCommands[command])) {
      return undefined;
    }
    return { ...this.customCommands } as CustomCommands;
  }

  private registrationSummary(multiline = false): string {
    return COMMAND_SETUP_ORDER.filter(
      (command) => this.customCommands[command] !== undefined,
    )
      .map((command) => `${command} → ${this.customCommands[command]}`)
      .join(multiline ? "\n" : "　");
  }

  private createButton(
    x: number,
    y: number,
    label: string,
    onClick: () => void,
    fontSize = 29,
  ): Phaser.GameObjects.Text {
    const button = this.add
      .text(x, y, label, {
        fontFamily: '"M PLUS Rounded 1c", sans-serif',
        fontSize: `${fontSize}px`,
        fontStyle: "bold",
        color: "#063d5c",
        backgroundColor: "#fff9cf",
        padding: { x: 28, y: 18 },
      })
      .setOrigin(0.5)
      .setInteractive({ useHandCursor: true });
    button.on("pointerover", () => button.setBackgroundColor("#ffe27a"));
    button.on("pointerout", () => button.setBackgroundColor("#fff9cf"));
    button.on("pointerdown", onClick);
    return button;
  }

  private clearOverlay(): void {
    this.overlayObjects.forEach((object) => object.destroy());
    this.overlayObjects = [];
  }
}
