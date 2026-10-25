"use strict";

const $ = (id) => document.getElementById(id);
const statuses = { playing: "Прохожу", completed: "Пройдено", dropped: "Брошено" };
let playerId = Number(localStorage.getItem("game-roll-player")) || null;
let state = null;
let assignments = [];
let catalogue = [];
let playerNames = [];
let busy = false;

function notice(message = "") {
  $("notice").textContent = message;
  $("notice").hidden = !message;
}

async function api(path, method = "GET", body) {
  const response = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : "Проверь введённые данные.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function startReveal() {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  $("game-area").style.minHeight = `${$("game-area").getBoundingClientRect().height}px`;
  $("game-area").setAttribute("aria-busy", "true");
  $("game-area").innerHTML = `<div class="offer rolling">
    <p class="game-state" role="status">Выбираем игру...</p>
    <div class="reel" aria-hidden="true"><span id="reel-name">Какая игра выпадет?</span></div>
    <div class="roll-progress" aria-hidden="true"><span></span></div>
  </div>`;
  // Меняются только названия на экране. Сервер делает один настоящий выбор.
  const limit = state.round ? state.round.max_hours : null;
  const titles = catalogue.filter((game) => limit === null || game.hours <= limit).map((game) => game.name);
  let interval;
  if (!reducedMotion && titles.length) {
    interval = setInterval(() => {
      const name = $("reel-name");
      if (name) name.textContent = titles[Math.floor(Math.random() * titles.length)];
    }, 110);
  }
  let timeout;
  let finish;
  const finished = new Promise((resolve) => {
    finish = resolve;
    timeout = setTimeout(resolve, reducedMotion ? 0 : 1800);
  });
  return {
    finished,
    stop() { clearInterval(interval); clearTimeout(timeout); finish(); },
  };
}

async function action(work, reveal = false) {
  if (busy) return;
  busy = true;
  notice();
  document.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  const animation = reveal ? startReveal() : null;
  try {
    await Promise.all([work(), animation ? animation.finished : Promise.resolve()]);
    await refresh();
  } catch (error) {
    notice(error.message === "Failed to fetch" ? "Нет связи с сервером. Проверь, запущен ли сервис." : error.message);
    // Другая вкладка могла принять игру или использовать попытку.
    if (error.status === 409) await refresh().catch(() => {});
  } finally {
    if (animation) {
      animation.stop();
      renderGame();
      const info = $("game-info");
      if (info) info.classList.add("revealed");
    }
    busy = false;
    document.querySelectorAll("button").forEach((button) => { button.disabled = false; });
  }
}

function hours(value) { return `${value.toLocaleString("ru-RU")} ч`; }

function renderPlayerNames(players) {
  const names = players.map((player) => player.name);
  // Не перестраиваем открытый список при каждом фоновом обновлении.
  if (JSON.stringify(names) === JSON.stringify(playerNames)) return;
  playerNames = names;
  $("player-names").replaceChildren();
  $("no-players").hidden = names.length > 0;
  for (const name of names) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "player-option";
    button.textContent = name;
    button.onclick = () => {
      $("player-name").value = name;
      $("player-picker").open = false;
      $("player-name").focus();
    };
    item.append(button);
    $("player-names").append(item);
  }
}

function describeGame(game) {
  if (game.description) return game.description;
  // Короткая справка по жанрам каталога, без выдуманного описания сюжета.
  const genres = game.genres.split(",").map((genre) => genre.trim());
  const descriptions = {
    "Role-Playing": "Ролевая игра с элементами развития персонажа.",
    "Shooter": "Шутер, в котором основное внимание уделяется стрельбе и сражениям.",
    "Hack and Slash": "Экшен со сражениями в ближнем бою.",
    "Fighting": "Файтинг с поединками и комбинациями ударов.",
    "Survival Horror": "Хоррор с элементами выживания.",
    "Horror": "Хоррор с напряжённой атмосферой.",
    "Platform": "Платформер с прыжками и преодолением препятствий.",
    "Puzzle": "Головоломка, в которой нужно искать решения и замечать детали.",
    "Strategy": "Стратегия с планированием действий и управлением ресурсами.",
    "Strategy/Tactical": "Тактическая стратегия, где важно продумывать каждый ход.",
    "Racing/Driving": "Гонки и управление транспортом.",
    "Visual Novel": "Визуальная новелла с акцентом на историю и диалоги.",
    "Action": "Экшен с активными сражениями и испытаниями на реакцию.",
    "Adventure": "Приключенческая игра с акцентом на развитие истории.",
    "Simulation": "Симулятор, в котором важны освоение механик и внимание к деталям.",
    "Interactive Art": "Интерактивное приключение с акцентом на впечатления и атмосферу.",
  };
  const main = Object.keys(descriptions).find((genre) => genres.includes(genre));
  const extra = genres.includes("Stealth") ? "Есть элементы скрытного прохождения."
    : genres.includes("Open World") ? "Можно исследовать открытый мир." : "";
  const view = genres.includes("First-Person") ? "Камера от первого лица."
    : genres.includes("Third-Person") ? "Камера от третьего лица."
    : genres.includes("Top-Down") || genres.includes("Isometric") ? "Камера с видом сверху." : "";
  return [main ? descriptions[main] : "Игра для ПК из общего каталога.", extra, view].filter(Boolean).join(" ");
}

function renderGame() {
  $("game-area").removeAttribute("aria-busy");
  $("game-area").style.removeProperty("min-height");
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

  $("game-area").innerHTML = `<div class="offer" id="game-info" aria-labelledby="game-name">
    <p class="game-state" id="attempt-label"></p>
    <h3 id="game-name"></h3>
    <p class="game-description" id="game-description"></p>
    <div class="game-meta" id="game-meta"><span id="game-hours"></span><a id="game-source" target="_blank" rel="noopener noreferrer">Об игре</a></div>
  </div><div class="choice-controls" id="choice-controls"></div>`;
  const current = state.assignment;
  const offer = state.round;
  if (!current && !offer) {
    $("attempt-label").textContent = "Новый выбор";
    $("game-name").textContent = "Во что играем?";
    $("game-description").textContent = "Выбери длительность и нажми «Выбрать игру». Здесь появится твоя игра.";
    $("game-meta").hidden = true;
    $("choice-controls").innerHTML = `<div class="pick-options"><label for="max-hours">Время на основной сюжет
      <select id="max-hours"><option value="5">До 5 часов</option><option value="10">До 10 часов</option><option value="20" selected>До 20 часов</option><option value="40">До 40 часов</option><option value="">Любая длительность</option></select>
      </label><button id="roll" type="button">Выбрать игру</button></div>`;
    $("roll").onclick = () => {
      const maxHours = $("max-hours").value ? Number($("max-hours").value) : null;
      action(() => api("/rolls", "POST", { player_id: playerId, max_hours: maxHours }), true);
    };
    return;
  }
  const game = (current || offer).game;
  $("game-name").textContent = game.name;
  $("game-description").textContent = describeGame(game);
  $("game-hours").textContent = `Основной сюжет: ≈ ${hours(game.hours)}`;
  $("game-source").href = game.source_url;
  if (current) {
    $("attempt-label").textContent = "Прохожу";
    $("choice-controls").innerHTML = `<div class="actions" id="finish-actions">
      <button id="complete" type="button">Прошёл</button><button id="drop" class="secondary" type="button">Бросил</button>
    </div>
    <form id="finish-form" class="finish-form" hidden>
      <h3 id="finish-title"></h3>
      <label for="spent-hours">Сколько часов потратил?<input id="spent-hours" type="number" min="0" max="10000" step="0.1" required placeholder="Например, 12.5"></label>
      <label for="comment">Комментарий (необязательно)<textarea id="comment" rows="2" maxlength="500" placeholder="Можно написать пару слов об игре"></textarea></label>
      <div class="actions"><button type="submit">Сохранить результат</button><button id="cancel-finish" class="secondary" type="button">Отмена</button></div>
    </form>`;
    let finishStatus;
    $("comment").value = current.comment;
    for (const [id, status] of [["complete", "completed"], ["drop", "dropped"]]) {
      $(id).onclick = () => {
        finishStatus = status;
        $("finish-title").textContent = status === "completed" ? "Игра пройдена" : "Игра брошена";
        $("finish-actions").hidden = true;
        $("finish-form").hidden = false;
        $("spent-hours").focus();
      };
    }
    $("cancel-finish").onclick = () => {
      $("finish-form").hidden = true;
      $("finish-actions").hidden = false;
      $(finishStatus === "completed" ? "complete" : "drop").focus();
    };
    $("finish-form").onsubmit = (event) => {
      event.preventDefault();
      const result = { status: finishStatus, spent_hours: Number($("spent-hours").value), comment: $("comment").value };
      action(() => api(`/assignments/${current.id}`, "PATCH", result));
    };
  } else {
    $("attempt-label").textContent = `Попытка ${offer.attempt} из 3`;
    $("choice-controls").innerHTML = `<div class="actions"><button id="accept" type="button">Буду проходить</button><button id="reroll" class="secondary" type="button">Перебросить</button></div><p class="hint" id="roll-hint"></p>`;
    $("roll-hint").textContent = offer.attempt === 1 ? "Осталось 2 переброса." : "Последний переброс. Следующая игра запишется автоматически.";
    $("accept").onclick = () => action(() => api(`/rolls/${offer.id}/accept`, "POST", { attempt: offer.attempt }));
    $("reroll").onclick = () => action(async () => {
      const next = await api(`/rolls/${offer.id}/reroll`, "POST", { attempt: offer.attempt });
      if (next.accepted) notice("Третья игра записана в таблицу.");
    }, true);
  }
}

function renderHistory() {
  const rows = assignments.filter((item) => (!$("player-filter").value || item.player_id === Number($("player-filter").value)) && (!$("status-filter").value || item.status === $("status-filter").value));
  $("history-body").replaceChildren();
  $("history-wrap").hidden = rows.length === 0;
  $("empty-history").hidden = rows.length > 0;
  $("empty-history").textContent = assignments.length ? "По этим фильтрам записей нет." : "Пока никто не выбрал игру.";
  for (const item of rows) {
    const tr = document.createElement("tr");
    const spent = item.spent_hours == null ? (item.status === "playing" ? "Ещё играет" : "Не указано") : hours(item.spent_hours);
    for (const value of [item.player_name, item.game.name, `≈ ${hours(item.game.hours)}`, spent, "", item.comment || "Без комментария"]) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.append(td);
    }
    const status = document.createElement("span");
    status.className = `status ${item.status}`;
    status.textContent = statuses[item.status];
    tr.children[4].append(status);
    $("history-body").append(tr);
  }
}

async function refresh() {
  const [players, history] = await Promise.all([api("/players"), api("/assignments")]);
  assignments = history;
  const filter = $("player-filter").value;
  $("player-filter").replaceChildren(new Option("Все друзья", ""));
  for (const player of players) {
    $("player-filter").append(new Option(player.name, player.id));
  }
  renderPlayerNames(players);
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
    // Фоновое обновление не стирает часы и комментарий в открытой форме.
    if (JSON.stringify(next) !== JSON.stringify(state)) { state = next; renderGame(); }
  }
  $("updated").textContent = `Обновлено в ${new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`;
}

$("name-form").onsubmit = (event) => {
  event.preventDefault();
  const name = $("player-name").value.trim();
  if (!name) { notice("Введи имя или ник."); return; }
  $("player-picker").open = false;
  action(async () => {
    const player = await api("/players", "POST", { name });
    playerId = player.id;
    localStorage.setItem("game-roll-player", playerId);
  });
};
const namePicker = document.querySelector(".name-picker");
namePicker.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $("player-picker").open) {
    event.preventDefault();
    $("player-picker").open = false;
    $("player-picker").querySelector("summary").focus();
  }
});
namePicker.addEventListener("focusout", (event) => {
  if (!namePicker.contains(event.relatedTarget)) $("player-picker").open = false;
});
document.addEventListener("click", (event) => {
  if (!namePicker.contains(event.target)) $("player-picker").open = false;
});
$("refresh").onclick = () => action(async () => {});
$("player-filter").onchange = renderHistory;
$("status-filter").onchange = renderHistory;
refresh().catch(() => notice("Не удалось загрузить данные. Проверь связь с сервером и нажми «Обновить»."));
api("/games").then((games) => { catalogue = games; }).catch(() => {});
setInterval(() => { if (!busy) refresh().catch(() => notice("Нет связи с сервером. История обновится после восстановления связи.")); }, 15000);
