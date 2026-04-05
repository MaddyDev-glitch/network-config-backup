const state = {
  devices: [],
  selectedDevice: null,
  changes: [],
  selectedChangeId: null,
  selectedChange: null,
  showFullDiff: false,
};

const deviceList = document.getElementById("deviceList");
const changeList = document.getElementById("changeList");
const timelineTitle = document.getElementById("timelineTitle");
const diffTitle = document.getElementById("diffTitle");
const diffGrid = document.getElementById("diffGrid");
const previousMeta = document.getElementById("previousMeta");
const currentMeta = document.getElementById("currentMeta");
const noteInput = document.getElementById("noteInput");
const saveNoteButton = document.getElementById("saveNoteButton");
const noteStatus = document.getElementById("noteStatus");
const refreshButton = document.getElementById("refreshButton");
const diffStatAdded = document.getElementById("diffStatAdded");
const diffStatRemoved = document.getElementById("diffStatRemoved");
const diffStatChanged = document.getElementById("diffStatChanged");
const copyDiffButton = document.getElementById("copyDiffButton");
const showFullDiffToggle = document.getElementById("showFullDiffToggle");

refreshButton.addEventListener("click", async () => {
  await loadDevices();
});

showFullDiffToggle.addEventListener("change", () => {
  state.showFullDiff = showFullDiffToggle.checked;
  renderDiffRows();
});

copyDiffButton.addEventListener("click", async () => {
  if (!state.selectedChange) {
    return;
  }
  const text = buildCopyConfigText(state.selectedChange);
  try {
    await copyText(text);
    noteStatus.textContent = "Current config copied to clipboard.";
  } catch (error) {
    noteStatus.textContent = "Clipboard copy failed.";
  }
});

saveNoteButton.addEventListener("click", async () => {
  if (!state.selectedChangeId) {
    return;
  }

  const response = await fetch(`/api/changes/${state.selectedChangeId}/note`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ note: noteInput.value }),
  });

  if (!response.ok) {
    noteStatus.textContent = "Failed to save note.";
    return;
  }

  const payload = await response.json();
  const change = state.changes.find((item) => item.id === state.selectedChangeId);
  if (change) {
    change.note = payload.note;
    change.note_updated_at = payload.updated_at;
  }
  noteStatus.textContent = payload.updated_at ? `Saved ${formatDate(payload.updated_at)}` : "Saved";
  renderChanges();
});

async function loadDevices() {
  const response = await fetch("/api/devices");
  const payload = await response.json();
  state.devices = payload.devices;
  renderDevices();

  if (!state.devices.length) {
    state.selectedDevice = null;
    state.changes = [];
    renderChanges();
    resetDiff();
    return;
  }

  const stillExists = state.devices.some((device) => device.name === state.selectedDevice);
  state.selectedDevice = stillExists ? state.selectedDevice : state.devices[0].name;
  await loadChanges(state.selectedDevice);
}

async function loadChanges(deviceName) {
  state.selectedDevice = deviceName;
  const response = await fetch(`/api/devices/${encodeURIComponent(deviceName)}/changes`);
  const payload = await response.json();
  state.changes = payload.changes.slice().reverse();
  renderDevices();
  renderChanges();

  if (!state.changes.length) {
    resetDiff();
    return;
  }

  const stillExists = state.changes.some((change) => change.id === state.selectedChangeId);
  state.selectedChangeId = stillExists ? state.selectedChangeId : state.changes[0].id;
  await loadDiff(state.selectedChangeId);
}

async function loadDiff(changeId) {
  state.selectedChangeId = changeId;
  renderChanges();

  const response = await fetch(`/api/changes/${changeId}`);
  const change = await response.json();
  state.selectedChange = change;

  diffTitle.textContent = `${change.device} · ${formatDate(change.current.collected_at)}`;
  previousMeta.innerHTML = renderSnapshotMeta("Previous", change.previous);
  currentMeta.innerHTML = renderSnapshotMeta("Current", change.current);
  diffStatAdded.textContent = `+${change.stats.added}`;
  diffStatRemoved.textContent = `-${change.stats.removed}`;
  diffStatChanged.textContent = `~${change.stats.changed}`;
  noteInput.disabled = false;
  saveNoteButton.disabled = false;
  copyDiffButton.disabled = false;
  noteInput.value = change.note || "";
  noteStatus.textContent = change.note_updated_at ? `Last saved ${formatDate(change.note_updated_at)}` : "";

  showFullDiffToggle.disabled = false;
  showFullDiffToggle.checked = state.showFullDiff;
  renderDiffRows();
}

function renderDevices() {
  if (!state.devices.length) {
    deviceList.innerHTML = `<div class="empty-state">No device folders found under output/.</div>`;
    return;
  }

  const selectedDevice = state.devices.find((device) => device.name === state.selectedDevice) || state.devices[0];
  deviceList.innerHTML = `
    <label class="device-selector header-device-selector">
      <span class="device-selector-label">Device</span>
      <select id="deviceSelect" class="device-select">
        ${state.devices.map((device) => `
          <option value="${escapeHtml(device.name)}" ${device.name === selectedDevice.name ? "selected" : ""}>
            ${escapeHtml(device.name)}
          </option>
        `).join("")}
      </select>
    </label>
  `;

  const deviceSelect = document.getElementById("deviceSelect");
  deviceSelect.addEventListener("change", async () => {
    await loadChanges(deviceSelect.value);
  });
}

function renderChanges() {
  timelineTitle.textContent = state.selectedDevice ? `${state.selectedDevice} history` : "Select a device";
  if (!state.selectedDevice) {
    changeList.className = "change-list empty-state";
    changeList.textContent = "No device selected.";
    return;
  }

  if (!state.changes.length) {
    changeList.className = "change-list empty-state";
    changeList.textContent = "No real config changes detected yet.";
    return;
  }

  changeList.className = "change-list";
  changeList.innerHTML = state.changes.map((change) => {
    const active = change.id === state.selectedChangeId ? "active" : "";
    const noteFlag = change.note ? "Saved note" : "No note";
    const typeLabel = change.type === "initial" ? "Initial" : "Change";
    return `
      <button class="change-card ${active}" type="button" data-change="${change.id}">
        <div class="change-card-top">
          <div class="change-summary">${escapeHtml(change.summary)}</div>
          <div class="change-time">${formatDate(change.current.collected_at)}</div>
        </div>
        <div class="change-card-bottom">
          <span class="change-chip change-chip-type">${escapeHtml(typeLabel)}</span>
          <span class="change-chip change-chip-note ${change.note ? "has-note" : "no-note"}">${escapeHtml(noteFlag)}</span>
          <span class="change-chip change-chip-file">${escapeHtml(change.current.filename)}</span>
        </div>
      </button>
    `;
  }).join("");

  document.querySelectorAll("[data-change]").forEach((element) => {
    element.addEventListener("click", async () => {
      await loadDiff(element.dataset.change);
    });
  });
}

function renderSnapshotMeta(label, snapshot) {
  if (!snapshot) {
    return `<strong>${label}</strong><br>No previous snapshot`;
  }

  return `
    <strong>${label}</strong><br>
    ${escapeHtml(snapshot.filename)}<br>
    ${formatDate(snapshot.collected_at)}<br>
    ${snapshot.size} bytes
  `;
}

function renderDiffRow(row) {
  return `
    <div class="diff-row ${row.kind}">
      <div class="cell line-no">${row.left.line_no ?? ""}</div>
      <div class="cell text">${escapeHtml(row.left.text || " ")}</div>
      <div class="cell line-no">${row.right.line_no ?? ""}</div>
      <div class="cell text right">${escapeHtml(row.right.text || " ")}</div>
    </div>
  `;
}

function renderDiffRows() {
  if (!state.selectedChange) {
    diffGrid.className = "diff-grid empty-state";
    diffGrid.textContent = "No change selected.";
    return;
  }

  const rows = state.showFullDiff
    ? state.selectedChange.diff_rows
    : state.selectedChange.diff_rows.filter((row) => row.kind !== "equal");

  diffGrid.classList.remove("empty-state");
  diffGrid.innerHTML = rows.length
    ? rows.map(renderDiffRow).join("")
    : `<div class="diff-empty-message">No changed lines.</div>`;
}

function resetDiff() {
  state.selectedChangeId = null;
  state.selectedChange = null;
  diffTitle.textContent = "Choose a change";
  previousMeta.textContent = "";
  currentMeta.textContent = "";
  diffStatAdded.textContent = "+0";
  diffStatRemoved.textContent = "-0";
  diffStatChanged.textContent = "~0";
  diffGrid.className = "diff-grid empty-state";
  diffGrid.textContent = "No change selected.";
  copyDiffButton.disabled = true;
  showFullDiffToggle.checked = false;
  showFullDiffToggle.disabled = true;
  noteInput.value = "";
  noteInput.disabled = true;
  saveNoteButton.disabled = true;
  noteStatus.textContent = "";
}

function buildCopyConfigText(change) {
  const text = change.current?.raw_content || change.current?.normalized_content || "";
  if (change.current?.filename?.toLowerCase().endsWith(".xml")) {
    return beautifyXml(text);
  }
  return text;
}

function beautifyXml(text) {
  const parser = new DOMParser();
  const parsed = parser.parseFromString(text, "application/xml");
  if (parsed.querySelector("parsererror")) {
    return text;
  }

  const normalized = text
    .replace(/>\s*</g, "><")
    .replace(/(>)(<)(\/*)/g, "$1\n$2$3")
    .split("\n");

  let indent = 0;
  const formatted = [];

  for (const rawLine of normalized) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }

    if (/^<\//.test(line)) {
      indent = Math.max(indent - 1, 0);
    }

    formatted.push(`${"  ".repeat(indent)}${line}`);

    if (
      /^<[^!?][^>]*[^/]>$/.test(line) &&
      !line.includes("</")
    ) {
      indent += 1;
    }
  }

  return formatted.join("\n");
}

async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const helper = document.createElement("textarea");
  helper.value = text;
  helper.setAttribute("readonly", "");
  helper.style.position = "fixed";
  helper.style.top = "0";
  helper.style.left = "0";
  helper.style.opacity = "0";
  document.body.appendChild(helper);
  helper.focus();
  helper.select();
  helper.setSelectionRange(0, helper.value.length);

  const copied = document.execCommand("copy");
  document.body.removeChild(helper);

  if (!copied) {
    throw new Error("Copy command failed");
  }
}

function formatDate(value) {
  if (!value) {
    return "Unknown time";
  }
  const date = new Date(value.replace(" ", "T"));
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

loadDevices();
