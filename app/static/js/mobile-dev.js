"use strict";

(() => {
  const httpsResult = document.getElementById("https-result");
  const apiResult = document.getElementById("api-result");
  const cameraResult = document.getElementById("camera-result");
  const video = document.getElementById("camera-preview");
  const startButton = document.getElementById("start-camera");
  const stopButton = document.getElementById("stop-camera");
  let stream = null;
  let generation = 0;

  httpsResult.textContent = window.isSecureContext && location.protocol === "https:"
    ? "HTTPS 安全來源：通過。" : "目前不是 HTTPS 安全來源，無法驗收手機相機。";

  function stopCamera(message = "相機已停止。") {
    generation += 1;
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    video.srcObject = null;
    video.hidden = true;
    startButton.disabled = false;
    stopButton.disabled = true;
    cameraResult.textContent = message;
  }

  startButton.addEventListener("click", async () => {
    stopCamera();
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      cameraResult.textContent = "瀏覽器未提供相機介面，請確認 HTTPS 與相機權限。";
      return;
    }
    const current = generation;
    startButton.disabled = true;
    stopButton.disabled = false;
    cameraResult.textContent = "正在要求相機權限…";
    try {
      const acquired = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } }, audio: false,
      });
      if (current !== generation || document.hidden) {
        acquired.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = acquired;
      video.srcObject = acquired;
      video.hidden = false;
      await video.play();
      if (current === generation) cameraResult.textContent = "相機預覽已開啟；影像僅在此頁記憶體中。";
    } catch {
      if (current === generation) stopCamera("無法開啟相機；請確認瀏覽器權限後重試。");
    }
  });
  stopButton.addEventListener("click", () => stopCamera());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopCamera();
  });
  window.addEventListener("pagehide", () => stopCamera());
  const apiButton = document.getElementById("check-api");
  apiButton.addEventListener("click", async () => {
    apiButton.disabled = true;
    apiResult.textContent = "正在檢查本機 API…";
    try {
      const response = await fetch("/__dev/api-health", { credentials: "same-origin", cache: "no-store" });
      const body = await response.json();
      apiResult.textContent = response.ok && body.status === "ok" && body.connectivity_checked === true
        ? "前端 → 本機 API：連線通過。尚未驗證登入、資料或模型服務。"
        : "本機 API 尚未就緒；請查看啟動器狀態。";
    } catch {
      apiResult.textContent = "本機 API 檢查失敗；請查看啟動器狀態。";
    } finally {
      apiButton.disabled = false;
    }
  });
})();
