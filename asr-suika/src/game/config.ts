export const GAME_CONFIG = {
  round: {
    durationMs: 60_000,
    timerWarningMs: 10_000,
    countdownLabels: ["3", "2", "1", "スタート！"],
    countdownStepMs: 850,
  },
  player: {
    moveDurationMs: 1_000,
  },
  fruit: {
    initialCount: 3,
    goldenChance: 0.1,
  },
  crab: {
    maxCount: 4,
    warningDurationMs: 1_000,
    respawnMinMs: 2_000,
    respawnMaxMs: 5_000,
    hardRespawnMinMs: 1_000,
    hardRespawnMaxMs: 2_000,
    stunDurationMs: 3_000,
    defeatDurationMs: 1_000,
    score: 2,
    // 警告開始時刻。warningDurationMs 後にカニが出現する。
    normalSlotWarningTimesMs: [9_000, 29_000],
    // Hardの先頭2枠は即時出現。残り2枠は30秒時点の出現に向けて警告する。
    hardSlotWarningTimesMs: [0, 0, 29_000, 29_000],
  },
  customCommandGuide: {
    visibleDurationMs: 15_000,
  },
  voiceSocket: {
    reconnectDelayMs: 3_000,
  },
} as const;

export const COMMANDS = ["すすめ", "とまれ", "みぎ", "ひだり", "たたけ"] as const;
export const COMMAND_SETUP_ORDER = ["みぎ", "ひだり", "すすめ", "とまれ", "たたけ"] as const;

export type VoiceCommand = (typeof COMMANDS)[number];
export type CustomCommands = Record<VoiceCommand, string>;
