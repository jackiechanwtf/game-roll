"use strict";

const $ = (id) => document.getElementById(id);
const statuses = { playing: "Прохожу", completed: "Пройдено", dropped: "Брошено" };
let playerId = Number(localStorage.getItem("game-roll-player")) || null;
let state = null;
let assignments = [];
let busy = false;

function notice(message = "") {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}

async function api(path, method = "GET", body) {
  const response = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
  const data = await response.json();
  if (!response.ok) {
    const message = typeof data.detail === "string" ? data.detail : "Проверь введённые данные.";
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return data;
}

async function action(work) {
  if (busy) return;
  busy = true;
  notice();
  document.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    await work();
    await refresh();
  } catch (error) {
    notice(error.message === "Failed to fetch" ? "Нет связи с сервером. Проверь, запущен ли сервис." : error.message);
    // Другая вкладка могла принять игру или использовать попытку.
    if (error.status === 409) await refresh().catch(() => {});
  } finally {
    busy = false;
    document.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

function hours(value) { return `${value.toLocaleString("ru-RU")} ч`; }

function renderGame() {
  $("name-form").hidden = Boolean(state);
  $("game-area").hidden = !state;
  $("who").replaceChildren();
  if (!state) return;
  const name = document.createElement("span");
  name.textContent = state.player.name;
  const change = document.createElement("button");
  change.type = "button";
  change.className = "subtle";
  change.textContent = "Сменить имя";
  change.onclick = () => {
    playerId = null;
    state = null;
    localStorage.removeItem("game-roll-player");
    renderGame();
    $("player-name").focus();
  };
  $("who").append(name, change);

  const current = state.assignment;
  const offer = state.round;
  if (!current && !offer) {
    $("game-area").innerHTML = `<div class="pick-options"><label for="max-hours">Время на основной сюжет<select id="max-hours"><option value="5">До 5 часов</option><option value="10">До 10 часов</option><option value="20" selected>До 20 часов</option><option value="40">До 40 часов</option><option value="">Любая длительность</option></select></label><button id="roll" type="button">Выбрать игру</button></div><p class="hint">Только ПК. Уже выпавшие тебе игры исключаются из выбора.</p>`;
    $("roll").onclick = () => action(async () => {
      await api("/rolls", "POST", { player_id: playerId, max_hours: $("max-hours").value ? Number($("max-hours").value) : null });
    });
    return;
  }
  $("game-area").innerHTML = `<div class="offer"><p class="eyebrow" id="attempt-label"></p><h3 id="game-name"></h3><div class="game-meta"><span id="game-hours"></span><span id="game-genres"></span><a id="game-source" target="_blank" rel="noopener noreferrer">Подробнее об игре ↗</a></div><div id="choice-controls"></div></div>`;
  const game = (current || offer).game;
  $("game-name").textContent = game.name;
  $("game-hours").textContent = `Основной сюжет: ≈ ${hours(game.hours)}`;
  $("game-genres").textContent = game.genres;
  $("game-source").href = game.source_url;
  if (current) {
    $("attempt-label").textContent = "Твоя текущая игра · Прохожу";
    $("choice-controls").innerHTML = `<label for="comment">Комментарий для друзей<textarea id="comment" rows="2" maxlength="500" placeholder="Как тебе игра? Почему прошёл или бросил?"></textarea></label><div class="actions"><button id="complete" type="button">Пройдено</button><button id="drop" class="danger" type="button">Брошено</button></div><p class="hint">После завершения появится возможность выбрать следующую игру.</p>`;
    $("comment").value = current.comment;
    for (const [id, status] of [["complete", "completed"], ["drop", "dropped"]]) {
      $(id).onclick = () => action(async () => {
        await api(`/assignments/${current.id}`, "PATCH", { status, comment: $("comment").value });
      });
    }
  } else {
    $("attempt-label").textContent = `Попытка ${offer.attempt} из 3`;
    $("choice-controls").innerHTML = `<div class="actions"><button id="accept" type="button">Буду проходить</button><button id="reroll" class="secondary" type="button">Перебросить</button></div><p class="hint" id="roll-hint"></p>`;
    $("roll-hint").textContent = offer.attempt === 1 ? "Осталось 2 переброса. Третья игра принимается автоматически." : "Остался 1 переброс. Следующая игра принимается автоматически.";
    $("accept").onclick = () => action(() => api(`/rolls/${offer.id}/accept`, "POST", { attempt: offer.attempt }));
    $("reroll").onclick = () => action(async () => {
      const next = await api(`/rolls/${offer.id}/reroll`, "POST", { attempt: offer.attempt });
      if (next.accepted) notice("Третья попытка: игра принята и записана в общую таблицу.");
    });
  }
}

function renderHistory() {
  const rows = assignments.filter((item) => (!$("player-filter").value || item.player_id === Number($("player-filter").value)) && (!$("status-filter").value || item.status === $("status-filter").value));
  $("history-body").replaceChildren();
  $("history-wrap").hidden = rows.length === 0;
  $("empty-history").hidden = rows.length > 0;
  $("empty-history").textContent = assignments.length ? "По выбранным фильтрам записей нет." : "Здесь появятся принятые игры и комментарии друзей.";
  for (const item of rows) {
    const tr = document.createElement("tr");
    for (const value of [item.player_name, item.game.name, `≈ ${hours(item.game.hours)}`, "", item.comment || "—"]) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.append(td);
    }
    const status = document.createElement("span");
    status.className = `status ${item.status}`;
    status.textContent = statuses[item.status];
    tr.children[3].append(status);
    $("history-body").append(tr);
  }
}

async function refresh() {
  const [players, history] = await Promise.all([api("/players"), api("/assignments")]);
  assignments = history;
  const filter = $("player-filter").value;
  $("player-filter").replaceChildren(new Option("Все друзья", ""));
  $("player-names").replaceChildren();
  for (const player of players) {
    $("player-filter").append(new Option(player.name, player.id));
    $("player-names").append(new Option(player.name, player.name));
  }
  $("player-filter").value = filter;
  renderHistory();
  if (playerId) {
    let next;
    try { next = await api(`/players/${playerId}/state`); }
    catch (error) {
      if (error.status !== 404) throw error;
      playerId = null;
      localStorage.removeItem("game-roll-player");
      next = null;
    }
    // Не стираем набираемый комментарий при фоновом обновлении таблицы.
    if (JSON.stringify(next) !== JSON.stringify(state)) { state = next; renderGame(); }
  }
  $("updated").textContent = `Обновлено в ${new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`;
}

$("name-form").onsubmit = (event) => {
  event.preventDefault();
  const name = $("player-name").value.trim();
  if (!name) { notice("Введи имя или ник."); return; }
  action(async () => {
    const player = await api("/players", "POST", { name });
    playerId = player.id;
    localStorage.setItem("game-roll-player", playerId);
  });
};
$("refresh").onclick = () => action(async () => {});
$("player-filter").onchange = renderHistory;
$("status-filter").onchange = renderHistory;
refresh().catch(() => notice("Не удалось загрузить данные. Проверь связь с сервером и нажми «Обновить»."));
api("/games").then((games) => { $("catalogue-size").textContent = `${games.length} ПК-игр в каталоге`; }).catch(() => {});
setInterval(() => { if (!busy) refresh().catch(() => notice("Нет связи с сервером. История обновится после восстановления связи.")); }, 15000);
