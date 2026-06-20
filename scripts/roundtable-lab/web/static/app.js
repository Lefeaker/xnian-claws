const state = {
  source: null,
  evidenceByPerson: new Map(),
  sessionId: null,
  roundNumber: 0,
  followLatest: true,
  notesSaveTimer: null,
};

const peopleList = document.querySelector("#peopleList");
const modelStatus = document.querySelector("#modelStatus");
const timeline = document.querySelector("#timeline");
const runStatus = document.querySelector("#runStatus");
const jumpToLatest = document.querySelector("#jumpToLatest");
const evidencePanel = document.querySelector("#evidencePanel");
const sessionList = document.querySelector("#sessionList");
const form = document.querySelector("#roundtableForm");
const startButton = document.querySelector("#startButton");
const newSessionButton = document.querySelector("#newSessionButton");
const sessionInfo = document.querySelector("#sessionInfo");
const notesTextarea = document.querySelector("#notesTextarea");
const notesStatus = document.querySelector("#notesStatus");
const clearNotesButton = document.querySelector("#clearNotesButton");
const template = document.querySelector("#messageTemplate");

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function setStatus(text, mode = "idle") {
  runStatus.textContent = text;
  runStatus.dataset.mode = mode;
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderInlineMarkdown(text) {
  return text
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderMarkdown(text) {
  const escaped = escapeHtml(text || "");
  const blocks = [];
  const codeBlocks = [];
  const withoutCode = escaped.replace(/```([\s\S]*?)```/g, (_, code) => {
    const token = `@@CODE_${codeBlocks.length}@@`;
    codeBlocks.push(`<pre class="code-block"><code>${code.trim()}</code></pre>`);
    return token;
  });

  let listItems = [];
  function flushList() {
    if (!listItems.length) return;
    blocks.push(`<ul>${listItems.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul>`);
    listItems = [];
  }

  for (const rawLine of withoutCode.split("\n")) {
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      flushList();
      continue;
    }
    const codeMatch = line.match(/^@@CODE_(\d+)@@$/);
    if (codeMatch) {
      flushList();
      blocks.push(codeBlocks[Number(codeMatch[1])]);
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushList();
      const level = heading[1].length + 2;
      blocks.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      listItems.push(bullet[1]);
      continue;
    }
    flushList();
    blocks.push(`<p>${renderInlineMarkdown(line)}</p>`);
  }
  flushList();
  return blocks.join("");
}

function isNearTimelineBottom() {
  return timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 90;
}

function scrollToLatest() {
  timeline.scrollTo({ top: timeline.scrollHeight, behavior: "smooth" });
  jumpToLatest.hidden = true;
  state.followLatest = true;
}

function appendTimelineNode(node) {
  const shouldFollow = state.followLatest || isNearTimelineBottom();
  timeline.append(node);
  if (shouldFollow) {
    requestAnimationFrame(scrollToLatest);
  } else {
    jumpToLatest.hidden = false;
  }
}

function appendSystem(text) {
  const node = document.createElement("div");
  node.className = "system-line";
  node.textContent = text;
  appendTimelineNode(node);
}

function appendRoundHeader(roundName, question) {
  const node = document.createElement("div");
  node.className = "round-header";
  node.innerHTML = `<strong>${roundName}</strong><span>${question || "未记录问题"}</span>`;
  appendTimelineNode(node);
}

function appendMessage(person, content, evidence = [], audit = null) {
  const node = template.content.firstElementChild.cloneNode(true);
  node.querySelector("strong").textContent = person;
  const fullContent = audit ? `${content}\n\n## 稽核\n${audit}` : content;
  const body = node.querySelector(".message-body");
  body.innerHTML = renderMarkdown(fullContent);
  node.querySelector('[data-role="evidence"]').addEventListener("click", () => renderEvidence(person, evidence));
  node.querySelector('[data-role="clip"]').addEventListener("click", () => {
    const selected = getSelectionWithin(node);
    appendToNotes(`## ${person}\n\n${selected || content}\n`);
  });
  appendTimelineNode(node);
}

function getSelectionWithin(node) {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0) return "";
  const range = selection.getRangeAt(0);
  if (!node.contains(range.commonAncestorContainer)) return "";
  return selection.toString().trim();
}

function extractNextQuestion(text) {
  const marker = "【下一层引导问题】";
  const index = text.indexOf(marker);
  if (index === -1) return "";
  const rest = text.slice(index + marker.length).trim();
  const nextMarker = rest.indexOf("【");
  return (nextMarker === -1 ? rest : rest.slice(0, nextMarker)).trim();
}

function renderEvidence(person, evidence) {
  evidencePanel.innerHTML = "";
  const heading = document.createElement("h3");
  heading.textContent = `${person} 的检索依据`;
  evidencePanel.append(heading);
  if (!evidence.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "没有检索到证据。";
    evidencePanel.append(empty);
    return;
  }
  for (const hit of evidence) {
    const item = document.createElement("article");
    item.className = "evidence-item";
    const title = document.createElement("div");
    title.className = "evidence-title";
    title.textContent = `score ${hit.score} · chunk ${hit.chunk_index}`;
    const path = document.createElement("div");
    path.className = "evidence-path";
    path.textContent = hit.path;
    const text = document.createElement("pre");
    text.textContent = hit.text;
    item.append(title, path, text);
    evidencePanel.append(item);
  }
}

async function loadStatus() {
  const response = await fetch("/api/status");
  const data = await response.json();
  modelStatus.textContent = `${data.has_api_key ? "API key 已配置" : "API key 未配置"} · ${data.chat_model} · ${data.embed_model}`;
  peopleList.innerHTML = "";
  for (const person of data.people) {
    const card = document.createElement("article");
    card.className = "person-card";
    card.innerHTML = `
      <div class="person-name">${person.person}</div>
      <div class="person-meta">${person.source_count} 份材料 · ${person.indexed_chunks} chunks</div>
    `;
    const sourceList = document.createElement("div");
    sourceList.className = "source-list";
    for (const source of person.sources) {
      const item = document.createElement("div");
      item.textContent = `${source.name} · ${formatBytes(source.bytes)}`;
      sourceList.append(item);
    }
    card.append(sourceList);
    peopleList.append(card);
  }
}

async function loadSessions() {
  const response = await fetch("/api/sessions");
  const data = await response.json();
  sessionList.innerHTML = "";
  if (!data.sessions.length) {
    sessionList.innerHTML = '<div class="empty compact">暂无历史圆桌</div>';
    return;
  }
  for (const item of data.sessions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "session-card";
    button.innerHTML = `
      <span>${item.topic}</span>
      <small>${item.created_at} · ${item.round_number} 轮${item.concluded ? " · 已结束" : ""}</small>
    `;
    button.addEventListener("click", () => restoreSession(item.session_id));
    sessionList.append(button);
  }
}

async function restoreSession(sessionId) {
  const response = await fetch(`/api/sessions/${sessionId}`);
  const data = await response.json();
  if (data.error) {
    appendSystem(`恢复失败：${data.error}`);
    return;
  }
  stopExistingRun();
  state.sessionId = data.session_id;
  state.roundNumber = data.round_number;
  state.evidenceByPerson.clear();
  timeline.innerHTML = "";
  evidencePanel.innerHTML = '<div class="empty">暂无证据</div>';
  notesTextarea.value = data.notes || localStorage.getItem(notesStorageKey(data.session_id)) || "";
  document.querySelector("#topic").value = data.topic;
  document.querySelector("#participants").value = data.participants.join(",");
  document.querySelector("#question").value = data.last_question || "";
  document.querySelector("#command").value = data.concluded ? "止" : "可";
  sessionInfo.textContent = `已恢复 session：${state.sessionId.slice(0, 8)} · 已完成 ${state.roundNumber} 轮`;
  appendSystem(`已恢复历史圆桌：${data.topic}`);
  for (const round of data.rounds || []) {
    appendRoundHeader(round.round, round.question);
    for (const agent of round.agents) {
      appendMessage(agent.person, agent.content, [], agent.audit || null);
    }
    if (round.moderator) {
      appendMessage("主持人", round.moderator, []);
    }
  }
  if (!data.rounds?.length && data.history) {
    appendMessage("历史记录", data.history, []);
  }
  startButton.textContent = data.concluded ? "讨论已结束" : "继续下一轮";
  startButton.disabled = Boolean(data.concluded);
  setStatus(data.concluded ? "已结束" : "已恢复", data.concluded ? "done" : "idle");
  scrollToLatest();
}

function notesStorageKey(sessionId = state.sessionId) {
  return sessionId ? `roundtable-notes:${sessionId}` : "roundtable-notes:draft";
}

function setNotesStatus(text) {
  notesStatus.textContent = text;
}

async function persistNotes() {
  const notes = notesTextarea.value;
  localStorage.setItem(notesStorageKey(), notes);
  if (!state.sessionId) {
    setNotesStatus("本地草稿");
    return;
  }
  setNotesStatus("保存中...");
  const response = await fetch(`/api/sessions/${state.sessionId}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ notes }),
  });
  setNotesStatus(response.ok ? "已保存" : "保存失败");
}

function scheduleNotesSave() {
  setNotesStatus(state.sessionId ? "待保存" : "本地草稿");
  localStorage.setItem(notesStorageKey(), notesTextarea.value);
  window.clearTimeout(state.notesSaveTimer);
  state.notesSaveTimer = window.setTimeout(() => {
    persistNotes().catch((error) => setNotesStatus(`保存失败：${error.message}`));
  }, 500);
}

function appendToNotes(markdown) {
  const prefix = notesTextarea.value.trim() ? "\n\n" : "";
  notesTextarea.value += `${prefix}${markdown.trim()}\n`;
  notesTextarea.focus();
  scheduleNotesSave();
}

function stopExistingRun() {
  if (state.source) {
    state.source.close();
    state.source = null;
  }
}

function startRoundtable(event) {
  event.preventDefault();
  stopExistingRun();
  if (!state.sessionId) {
    state.evidenceByPerson.clear();
    timeline.innerHTML = "";
    evidencePanel.innerHTML = '<div class="empty">暂无证据</div>';
  } else {
    appendSystem(`继续第 ${state.roundNumber + 1} 轮：本轮角色会看到前面完整记录。`);
  }
  setStatus("运行中", "running");
  startButton.disabled = true;
  const params = new URLSearchParams({
    topic: document.querySelector("#topic").value.trim(),
    question: document.querySelector("#question").value.trim(),
    participants: document.querySelector("#participants").value.trim(),
    command: document.querySelector("#command").value,
    new_participant: document.querySelector("#newParticipant").value.trim(),
    top_k: document.querySelector("#topK").value,
    audit: document.querySelector("#audit").checked ? "true" : "false",
    reset: state.sessionId ? "false" : "true",
  });
  if (state.sessionId) {
    params.set("session_id", state.sessionId);
  }
  const source = new EventSource(`/api/roundtable/stream?${params.toString()}`);
  state.source = source;
  source.addEventListener("status", (event) => {
    const data = JSON.parse(event.data);
    appendSystem(data.message);
  });
  source.addEventListener("agent", (event) => {
    const data = JSON.parse(event.data);
    state.evidenceByPerson.set(data.person, data.evidence);
    appendMessage(data.person, data.speech, data.evidence, data.audit);
  });
  source.addEventListener("moderator", (event) => {
    const data = JSON.parse(event.data);
    appendMessage("主持人", data.content, []);
    const nextQuestion = extractNextQuestion(data.content);
    if (nextQuestion) {
      document.querySelector("#question").value = nextQuestion;
    }
  });
  source.addEventListener("conclusion", (event) => {
    const data = JSON.parse(event.data);
    appendMessage("主持人：全局知识网络", data.content, []);
    startButton.textContent = "讨论已结束";
    startButton.disabled = true;
  });
  source.addEventListener("done", (event) => {
    const data = JSON.parse(event.data);
    state.sessionId = data.session_id;
    state.roundNumber = data.round_number;
    persistNotes().catch((error) => setNotesStatus(`保存失败：${error.message}`));
    sessionInfo.textContent = `当前 session：${state.sessionId.slice(0, 8)} · 已完成 ${state.roundNumber} 轮`;
    appendSystem(`已保存 session：${data.session_dir}`);
    setStatus(data.concluded ? "已结束" : "完成", "done");
    if (!data.concluded) {
      startButton.textContent = "继续下一轮";
      startButton.disabled = false;
    }
    stopExistingRun();
    loadStatus();
    loadSessions();
  });
  source.addEventListener("error", (event) => {
    if (event.data) {
      const data = JSON.parse(event.data);
      appendSystem(`错误：${data.message}`);
    } else {
      appendSystem("连接中断。");
    }
    setStatus("错误", "error");
    startButton.disabled = false;
    stopExistingRun();
  });
}

form.addEventListener("submit", startRoundtable);
newSessionButton.addEventListener("click", () => {
  stopExistingRun();
  state.sessionId = null;
  state.roundNumber = 0;
  state.evidenceByPerson.clear();
  timeline.innerHTML = "";
  evidencePanel.innerHTML = '<div class="empty">暂无证据</div>';
  document.querySelector("#question").value = "";
  document.querySelector("#command").value = "可";
  document.querySelector("#newParticipant").value = "";
  notesTextarea.value = "";
  localStorage.removeItem("roundtable-notes:draft");
  setNotesStatus("本地草稿");
  sessionInfo.textContent = "尚未开始 session";
  startButton.textContent = "开始一轮圆桌";
  startButton.disabled = false;
  setStatus("待开始", "idle");
});
timeline.addEventListener("scroll", () => {
  state.followLatest = isNearTimelineBottom();
  if (state.followLatest) {
    jumpToLatest.hidden = true;
  }
});
jumpToLatest.addEventListener("click", scrollToLatest);
notesTextarea.addEventListener("input", scheduleNotesSave);
clearNotesButton.addEventListener("click", () => {
  notesTextarea.value = "";
  scheduleNotesSave();
});
loadStatus().catch((error) => {
  modelStatus.textContent = `状态读取失败：${error.message}`;
});
loadSessions().catch((error) => {
  sessionList.innerHTML = `<div class="empty compact">历史读取失败：${error.message}</div>`;
});
notesTextarea.value = localStorage.getItem(notesStorageKey()) || "";
