const scanPanel = document.querySelector("#scan");
const settingsPanel = document.querySelector("#settings");
const form = document.querySelector("#settings-form");
const scanButton = document.querySelector("#scan-button");
const banner = document.querySelector("#banner");
const deviceSelect = document.querySelector("#device-select");

let settings = null;
let devices = [];

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => showTab(tab.dataset.tab));
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = readForm();
  const response = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const note = document.querySelector("#save-note");
  if (!response.ok) {
    note.textContent = await errorText(response);
    return;
  }
  settings = await response.json();
  note.textContent = "Saved";
  await refresh();
});

scanButton.addEventListener("click", async () => {
  banner.hidden = true;
  const response = await fetch("/api/scan", { method: "POST" });
  if (!response.ok) {
    banner.hidden = false;
    banner.textContent = await errorText(response);
    return;
  }
  await refresh();
});

function showTab(name) {
  scanPanel.hidden = name !== "scan";
  settingsPanel.hidden = name !== "settings";
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === name);
  });
}

function readForm() {
  const data = new FormData(form);
  const width = String(data.get("width_mm") || "");
  const height = String(data.get("height_mm") || "");
  return {
    server_url: String(data.get("server_url") || "").trim(),
    api_token: String(data.get("api_token") || ""),
    device_name: String(data.get("device_name") || ""),
    resolution_dpi: Number(data.get("resolution_dpi")),
    image_format: String(data.get("image_format")),
    mode: String(data.get("mode")),
    width_mm: width === "" ? null : Number(width),
    height_mm: height === "" ? null : Number(height),
  };
}

function fillForm() {
  if (!settings) return;
  form.elements.server_url.value = settings.server_url;
  form.elements.api_token.value = settings.api_token;
  form.elements.resolution_dpi.value = settings.resolution_dpi;
  form.elements.image_format.value = settings.image_format;
  form.elements.mode.value = settings.mode;
  form.elements.width_mm.value = settings.width_mm ?? "";
  form.elements.height_mm.value = settings.height_mm ?? "";
  const options = [{ name: "", description: "Backend default" }, ...devices];
  const known = new Set(options.map((device) => device.name));
  if (settings.device_name && !known.has(settings.device_name)) {
    options.push({ name: settings.device_name, description: settings.device_name });
  }
  deviceSelect.replaceChildren();
  for (const device of options) {
    const option = document.createElement("option");
    option.value = device.name;
    option.textContent = device.name ? `${device.description} (${device.name})` : device.description;
    deviceSelect.append(option);
  }
  deviceSelect.value = settings.device_name;
}

function paint(status) {
  setLamp("scanner-lamp", status.scanner_found ? "Found" : "Not found", status.scanner_found);
  document.querySelector("#scanner-detail").textContent = status.scanner_message;
  setLamp("server-lamp", status.server_reachable ? "Reachable" : "Unreachable", status.server_reachable);
  document.querySelector("#server-detail").textContent = status.server_message;
  const last = document.querySelector("#last-lamp");
  if (status.last_scan_ok === true) {
    setLamp("last-lamp", "Uploaded", true);
  } else if (status.last_scan_ok === false) {
    setLamp("last-lamp", "Failed", false);
  } else {
    last.textContent = "None yet";
    last.className = "lamp";
  }
  const when = status.last_scan_at ? new Date(status.last_scan_at).toLocaleString() : "";
  const id = status.last_scan_id ? `Scan ${status.last_scan_id}` : "";
  document.querySelector("#last-detail").textContent = [when, status.last_scan_message, id].filter(Boolean).join(" · ");
  document.querySelector("#phase").textContent = status.phase_message;
  scanButton.disabled = status.phase !== "idle";
  devices = status.devices;
  fillForm();
}

function setLamp(id, text, ok) {
  const node = document.querySelector(`#${id}`);
  node.textContent = text;
  node.className = ok ? "lamp ok" : "lamp bad";
}

async function refresh() {
  const [settingsResponse, statusResponse] = await Promise.all([
    fetch("/api/settings"),
    fetch("/api/status"),
  ]);
  settings = await settingsResponse.json();
  paint(await statusResponse.json());
}

async function errorText(response) {
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string") return payload.detail;
    return JSON.stringify(payload.detail || payload);
  } catch {
    return `Request failed (${response.status})`;
  }
}

refresh();
setInterval(refresh, 2000);
