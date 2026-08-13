import Phaser from "phaser";

import { SuikaScene } from "./game/SuikaScene";
import { TitleScene } from "./game/TitleScene";
import "./style.css";

const config: Phaser.Types.Core.GameConfig = {
  type: Phaser.AUTO,
  parent: "game",
  width: 1200,
  height: 900,
  backgroundColor: "#7ddaf0",
  antialias: true,
  transparent: false,
  scene: [TitleScene, SuikaScene],
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
    fullscreenTarget: "game",
  },
  render: {
    pixelArt: false,
    roundPixels: false,
  },
  dom: {
    createContainer: true,
  },
};

const game = new Phaser.Game(config);
const fullscreenButton = document.querySelector<HTMLButtonElement>(
  "#fullscreen-toggle",
);

function updateFullscreenButton(): void {
  if (fullscreenButton) {
    fullscreenButton.firstChild!.textContent = game.scale.isFullscreen
      ? "全画面を終了 "
      : "全画面 ";
  }
}

fullscreenButton?.addEventListener("click", () => game.scale.toggleFullscreen());
window.addEventListener("keydown", (event) => {
  if (event.code === "KeyF" && !event.repeat) {
    game.scale.toggleFullscreen();
  }
});
game.scale.on(Phaser.Scale.Events.ENTER_FULLSCREEN, updateFullscreenButton);
game.scale.on(Phaser.Scale.Events.LEAVE_FULLSCREEN, updateFullscreenButton);
