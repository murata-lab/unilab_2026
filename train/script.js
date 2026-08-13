const totalDistanceMeters = 180;
const targetMeters = 150;
const maxSpeedMps = 26.4;
const accelerationPerSecond = 6.7;
const brakePerSecond = 9.4;
const controlDeadZone = 0.08;
const requiredVisibility = 0.45;
const landmarkMargin = 0.04;

// ===== Score settings =====
// Final score = distance score * SCORE_DISTANCE_WEIGHT + time score * SCORE_TIME_WEIGHT.
// Example: 0.7 and 0.3 means distance 70%, time 30%.
const SCORE_DISTANCE_WEIGHT = 0.7;
const SCORE_TIME_WEIGHT = 0.3;

// Short stops use an exponential curve, so small misses are penalized clearly.
const SCORE_SHORT_DECAY_RATE = 0.64;

// Overshoot score uses a steeper exponential curve up to the soft limit,
// then falls sharply to 0 at the max overshoot error.
const SCORE_OVERSHOOT_DECAY_RATE = 0.8;
const SCORE_OVERSHOOT_SOFT_LIMIT_METERS = 0.6;
const SCORE_MAX_OVERSHOOT_ERROR_METERS = 1.8;

// Time score stays perfect up to the best time, then settles at the minimum score.
const SCORE_BEST_ELAPSED_SECONDS = 9.5;
const SCORE_MAX_ELAPSED_SECONDS = 15;
const SCORE_MIN_TIME_SCORE = 1 / 3;

const TRACK_VIEW_BEFORE_TARGET_METERS = 4;
const TRACK_VIEW_OVERSHOOT_METERS = SCORE_MAX_OVERSHOOT_ERROR_METERS;
const TRACK_VIEW_TOTAL_METERS = TRACK_VIEW_BEFORE_TARGET_METERS + TRACK_VIEW_OVERSHOOT_METERS;
const TRACK_MARKER_MIN_PROGRESS = 0.12;
const TRACK_MARKER_MAX_PROGRESS = 0.88;

const elements = {
  distanceLeft: document.querySelector("#distanceLeft"),
  marker: document.querySelector("#trainMarker"),
  speed: document.querySelector("#speedValue"),
  speedBlocks: [...document.querySelectorAll("#speedBlocks span")],
  elapsedTime: document.querySelector("#elapsedTime"),
  actionBubble: document.querySelector("#actionBubble"),
  cameraArea: document.querySelector(".camera-safe-area"),
  video: document.querySelector("#cameraFeed"),
  canvas: document.querySelector("#poseCanvas"),
  cameraStatus: document.querySelector("#cameraStatus"),
  scoreOverlay: document.querySelector("#scoreOverlay"),
  scoreValue: document.querySelector("#scoreValue"),
  scoreDistance: document.querySelector("#scoreDistance"),
  scoreElapsed: document.querySelector("#scoreElapsed"),
};

const ctx = elements.canvas.getContext("2d");
const targetTrackProgress = scaleTrackProgress(TRACK_VIEW_BEFORE_TARGET_METERS / TRACK_VIEW_TOTAL_METERS) * 100;
document.documentElement.style.setProperty("--track-progress-min", `${TRACK_MARKER_MIN_PROGRESS * 100}%`);
document.documentElement.style.setProperty("--track-progress-max", `${TRACK_MARKER_MAX_PROGRESS * 100}%`);
document.documentElement.style.setProperty("--target-progress", `${targetTrackProgress}%`);

let positionMeters = 0;
let speedMps = 0;
let previousSpeedMps = 0;
let lastPhysicsTime = performance.now();
let poseLandmarker;
let lastVideoTime = -1;
let latestControl = 0;
let demoTargetControl = 0.7;
let nextDemoChangeTime = 0;
let backendSocket = null;
let backendConnected = false;
let lastControlSentAt = 0;
let backendControlSource = null;
let cameraControlsStarted = false;
let cameraStartupTimer = null;
let latestDistanceToTargetMm = null;
let latestElapsedSeconds = 0;

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function scaleTrackProgress(progress) {
  const safeProgress = clamp(progress, 0, 1);
  return TRACK_MARKER_MIN_PROGRESS + safeProgress * (TRACK_MARKER_MAX_PROGRESS - TRACK_MARKER_MIN_PROGRESS);
}

function toFiniteNumber(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatDistanceMm(distanceMm) {
  if (distanceMm === null || distanceMm === undefined || Number.isNaN(Number(distanceMm))) {
    return null;
  }

  const roundedMm = Math.round(Number(distanceMm));
  if (roundedMm < 0) {
    return `${Math.abs(roundedMm)}mm オーバー`;
  }
  return `あと ${roundedMm}mm`;
}

function setStatusText(nextSpeedMps, lastSpeedMps, control) {
  const isAccelerating = nextSpeedMps > lastSpeedMps + 0.03;
  const isStopped = nextSpeedMps < 0.15;

  if (isStopped) {
    elements.actionBubble.textContent = "停止!";
    elements.actionBubble.className = "action-bubble is-stopped";
    return;
  }

  if (control > controlDeadZone || isAccelerating) {
    elements.actionBubble.textContent = "加速中!";
    elements.actionBubble.className = "action-bubble is-accelerating";
    return;
  }

  if (control < -controlDeadZone || nextSpeedMps < lastSpeedMps - 0.03) {
    elements.actionBubble.textContent = "減速中!";
    elements.actionBubble.className = "action-bubble is-decelerating";
    return;
  }

  elements.actionBubble.textContent = "キープ!";
  elements.actionBubble.className = "action-bubble is-keeping";
}

function formatMeters(value) {
  return `${Number(value).toFixed(2)} m`;
}

function formatScoreDistanceMm(distanceMm) {
  if (distanceMm === null || distanceMm === undefined || Number.isNaN(Number(distanceMm))) {
    return "未受信";
  }

  const roundedMm = Math.round(Number(distanceMm));
  const distanceText = formatMeters(Math.abs(roundedMm) / 1000);
  if (roundedMm === 0) {
    return distanceText;
  }

  if (roundedMm < 0) {
    return `${distanceText} オーバー`;
  }
  return `${distanceText} 手前`;
}

function formatElapsedSeconds(elapsedSeconds) {
  const safeSeconds = Math.max(0, Math.floor(Number(elapsedSeconds) || 0));
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function calculateDistanceScore(distanceMeters, isOvershoot) {
  if (!isOvershoot) {
    return clamp(Math.exp(-SCORE_SHORT_DECAY_RATE * distanceMeters), 0, 1);
  }

  if (distanceMeters <= SCORE_OVERSHOOT_SOFT_LIMIT_METERS) {
    return clamp(Math.exp(-SCORE_OVERSHOOT_DECAY_RATE * distanceMeters), 0, 1);
  }

  const softLimitScore = Math.exp(-SCORE_OVERSHOOT_DECAY_RATE * SCORE_OVERSHOOT_SOFT_LIMIT_METERS);
  const hardPenaltyProgress = clamp(
    (distanceMeters - SCORE_OVERSHOOT_SOFT_LIMIT_METERS) /
      (SCORE_MAX_OVERSHOOT_ERROR_METERS - SCORE_OVERSHOOT_SOFT_LIMIT_METERS),
    0,
    1,
  );

  return clamp(softLimitScore * (1 - hardPenaltyProgress) ** 2, 0, 1);
}

function calculateTimeScore(elapsedSeconds) {
  if (elapsedSeconds <= SCORE_BEST_ELAPSED_SECONDS) {
    return 1;
  }

  const timeScoreProgress = clamp(
    1 -
      (elapsedSeconds - SCORE_BEST_ELAPSED_SECONDS) /
        (SCORE_MAX_ELAPSED_SECONDS - SCORE_BEST_ELAPSED_SECONDS),
    0,
    1,
  );

  return SCORE_MIN_TIME_SCORE + (1 - SCORE_MIN_TIME_SCORE) * timeScoreProgress;
}

function calculateScore(distanceToTargetMm, elapsedSeconds) {
  const hasDistance = distanceToTargetMm !== null && distanceToTargetMm !== undefined;
  const signedDistanceMm = hasDistance ? Number(distanceToTargetMm) || 0 : 0;
  const distanceMeters = hasDistance ? Math.abs(signedDistanceMm) / 1000 : null;
  const isOvershoot = signedDistanceMm < 0;
  const safeElapsedSeconds = Math.max(0, Number(elapsedSeconds) || 0);
  const distanceScore = hasDistance ? calculateDistanceScore(distanceMeters, isOvershoot) : 0;
  const timeScore = calculateTimeScore(safeElapsedSeconds);
  const weightedScore = distanceScore * SCORE_DISTANCE_WEIGHT + timeScore * SCORE_TIME_WEIGHT;

  return {
    score: Math.round(clamp(weightedScore * 100, 0, 100)),
    hasDistance,
    distanceMeters,
    elapsedSeconds: safeElapsedSeconds,
  };
}

function calculateTrackProgress(position, distanceToTargetMm) {
  const distanceNumber = toFiniteNumber(distanceToTargetMm);
  if (distanceNumber !== null) {
    const distanceMeters = distanceNumber / 1000;
    return scaleTrackProgress((TRACK_VIEW_BEFORE_TARGET_METERS - distanceMeters) / TRACK_VIEW_TOTAL_METERS);
  }

  return scaleTrackProgress(position / totalDistanceMeters);
}

function showScore() {
  const result = calculateScore(latestDistanceToTargetMm, latestElapsedSeconds);
  elements.scoreValue.textContent = String(result.score);
  elements.scoreDistance.textContent = formatScoreDistanceMm(latestDistanceToTargetMm);
  elements.scoreElapsed.textContent = `${result.elapsedSeconds.toFixed(1)} s`;
  elements.scoreOverlay.hidden = false;
}

function hideScore() {
  elements.scoreOverlay.hidden = true;
}

function updateTrainUI({
  positionMeters: nextPositionMeters,
  speedMps: nextSpeedMps,
  control = 0,
  distanceToTargetMm,
  elapsedSeconds,
}) {
  const distanceNumber = toFiniteNumber(distanceToTargetMm);
  const receivedPosition = toFiniteNumber(nextPositionMeters);
  const fallbackPosition =
    distanceNumber !== null ? targetMeters - distanceNumber / 1000 : positionMeters;
  const position = clamp(receivedPosition ?? fallbackPosition, 0, totalDistanceMeters);
  const rawSpeedMps = nextSpeedMps ?? 0;
  const speed = clamp(rawSpeedMps, 0, maxSpeedMps);
  const progress = calculateTrackProgress(position, distanceNumber);

  elements.distanceLeft.textContent = formatDistanceMm(distanceToTargetMm) ?? "未受信";
  elements.speed.textContent = `${speed.toFixed(1)}`;
  const activeBlocks = Math.round((speed / maxSpeedMps) * elements.speedBlocks.length);
  elements.speedBlocks.forEach((block, index) => {
    block.classList.toggle("is-active", index < activeBlocks);
  });
  setStatusText(speed, previousSpeedMps, control);

  elements.marker.style.bottom = `${progress * 100}%`;
  elements.marker.style.left = "50%";

  if (distanceNumber !== null) {
    latestDistanceToTargetMm = distanceNumber;
  }

  if (elapsedSeconds !== null && elapsedSeconds !== undefined) {
    latestElapsedSeconds = Number(elapsedSeconds) || 0;
    elements.elapsedTime.textContent = formatElapsedSeconds(latestElapsedSeconds);
  }

  previousSpeedMps = speed;
  positionMeters = position;
  speedMps = speed;
}

function stopCameraStream() {
  const stream = elements.video.srcObject;
  if (!stream) {
    return;
  }

  for (const track of stream.getTracks()) {
    track.stop();
  }
  elements.video.srcObject = null;
}

function enterPseudoMode() {
  if (backendControlSource === "pseudo") {
    return;
  }

  backendControlSource = "pseudo";
  if (cameraStartupTimer) {
    window.clearTimeout(cameraStartupTimer);
    cameraStartupTimer = null;
  }

  stopCameraStream();
  resizeCanvas();
  ctx.clearRect(0, 0, elements.canvas.width, elements.canvas.height);
  elements.cameraArea.classList.add("is-demo");
  elements.cameraStatus.textContent = "擬似信号デモ中";
}

function maybeStartPoseControls() {
  if (cameraControlsStarted || backendControlSource === "pseudo") {
    return;
  }

  cameraControlsStarted = true;
  startPoseControls();
}

function connectBackend() {
  if (window.location.protocol === "file:") {
    return;
  }

  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);
  backendSocket = socket;

  socket.addEventListener("open", () => {
    backendConnected = true;
  });

  socket.addEventListener("message", (event) => {
    const data = JSON.parse(event.data);
    if (data.type !== "state") {
      return;
    }

    if (data.controlSource === "pseudo") {
      enterPseudoMode();
    } else {
      backendControlSource = data.controlSource ?? "websocket";
      maybeStartPoseControls();
    }

    updateTrainUI({
      positionMeters: data.positionMeters,
      speedMps: data.speedMps,
      control: data.control,
      distanceToTargetMm: data.distanceToTargetMm,
      elapsedSeconds: data.elapsedSeconds,
    });
  });

  socket.addEventListener("close", () => {
    backendConnected = false;
    if (backendSocket === socket) {
      window.setTimeout(connectBackend, 1000);
    }
  });

  socket.addEventListener("error", () => {
    backendConnected = false;
  });
}

function sendControlToBackend(control, now) {
  if (!backendConnected || backendSocket?.readyState !== WebSocket.OPEN) {
    return false;
  }

  if (now - lastControlSentAt < 50) {
    return true;
  }

  backendSocket.send(JSON.stringify({ type: "control", control }));
  lastControlSentAt = now;
  return true;
}

function sendBackendMessage(message) {
  if (!backendConnected || backendSocket?.readyState !== WebSocket.OPEN) {
    return false;
  }

  backendSocket.send(JSON.stringify(message));
  return true;
}

function resetRun() {
  positionMeters = 0;
  speedMps = 0;
  previousSpeedMps = 0;
  latestControl = 0;
  demoTargetControl = 0.7;
  nextDemoChangeTime = 0;
  latestDistanceToTargetMm = null;
  latestElapsedSeconds = 0;
  lastPhysicsTime = performance.now();
  hideScore();
  elements.elapsedTime.textContent = "00:00";

  updateTrainUI({ positionMeters, speedMps, control: 0 });
  sendBackendMessage({ type: "reset" });
}

window.addEventListener("keydown", (event) => {
  if (event.repeat) {
    return;
  }

  const key = event.key.toLowerCase();
  if (key === "r") {
    resetRun();
  } else if (key === "t") {
    showScore();
  }
});

function landmarkVisible(landmark) {
  return Boolean(landmark) && (landmark.visibility === undefined || landmark.visibility >= requiredVisibility);
}

function landmarkInsideFrame(landmark) {
  return (
    landmark.x >= landmarkMargin &&
    landmark.x <= 1 - landmarkMargin &&
    landmark.y >= landmarkMargin &&
    landmark.y <= 1 - landmarkMargin
  );
}

function landmarkDistance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function calculateAccordionControl(landmarks) {
  const leftShoulder = landmarks[11];
  const rightShoulder = landmarks[12];
  const leftWrist = landmarks[15];
  const rightWrist = landmarks[16];

  const requiredLandmarks = [leftShoulder, rightShoulder, leftWrist, rightWrist];

  if (!requiredLandmarks.every(landmarkVisible)) {
    return null;
  }

  if (![leftWrist, rightWrist].every(landmarkInsideFrame)) {
    return null;
  }

  const shoulderWidth = landmarkDistance(leftShoulder, rightShoulder);
  const handSpan = landmarkDistance(leftWrist, rightWrist);

  if (shoulderWidth < 0.04) {
    return null;
  }

  const rawControl = (handSpan - shoulderWidth) / shoulderWidth;
  if (Math.abs(rawControl) < controlDeadZone) {
    return 0;
  }

  return clamp(rawControl, -1, 1);
}

function updatePhysics(control, now) {
  const deltaSeconds = Math.min((now - lastPhysicsTime) / 1000, 0.08);
  lastPhysicsTime = now;

  if (control > 0) {
    speedMps += control * accelerationPerSecond * deltaSeconds;
  } else if (control < 0) {
    speedMps += control * brakePerSecond * deltaSeconds;
  } else {
    speedMps -= 1.4 * deltaSeconds;
  }

  speedMps = clamp(speedMps, 0, maxSpeedMps);
  positionMeters = clamp(positionMeters + speedMps * deltaSeconds, 0, totalDistanceMeters);
  updateTrainUI({ positionMeters, speedMps, control });
}

function resizeCanvas() {
  const rect = elements.canvas.getBoundingClientRect();
  const width = Math.max(1, Math.round(rect.width));
  const height = Math.max(1, Math.round(rect.height));

  if (elements.canvas.width !== width || elements.canvas.height !== height) {
    elements.canvas.width = width;
    elements.canvas.height = height;
  }
}

function drawPose(landmarks, control) {
  resizeCanvas();
  ctx.clearRect(0, 0, elements.canvas.width, elements.canvas.height);

  if (!landmarks) {
    return;
  }

  const keyPoints = [11, 12, 15, 16].map((index) => {
    const point = landmarks[index];
    return {
      x: (1 - point.x) * elements.canvas.width,
      y: point.y * elements.canvas.height,
    };
  });
  const [leftShoulder, rightShoulder, leftWrist, rightWrist] = keyPoints;
  const color = control >= 0 ? "#4cc9f0" : "#ff6b63";

  ctx.lineWidth = 8;
  ctx.lineCap = "round";
  ctx.strokeStyle = "rgba(255, 255, 255, 0.72)";
  ctx.beginPath();
  ctx.moveTo(leftShoulder.x, leftShoulder.y);
  ctx.lineTo(rightShoulder.x, rightShoulder.y);
  ctx.stroke();

  ctx.strokeStyle = color;
  ctx.beginPath();
  ctx.moveTo(leftWrist.x, leftWrist.y);
  ctx.lineTo(rightWrist.x, rightWrist.y);
  ctx.stroke();

  ctx.fillStyle = color;
  for (const point of keyPoints) {
    ctx.beginPath();
    ctx.arc(point.x, point.y, 10, 0, Math.PI * 2);
    ctx.fill();
  }
}

function updateCameraStatus(control) {
  if (control === null) {
    elements.cameraStatus.textContent = "両手をカメラ内に入れてください";
    return;
  }

  if (control > controlDeadZone) {
    elements.cameraStatus.textContent = "手を肩幅より広げる: アクセル";
    return;
  }

  if (control < -controlDeadZone) {
    elements.cameraStatus.textContent = "手を肩幅より狭める: ブレーキ";
    return;
  }

  elements.cameraStatus.textContent = "肩幅くらい: キープ";
}

function predictWebcam(now) {

  if (elements.video.currentTime !== lastVideoTime) {
    const result = poseLandmarker.detectForVideo(elements.video, now);
    const landmarks = result.landmarks?.[0];
    const control = landmarks ? calculateAccordionControl(landmarks) : null;

    latestControl = control ?? -0.15;
    drawPose(landmarks, latestControl);
    updateCameraStatus(control);
    lastVideoTime = elements.video.currentTime;
  }

  if (!sendControlToBackend(latestControl, now)) {
    updatePhysics(latestControl, now);
  }
  window.requestAnimationFrame(predictWebcam);
}

async function startCamera() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: {
      width: { ideal: 1280 },
      height: { ideal: 720 },
      facingMode: "user",
    },
    audio: false,
  });

  elements.video.srcObject = stream;
  await elements.video.play();
}

async function startPoseControls() {
  try {
    elements.cameraArea.classList.remove("is-demo");
    elements.cameraStatus.textContent = "カメラ許可を待っています...";
    await startCamera();

    elements.cameraStatus.textContent = "AIモデル読み込み中...";
    const { FilesetResolver, PoseLandmarker } = await import("./assets/mediapipe/vision_bundle.mjs");
    const vision = await FilesetResolver.forVisionTasks("./assets/mediapipe/wasm");
    poseLandmarker = await createPoseLandmarker(PoseLandmarker, vision);

    elements.cameraStatus.textContent = "両手をカメラ内に入れてください";
    lastPhysicsTime = performance.now();
    window.requestAnimationFrame(predictWebcam);
  } catch (error) {
    console.error(error);
    elements.cameraStatus.textContent = getStartupErrorMessage(error);
  }
}

async function createPoseLandmarker(PoseLandmarker, vision) {
  const options = {
    baseOptions: {
      modelAssetPath: "./assets/mediapipe/pose_landmarker_lite.task",
      delegate: "GPU",
    },
    runningMode: "VIDEO",
    numPoses: 1,
    minPoseDetectionConfidence: 0.5,
    minPosePresenceConfidence: 0.5,
    minTrackingConfidence: 0.5,
  };

  try {
    return await PoseLandmarker.createFromOptions(vision, options);
  } catch (error) {
    console.warn("GPU delegate failed. Retrying PoseLandmarker with CPU.", error);
    return PoseLandmarker.createFromOptions(vision, {
      ...options,
      baseOptions: {
        ...options.baseOptions,
        delegate: "CPU",
      },
    });
  }
}

function getStartupErrorMessage(error) {
  if (error?.name === "NotAllowedError") {
    return "カメラが許可されていません。ブラウザのカメラ許可をオンにしてください";
  }

  if (error?.name === "NotFoundError") {
    return "カメラが見つかりません。接続を確認してください";
  }

  if (!navigator.mediaDevices?.getUserMedia) {
    return "このブラウザではカメラを開始できません";
  }

  return "AIモデルを開始できませんでした。ネット接続後に再読み込みしてください";
}

function updateDemoStatus(control) {
  if (speedMps < 0.15) {
    elements.cameraStatus.textContent = "ランダム運転デモ: 停止中";
    return;
  }

  if (control > controlDeadZone) {
    elements.cameraStatus.textContent = "ランダム運転デモ: アクセル";
    return;
  }

  if (control < -controlDeadZone) {
    elements.cameraStatus.textContent = "ランダム運転デモ: ブレーキ";
    return;
  }

  elements.cameraStatus.textContent = "ランダム運転デモ: キープ";
}

function runRandomDemo(now) {

  if (now >= nextDemoChangeTime) {
    demoTargetControl = Math.random() * 2 - 1;
    nextDemoChangeTime = now + 800 + Math.random() * 1700;
  }

  latestControl += (demoTargetControl - latestControl) * 0.04;
  if (!sendControlToBackend(latestControl, now)) {
    updatePhysics(latestControl, now);
  }
  updateDemoStatus(latestControl);

  if (positionMeters >= totalDistanceMeters) {
    positionMeters = 0;
    speedMps = 0;
  }

  window.requestAnimationFrame(runRandomDemo);
}

window.updateTrainUI = updateTrainUI;
connectBackend();
updateTrainUI({ positionMeters, speedMps });
lastPhysicsTime = performance.now();

if (window.location.protocol === "file:") {
  maybeStartPoseControls();
} else {
  cameraStartupTimer = window.setTimeout(() => {
    if (!backendConnected && backendControlSource !== "pseudo") {
      maybeStartPoseControls();
    }
  }, 1500);
}
