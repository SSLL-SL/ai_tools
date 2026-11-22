function collectMagnetsFromPage() {
  const found = new Set();

  function addMagnets(value) {
    const matches = String(value).match(/magnet:\?[^"'`<>\s]+/gi) || [];
    for (const match of matches) {
      const magnet = match
        .replace(/&amp;|&#0*38;|&#x0*26;/gi, "&")
        .replace(/&quot;|&#0*34;|&#x0*22;/gi, '"')
        .replace(/&#0*39;|&#x0*27;/gi, "'")
        .replace(/[),.;\]}]+$/g, "");
      if (/^magnet:\?xt=/i.test(magnet)) found.add(magnet);
    }
  }

  for (const link of document.querySelectorAll("a[href], area[href]")) {
    addMagnets(link.getAttribute("href"));
    addMagnets(link.href);
  }

  if (document.documentElement) addMagnets(document.documentElement.outerHTML);
  if (document.body) addMagnets(document.body.innerText);
  return [...found];
}

const status = document.querySelector("#status");
const results = document.querySelector("#results");
const extractButton = document.querySelector("#extract-button");
const copyAllButton = document.querySelector("#copy-all");
const downloadProgress = document.querySelector("#download-progress");
let currentMagnets = [];

function renderMagnets(magnets) {
  currentMagnets = magnets;
  results.replaceChildren();
  results.hidden = magnets.length === 0;
  copyAllButton.hidden = magnets.length === 0;

  for (const magnet of magnets) {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.className = "magnet";
    link.href = magnet;
    link.textContent = magnet;

    const copyButton = document.createElement("button");
    copyButton.className = "copy-one";
    copyButton.type = "button";
    copyButton.textContent = "Copiar";
    copyButton.addEventListener("click", () => copyText(magnet));

    const torrentButton = document.createElement("button");
    torrentButton.className = "torrent-button";
    torrentButton.type = "button";
    torrentButton.textContent = "Descargar .torrent";
    torrentButton.addEventListener("click", () => downloadTorrent(magnet, torrentButton));

    const fileButton = document.createElement("button");
    fileButton.className = "file-button";
    fileButton.type = "button";
    fileButton.textContent = "Descargar fichero";
    fileButton.addEventListener("click", () => downloadFile(magnet, fileButton));

    item.append(link, copyButton, torrentButton, fileButton);
    results.append(item);
  }

  status.textContent = magnets.length
    ? `Se encontraron ${magnets.length} enlace${magnets.length === 1 ? "" : "s"}.`
    : "No se encontraron enlaces magnet en esta pestaña.";
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    status.textContent = "Enlace copiado al portapapeles.";
  } catch {
    status.textContent = "No se pudo copiar. Selecciona el enlace para copiarlo manualmente.";
  }
}

function magnetFilename(magnet) {
  const query = magnet.slice(magnet.indexOf("?") + 1);
  const xt = new URLSearchParams(query).get("xt") || "metadata";
  const hash = xt.split(":").pop().replace(/[^a-z0-9_-]/gi, "").slice(0, 64);
  return `magnet-${hash || "metadata"}.torrent`;
}

function bytesToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function startDownload(url, filename) {
  return new Promise((resolve, reject) => {
    chrome.downloads.download({ url, filename, saveAs: true }, (downloadId) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else {
        resolve(downloadId);
      }
    });
  });
}

async function readJsonResponse(response, operation) {
  const body = await response.text();
  if (!body.trim()) {
    throw new Error(
      `${operation}: el helper respondió HTTP ${response.status} sin JSON. ` +
      "Cierra la instancia anterior del helper y vuelve a iniciarla."
    );
  }

  try {
    return JSON.parse(body);
  } catch {
    const preview = body.replace(/\s+/g, " ").slice(0, 160);
    throw new Error(
      `${operation}: respuesta no válida del helper (HTTP ${response.status}): ${preview}`
    );
  }
}

async function downloadTorrent(magnet, button) {
  button.disabled = true;
  status.textContent = "Obteniendo los metadatos del torrent…";

  try {
    const response = await fetch("http://127.0.0.1:8765/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ magnet }),
    });

    if (!response.ok) {
      const error = await readJsonResponse(response, "Descargar .torrent");
      throw new Error(error.error || `El helper respondió HTTP ${response.status}.`);
    }

    const torrent = await response.arrayBuffer();
    const dataUrl = `data:application/x-bittorrent;base64,${bytesToBase64(torrent)}`;
    const filename = magnetFilename(magnet);
    await startDownload(dataUrl, filename);
    status.textContent = `Descarga iniciada: ${filename}`;
  } catch (error) {
    if (error instanceof TypeError) {
      status.textContent = `No se pudo conectar al helper. Ejecuta: ./venv/bin/python torrent_helper.py --extension-id ${chrome.runtime.id}`;
    } else {
      status.textContent = error.message || "No se pudo crear el archivo .torrent.";
    }
  } finally {
    button.disabled = false;
  }
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function formatBytes(value) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / (1024 ** index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

async function downloadFile(magnet, button) {
  button.disabled = true;
  downloadProgress.value = 0;
  downloadProgress.hidden = false;
  status.textContent = "Iniciando la descarga del fichero…";

  try {
    const response = await fetch("http://127.0.0.1:8765/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ magnet }),
    });
    const job = await readJsonResponse(response, "Iniciar descarga");
    if (!response.ok) {
      throw new Error(job.error || `El helper respondió HTTP ${response.status}.`);
    }
    if (!job.job_id) {
      throw new Error("El helper no devolvió el identificador de la descarga.");
    }

    while (true) {
      await wait(2000);
      const progressResponse = await fetch("http://127.0.0.1:8765/download/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: job.job_id }),
      });
      const progress = await readJsonResponse(progressResponse, "Consultar descarga");
      if (!progressResponse.ok) {
        throw new Error(progress.error || "No se pudo consultar el estado de la descarga.");
      }
      if (progress.status === "failed") {
        throw new Error(progress.error || "Falló la descarga del fichero.");
      }
      if (progress.status === "completed") {
        downloadProgress.value = 100;
        status.textContent = `Descarga completa: ${progress.destination}`;
        break;
      }
      if (progress.total > 0) {
        const percent = Math.min(100, Math.max(0, progress.progress * 100));
        downloadProgress.value = percent;
        status.textContent = `${percent.toFixed(1)}% · ${formatBytes(progress.downloaded)} / ${formatBytes(progress.total)} · ${formatBytes(progress.speed)}/s · ${progress.peers} peers`;
      } else {
        status.textContent = "Obteniendo metadatos del torrent y conectando con peers…";
      }
    }
  } catch (error) {
    downloadProgress.hidden = true;
    if (error instanceof TypeError) {
      status.textContent = `No se pudo conectar al helper. Ejecuta: ./venv/bin/python torrent_helper.py --extension-id ${chrome.runtime.id}`;
    } else {
      status.textContent = error.message || "No se pudo descargar el fichero.";
    }
  } finally {
    button.disabled = false;
  }
}

async function extractFromActiveTab() {
  extractButton.disabled = true;
  status.textContent = "Buscando enlaces en la pestaña…";
  downloadProgress.hidden = true;
  downloadProgress.value = 0;
  results.hidden = true;
  copyAllButton.hidden = true;

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.id || !/^https?:/.test(tab.url || "")) {
      throw new Error("Abre una página HTTP o HTTPS para extraer sus enlaces.");
    }

    const [execution] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: collectMagnetsFromPage,
    });
    renderMagnets(execution.result || []);
  } catch (error) {
    currentMagnets = [];
    status.textContent = error.message || "Chrome no permitió leer esta pestaña.";
  } finally {
    extractButton.disabled = false;
  }
}

extractButton.addEventListener("click", extractFromActiveTab);
copyAllButton.addEventListener("click", () => copyText(currentMagnets.join("\n")));
extractFromActiveTab();
