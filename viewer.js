"use strict";

const get = id => document.getElementById(id);
const labels = {
  empty: "Нет строк", match: "Совпали поля", conflict: "Расхождение",
  context: "Контекст", candidate: "Кандидаты", outside: "Вне периода",
};
const route = [
  [3, "Подача порошков"], [4, "Дозирование"], [6, "Прессовка"], [7, "Садка"],
  [8, "Печи"], [9, "Дополнительные операции"], [10, "Сдача"],
];
const routeTitles = new Map(route);
const recipeFields = "Код распоряжения, номер шихты и дополнительная марка образуют ключ рецептуры.";
const sameSlot = "Дата и смена помогают проверить, есть ли записи в одном производственном интервале.";
const routeLinks = [
  {from: 3, to: 4,
    rule: "Код материала в подаче сверяется с кодом компонента в «Шихте». Дозирование ищется по версии этой шихты.",
    fields: {
      3: {1: "Отбирается период поиска и один день перед ним.", 2: "nMaterialId сравнивается с кодом компонента в «Шихте»."},
      4: {12: "Код компонента можно сверить вручную с nMaterialId. При поиске строк дозирования этот код не участвует."},
    }},
  {from: 4, to: 6,
    rule: "Дозирование и прессовка сверяются по ключу шихты. Для сравнения записей проверяются дата и смена.",
    fields: {4: {0: sameSlot, 1: sameSlot, 6: recipeFields, 8: recipeFields, 9: recipeFields},
      6: {0: sameSlot, 1: sameSlot, 8: recipeFields, 10: recipeFields, 11: recipeFields}}},
  {from: 6, to: 7,
    rule: "Садка подбирается по сырцу заказа и ключу шихты из прессовки. Дата садки должна быть не раньше даты прессовки. Совпадение даты и смены показывает близких кандидатов.",
    fields: {6: {0: "Дата прессовки задаёт нижнюю границу для садки.", 1: sameSlot, 6: "Код сырца сверяется с заказом.", 8: recipeFields, 10: recipeFields, 11: recipeFields},
      7: {0: "Дата садки сверяется с датой прессовки.", 1: sameSlot, 5: "Код сырца сверяется с заказом.", 7: recipeFields, 9: recipeFields, 10: recipeFields}}},
  {from: 7, to: 8,
    rule: "Вход в печь подбирается по сырцу и ключу шихты относительно прессовки. Записи садки с теми же ключом, датой и сменой показываются как кандидаты.",
    fields: {7: {0: sameSlot, 1: sameSlot, 7: recipeFields, 9: recipeFields, 10: recipeFields},
      8: {2: "Дата входа сверяется с датой прессовки и сравнивается с датой садки.", 3: sameSlot, 8: "Код сырца сверяется с заказом.", 10: recipeFields, 12: recipeFields, 13: recipeFields}}},
  {from: 8, to: 9,
    rule: "Дополнительные операции ищутся по изделию из заказа. Их ключ шихты сверяется с прессовкой, а дата — с выходами из печи.",
    fields: {8: {4: "Даты выхода задают границы проверки дополнительных операций."},
      9: {0: "Запись до всех найденных выходов из печи получает статус расхождения.", 5: "Код изделия сверяется с заказом.", 7: recipeFields, 9: recipeFields, 10: recipeFields}}},
  {from: 9, to: 10,
    rule: "Сдача ищется по коду изделия. Доп. марка сверяется с заказом, дата — с выходами из печи. Связь строки сдачи с дополнительной операцией в выгрузках отсутствует.",
    fields: {10: {0: "Запись до всех найденных выходов из печи получает статус расхождения.",
      6: "Код изделия сверяется с заказом.", 8: "Дополнительная марка сверяется с заказом."}}},
].map((link, index) => ({...link, number: index + 1, title: `${routeTitles.get(link.from)} → ${routeTitles.get(link.to)}`}));
const referenceFields = {
  2: {rule: "Шихта сверяется с заказом по коду марки массы и доп. марке. В дозировании проверяются ключ версии, масса и срок действия на дату записи. Код компонента используется для поиска подачи порошков.",
    columns: [0, 1, 3, 4, 7, 8, 9]},
  5: {rule: "Нормы ищутся по коду сырца и прессам из найденных строк прессовки. Если ни один пресс не совпал, показываются нормы по сырцу.",
    columns: [0, 2]},
  11: {rule: "Оба кода групп сверяются с группами сырца и изделия в строке заказа.",
    columns: [1, 2]},
  12: {rule: "Код оборудования сверяется с кодом пресса, а даты начала и окончания проверяются на пересечение с периодом поиска.",
    columns: [2, 5, 6]},
};
const app = {
  months: [], ordersByMonth: new Map(), coverageByMonth: new Map(), order: null, month: null,
  request: 0, pickerRequest: 0, sourceRequest: 0,
  stages: new Map(), transitions: new Map(), stage: null, connection: null,
};
const formatNumber = new Intl.NumberFormat("ru-RU", {maximumFractionDigits: 8});
const sortText = new Intl.Collator("ru", {numeric: true, sensitivity: "base"});
const plural = new Intl.PluralRules("ru-RU");
const rowForms = {one: "строка", few: "строки", many: "строк", other: "строк"};
const datePattern = /^([0-9]{4})-([0-9]{2})-([0-9]{2})(T[0-9:]+)?$/;
const helpPopover = get("fieldHelp");
const sourceDialog = get("sourceDialog");
let helpTrigger = null;
let sourceTrigger = null;

function el(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  return node;
}

function button(label, action, className) {
  const node = el("button", label, className);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}

function helpButton(title, ...paragraphs) {
  return tooltipButton("?", "help-button", title, ...paragraphs);
}

function tooltipButton(label, className, title, ...paragraphs) {
  const trigger = button(label, () => {
    if (helpPopover.matches(":popover-open")) {
      helpPopover.hidePopover();
      if (helpTrigger === trigger) return;
      helpTrigger?.setAttribute("aria-expanded", "false");
    }
    helpTrigger = trigger;
    trigger.setAttribute("aria-expanded", "true");
    get("helpTitle").textContent = title;
    get("helpBody").replaceChildren(...paragraphs.filter(Boolean).map(text => el("p", text)));
    helpPopover.showPopover({source: trigger});
    positionHelp();
  }, className);
  trigger.setAttribute("aria-label", `Справка · ${title}`);
  trigger.setAttribute("aria-controls", helpPopover.id);
  trigger.setAttribute("aria-expanded", "false");
  return trigger;
}

function positionHelp() {
  if (!helpPopover.matches(":popover-open")) return;
  const anchor = helpTrigger.getBoundingClientRect();
  if (!helpTrigger.isConnected || anchor.bottom < 0 || anchor.top > window.innerHeight) {
    helpPopover.hidePopover();
    return;
  }
  const content = helpPopover.firstElementChild;
  content.style.removeProperty("max-height");
  const {width, height} = helpPopover.getBoundingClientRect();
  const left = Math.max(8, Math.min(anchor.left, document.documentElement.clientWidth - width - 8));
  const below = anchor.bottom + 8;
  const roomBelow = window.innerHeight - below - 8;
  const roomAbove = anchor.top - 16;
  const above = height > roomBelow && roomAbove > roomBelow;
  const available = above ? roomAbove : roomBelow;
  content.style.maxHeight = `${available}px`;
  const top = above ? anchor.top - Math.min(height, available) - 8 : below;
  helpPopover.dataset.side = above ? "above" : "below";
  helpPopover.style.setProperty("--tip-x", `${anchor.left + anchor.width / 2 - left}px`);
  helpPopover.style.left = `${left}px`;
  helpPopover.style.top = `${top}px`;
}

helpPopover.addEventListener("toggle", () => {
  if (!helpPopover.matches(":popover-open")) {
    helpTrigger?.setAttribute("aria-expanded", "false");
    helpTrigger = null;
  }
});
document.addEventListener("scroll", positionHelp, true);

function rowCount(count) {
  return `${formatNumber.format(count)} ${rowForms[plural.select(count)]}`;
}

function visValue(value) {
  if (value === null || value === "") return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : formatNumber.format(value);
  const match = datePattern.exec(value);
  if (match) return `${match[3]}.${match[2]}.${match[1]}${match[4] ? " " + match[4].slice(1) : ""}`;
  return String(value);
}

async function api(path, query) {
  const url = query ? `${path}?${new URLSearchParams(query)}` : path;
  const reply = await fetch(url);
  const payload = await reply.json();
  if (!reply.ok) throw new Error(payload.error || "Данные недоступны.");
  return payload;
}

function report(message = "") {
  get("error").textContent = message;
  get("error").hidden = !message;
}

function ordersFor(month) {
  if (!app.ordersByMonth.has(month)) {
    const pending = api("/api/orders", {month}).catch(error => {
      app.ordersByMonth.delete(month);
      throw error;
    });
    app.ordersByMonth.set(month, pending);
  }
  return app.ordersByMonth.get(month);
}

function coverageFor(month) {
  if (!app.coverageByMonth.has(month)) {
    const pending = api("/api/order-coverage", {month}).catch(error => {
      app.coverageByMonth.delete(month);
      throw error;
    });
    app.coverageByMonth.set(month, pending);
  }
  return app.coverageByMonth.get(month);
}

async function renderOrders(revealSelected = false) {
  const ticket = ++app.pickerRequest;
  const month = get("month").value;
  const query = get("orderSearch").value.toLocaleLowerCase("ru").trim();
  const mode = get("orderMode").value;
  get("orders").replaceChildren();
  get("orderCount").textContent = mode === "all" ? "Загрузка заказов…" : "Сопоставляю этапы…";
  try {
    const [orders, coverage] = await Promise.all([ordersFor(month), mode === "all" ? null : coverageFor(month)]);
    if (ticket !== app.pickerRequest) return;
    const filtered = orders.filter(o => [o.row, o.name, o.raw, o.product, o.mass, o.mark]
      .some(value => String(value).toLocaleLowerCase("ru").includes(query)));
    const byRow = new Map(filtered.map(order => [order.row, order]));
    let entries = coverage ? coverage.orders
      .filter(score => score.initial_stages && byRow.has(score.row) && (mode !== "clean" || !score.conflicts))
      .map(score => ({order: byRow.get(score.row), score})) : filtered.map(order => ({order}));
    const exact = entries.find(entry => String(entry.order.row) === query);
    if (exact) entries = [exact, ...entries.filter(entry => entry !== exact)];
    get("orderCount").textContent = entries.length ? `Найдено ${entries.length} из ${orders.length}` : "Заказы не найдены";
    get("orders").replaceChildren(...entries.map(({order: o, score}) => {
      const item = el("li");
      const select = button(undefined, () => selectOrder(month, o), "order-item");
      select.dataset.row = o.row;
      const number = el("strong", o.row);
      number.prepend(el("span", "Строка ", "sr-only"));
      const name = el("span", o.name.trim() || "Без наименования", "order-list-name");
      name.title = name.textContent;
      select.append(number, name);
      if (score) select.append(coverageLabel(score, coverage.stage_count));
      item.append(select);
      return item;
    }));
    get("orders").scrollTop = 0;
    markCurrentOrder(revealSelected);
    return entries.map(entry => entry.order);
  } catch (error) {
    if (ticket === app.pickerRequest) get("orderCount").textContent = error.message;
  }
}

function coverageLabel(score, total) {
  const node = el("span", undefined, "order-coverage");
  const conflicts = {one: "расхождение", few: "расхождения", many: "расхождений", other: "расхождений"};
  const ambiguous = {one: "неоднозначность", few: "неоднозначности", many: "неоднозначностей", other: "неоднозначностей"};
  const detail = [`${score.covered}/${total} этапов`, `${score.conflicts} ${conflicts[plural.select(score.conflicts)]}`];
  node.append(el("span", `${score.covered}/${total}`, "order-covered"));
  if (score.conflicts) node.append(el("span", `!${score.conflicts}`, "order-issue"));
  if (score.ambiguous) {
    node.append(el("span", `?${score.ambiguous}`, "order-ambiguous"));
    detail.push(`${score.ambiguous} ${ambiguous[plural.select(score.ambiguous)]}`);
  }
  node.title = detail.join(" · ");
  for (const item of node.children) item.setAttribute("aria-hidden", "true");
  node.append(el("span", node.title, "sr-only"));
  return node;
}

function markCurrentOrder(reveal = false) {
  const row = app.month === get("month").value ? String(app.order?.row) : null;
  const items = [...get("orders").querySelectorAll("button")];
  items.forEach((item, index) => {
    if (item.dataset.row === row) {
      item.setAttribute("aria-current", "true");
      if (reveal) get("orders").scrollTop = items[Math.max(0, index - 2)].offsetTop - 5;
    } else {
      item.removeAttribute("aria-current");
    }
  });
}

function renderOrderSheet() {
  const sheet = get("orderSheet");
  sheet.hidden = !app.month || app.month === get("month").value;
  if (!sheet.hidden) {
    sheet.textContent = `Лист заказа · ${app.months.find(m => m.id === app.month).label}`;
  }
}

function renderOrder() {
  const o = app.order;
  renderOrderSheet();
  get("orderNumber").textContent = `Заказ ${o.row}`;
  get("orderNumber").hidden = false;
  get("orderTitle").textContent = o.name.trim() || (o.product ? `Изделие ${o.product}` : "Наименование отсутствует");
  get("orderProduct").textContent = visValue(o.product);
  get("orderRaw").textContent = visValue(o.raw);
  get("orderMass").textContent = visValue(o.mass);
  get("orderMark").textContent = o.mark || "—";
  get("orderBase").textContent = typeof o.base === "number" ? `${formatNumber.format(o.base)} т` : visValue(o.base);
  get("orderExtra").textContent = typeof o.extra === "number" ? `${formatNumber.format(o.extra)} т` : visValue(o.extra);
  get("orderExtraField").hidden = o.extra === 0 || o.extra === "" || o.extra == null;
  get("orderFacts").hidden = false;
  get("openOrder").hidden = false;
}

async function selectOrder(month, order, scroll = true) {
  app.month = month;
  app.order = order;
  get("shift").value = "";
  get("content").hidden = true;
  get("filters").hidden = false;
  get("recipe").replaceChildren();
  get("recipe").disabled = true;
  get("applyFilters").disabled = true;
  app.stage = null;
  app.connection = null;
  renderOrder();
  markCurrentOrder();
  setView("tab-route");
  if (scroll) window.scrollTo(0, 0);
  await loadTrace("auto");
}

function renderRecipes(data) {
  const select = get("recipe");
  select.replaceChildren(new Option(`Все версии марки массы (${data.versions.length})`, "all"));
  const groups = new Map();
  for (const v of data.versions) {
    const name = !v.active ? "Вне срока действия" : v.order_mark ? "Совпала доп. марка заказа" : "Та же масса, другая доп. марка";
    if (!groups.has(name)) {
      const group = document.createElement("optgroup");
      group.label = name;
      groups.set(name, group);
    }
    groups.get(name).append(new Option(`${v.order_code}/${v.number} · ${v.marks.join(", ") || "доп. марка пуста"}`, v.id));
  }
  select.append(...groups.values());
  select.value = data.recipe;
  select.disabled = false;
  return data.versions.find(v => v.id === data.recipe);
}

function renderCatalog(stage, selected, data) {
  const title = selected ? `Шихта ${selected.order_code}/${selected.number}` : "Все версии шихты";
  const note = selected
    ? `Срок действия ${visValue(selected.first)}–${visValue(selected.last)}. Доп. марка ${selected.order_mark ? "совпала с заказом" : "отличается от заказа"}. В периоде действуют ${data.active_count} из ${data.versions.length} версий марки массы.`
    : `В периоде действуют ${data.active_count} из ${data.versions.length} версий марки массы.`;
  get("view-catalog").replaceChildren(sectionWithTable(stage, title, note));
}

async function loadTrace(recipe = get("recipe").value || "auto") {
  if (!app.order) return;
  const ticket = ++app.request;
  get("main").setAttribute("aria-busy", "true");
  get("status").textContent = "Загрузка данных заказа…";
  report();
  const query = {month: app.month, row: app.order.row, recipe};
  if (get("shift").value) query.shift = get("shift").value;
  try {
    const data = await api("/api/trace", query);
    if (ticket !== app.request) return;
    app.stages = new Map(data.stages.map(s => [s.file, s]));
    app.transitions = new Map(data.gaps.map(gap => [gap.to, gap]));
    const selected = renderRecipes(data);
    renderCatalog(app.stages.get(2), selected, data);
    renderRoute();
    get("view-context").replaceChildren(...[11, 12].map(file => {
      const stage = app.stages.get(file);
      return sectionWithTable(stage, stage.title);
    }));
    get("content").hidden = false;
    get("status").textContent = `Маршрут заказа ${app.order.row} обновлён`;
  } catch (error) {
    if (ticket !== app.request) return;
    get("content").hidden = true;
    report(error.message);
    get("status").textContent = "";
  } finally {
    if (ticket === app.request) {
      get("main").setAttribute("aria-busy", "false");
      get("applyFilters").disabled = false;
    }
  }
}

function renderRoute() {
  get("route").replaceChildren(...route.map(([file, title]) => {
    const item = el("li");
    const stage = app.stages.get(file);
    const step = button(undefined, () => showStage(file), "step");
    step.dataset.file = file;
    step.setAttribute("aria-controls", "operation");
    step.append(el("strong", title));
    const issue = app.transitions.get(file);
    const tone = issue?.tone === "conflict" || stage.tone === "conflict" ? "conflict" :
      issue?.tone === "ambiguous" ? "ambiguous" : stage.outside_period ? "outside" : null;
    const status = tone ? badge(tone) : el("small", rowCount(stage.rows.length));
    step.append(status);
    item.append(step);
    const link = routeLinks.find(link => link.to === file);
    if (link) {
      item.classList.add("has-connection");
      const {tone, label} = connectionStatus(link);
      const marker = button(link.number, () => {
        showStage([link.from, link.to].includes(app.stage) ? app.stage : link.to, link);
      }, "connection-mark route-connection");
      marker.dataset.link = link.number;
      marker.dataset.tone = tone;
      marker.title = `${link.title} · ${label}`;
      marker.setAttribute("aria-label", `Связь ${link.number}. ${marker.title}`);
      marker.setAttribute("aria-controls", "operation");
      item.append(marker);
    }
    return item;
  }));
  showStage(app.stage ?? (app.transitions.get(6)?.tone === "conflict" ? 6 : route[0][0]), app.connection || undefined);
}

function connectionStatus(link) {
  const issue = app.transitions.get(link.to);
  const stages = [app.stages.get(link.from), app.stages.get(link.to)];
  if (issue?.tone === "conflict" || stages[1].tone === "conflict") return {tone: "conflict", label: "Есть расхождения"};
  if (issue?.tone === "ambiguous") return {tone: "ambiguous", label: "Неоднозначность"};
  if (stages.some(stage => !stage.rows.length || stage.outside_period)) return {tone: "empty", label: "Недостаточно данных"};
  if (issue?.matching_slot) return {tone: "match", label: "Совпали поля"};
  return {tone: "candidate", label: "Кандидатская связь"};
}

function stageStatus(stage) {
  if (stage.outside_period) return `Вне периода · 0 в периоде, ${rowCount(stage.rows.length)} рядом`;
  return stage.rows.length ? `${labels[stage.tone]} · ${rowCount(stage.rows.length)}` : "0 строк";
}

function badge(tone) {
  const status = el("span", tone === "ambiguous" ? "Неоднозначность" : labels[tone], "record-status");
  status.dataset.tone = tone;
  return status;
}

function showStage(file, link = routeLinks.find(link => link.to === file) ?? routeLinks.find(link => link.from === file)) {
  app.stage = file;
  app.connection = link;
  for (const step of get("route").querySelectorAll(".step")) {
    if (Number(step.dataset.file) === file) step.setAttribute("aria-current", "step");
    else step.removeAttribute("aria-current");
  }
  for (const marker of get("route").querySelectorAll(".route-connection")) {
    marker.setAttribute("aria-pressed", String(Number(marker.dataset.link) === link.number));
  }
  const title = routeTitles.get(file);
  const stage = app.stages.get(file);
  const heading = stageHeading(stage, title);
  const operationTitle = heading.querySelector("h3");
  operationTitle.id = "operationTitle";
  operationTitle.tabIndex = -1;
  const panel = get("operation");
  panel.replaceChildren(heading);
  panel.append(transitionDetails(link, file));
  if (file === 6) {
    const norms = app.stages.get(5);
    const reference = el("details", undefined, "reference");
    reference.append(el("summary", `Нормы прессовки · справочник · ${rowCount(norms.rows.length)}`),
      sectionWithTable(norms, "Нормы прессовки"));
    panel.append(reference);
  }
  panel.append(stageBody(stage, title, link));
  positionHelp();
  get("status").textContent = `${title}. ${stageStatus(stage)}.`;
}

function sourceLink(link, label = link.label) {
  return button(label, event => openSource(link, event.currentTarget), "source-link");
}

function transitionDetails(link, file) {
  const {tone, label} = connectionStatus(link);
  const issue = app.transitions.get(link.to);
  const block = el("section", undefined, "transition");
  block.dataset.tone = tone;
  const path = el("div", undefined, "transition-path");
  const mark = el("span", link.number, "connection-mark");
  mark.dataset.tone = tone;
  mark.setAttribute("aria-hidden", "true");
  const other = file === link.from ? link.to : link.from;
  path.append(mark, el("h4", link.title), el("span", label, "connection-status"),
    helpButton(link.title, link.rule, issue?.help, connectionSources(link)),
    button(`К этапу «${routeTitles.get(other)}»`, () => {
      showStage(other, link);
      get("operationTitle").focus({preventScroll: true});
    }, "connection-jump"));
  if (!issue) {
    block.append(path, el("p", link.rule, "transition-text"));
    return block;
  }
  block.append(path, el("p", issue.title, "issue-title"));
  if (issue.count) block.append(el("p", `${rowCount(issue.count)} с расхождениями`, "transition-text"));
  if (issue.text) block.append(el("p", issue.text, "transition-text"));
  if (issue.left) {
    const evidence = el("div", undefined, "evidence");
    [issue.left, issue.right].forEach((text, index) => {
      const side = el("div", undefined, "evidence-side");
      const link = issue.links[index];
      const parts = text.split(" · ");
      side.append(el("span", parts[0], "evidence-label"), el("strong", parts[1]));
      if (parts[2]) side.append(el("small", parts[2]));
      const label = `XLS · строка ${link.row}`;
      const source = sourceLink(link, label);
      source.setAttribute("aria-label", `${label} · ${parts[0]}`);
      side.append(source);
      evidence.append(side);
    });
    block.append(evidence);
  }
  if (issue.missing) block.append(el("p", issue.missing, "transition-text"));
  if (!issue.left && issue.links.length) {
    const links = el("div", undefined, "source-links");
    for (const link of issue.links) {
      const source = sourceLink(link, `XLS · ${link.label}`);
      if (link.basis) {
        const item = el("div", undefined, "transition-example");
        item.append(source, el("p", link.basis, "transition-text"));
        links.append(item);
      } else {
        links.append(source);
      }
    }
    block.append(links);
  }
  return block;
}

function connectionSources(link) {
  return [link.from, link.to].map(file => app.stages.get(file).source).join(" → ");
}

function columnMarker(stage, index, link) {
  const field = stage.column_ids?.[index];
  if (!link) {
    const reference = referenceFields[stage.file];
    if (!reference?.columns.includes(field)) return;
    const marker = tooltipButton("i", "connection-mark", stage.columns[index], "Справочная сверка.", reference.rule);
    marker.dataset.tone = "candidate";
    marker.title = `Справочная сверка. ${reference.rule}`;
    return marker;
  }
  const fieldRule = link.fields[stage.file]?.[field];
  if (!fieldRule) return;
  const issue = app.transitions.get(link.to);
  const {tone, label} = connectionStatus(link);
  const conflict = issue?.field_conflicts?.[stage.file]?.includes(field);
  const status = label === "Совпали поля" ? "Совпали поля в части записей. Связь партий остаётся кандидатской." : `${label}.`;
  const evidence = issue?.text || issue?.help;
  const context = issue && [issue.title, evidence].filter(Boolean).join(". ");
  const marker = tooltipButton(link.number, "connection-mark", `Связь ${link.number} · ${link.title}`,
    status, fieldRule, link.rule, context, conflict && issue.left && `${issue.left} → ${issue.right}`, connectionSources(link));
  marker.title = [status, fieldRule, context].filter(Boolean).join("\n");
  marker.setAttribute("aria-label", `${stage.columns[index]}. Связь ${link.number}. ${label}`);
  marker.dataset.tone = tone === "conflict" && !conflict ? "candidate" : tone;
  if (conflict) marker.dataset.fieldConflict = "";
  return marker;
}

function stageHeading(stage, title, note) {
  const heading = el("div", undefined, "data-heading");
  heading.append(el("h3", title), helpButton(title, stageStatus(stage), note, stage.summary, commonBasis(stage)));
  return heading;
}

function sectionWithTable(stage, title, note) {
  const node = el("section", undefined, "data-section");
  node.append(stageHeading(stage, title, note), stageBody(stage, title));
  return node;
}

function commonBasis(stage) {
  const first = stage.rows[0];
  if (first && stage.rows.every(row => row.basis === first.basis && row.tone === first.tone)) return first.basis;
}

function sortKey(value) {
  if (value == null) return null;
  if (typeof value === "number") return {kind: 0, value};
  const text = String(value).trim();
  if (!text) return null;
  if (datePattern.test(text)) return {kind: 1, value: text};
  if (/^[+-]?\d+(?:[.,]\d+)?$/.test(text)) return {kind: 0, value: Number(text.replace(",", "."))};
  return {kind: 2, value: text};
}

function sortRows(rows, getValue, direction) {
  const factor = direction === "ascending" ? 1 : -1;
  return rows.map(row => ({row, key: sortKey(getValue(row))}))
    .sort(({key: a}, {key: b}) => {
      if (!a || !b) return Number(!a) - Number(!b);
      if (a.kind !== b.kind) return factor * (a.kind - b.kind);
      return factor * (a.kind === 0 ? a.value - b.value : sortText.compare(a.value, b.value));
    })
    .map(({row}) => row);
}

function addSortHeaders(table, columns, onSort) {
  const headers = table.createTHead().insertRow();
  let active;
  for (const {label, value, numeric, hint, marker} of columns) {
    const heading = el("th", undefined, numeric ? "measure" : undefined);
    heading.scope = "col";
    const control = button(label || "Без названия", () => {
      const next = heading.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
      active?.removeAttribute("aria-sort");
      heading.setAttribute("aria-sort", next);
      active = heading;
      onSort(value, next);
    }, "sort-button");
    const arrow = el("span", undefined, "sort-arrow");
    arrow.setAttribute("aria-hidden", "true");
    control.append(arrow);
    if (hint) control.title = hint;
    if (marker) {
      const contents = el("div", undefined, "marked-header");
      contents.append(control, marker);
      heading.append(contents);
    } else {
      heading.append(control);
    }
    headers.append(heading);
  }
}

function stageBody(stage, title, link) {
  const panel = el("section", undefined, "stage-body");
  if (!stage.rows.length) {
    panel.append(el("p", "По выбранным фильтрам строк нет.", "muted"));
    return panel;
  }
  const sharedBasis = commonBasis(stage);
  const showRowTone = !link || (!stage.outside_period && stage.rows.some(row => row.tone !== stage.tone));
  const markIndex = stage.columns.findIndex(label => /^Доп\.? марка$/i.test(label));

  const container = el("div", undefined, "table-wrap");
  container.tabIndex = 0;
  container.setAttribute("role", "region");
  container.setAttribute("aria-label", `${title}, таблица исходных записей`);
  const table = el("table", undefined, "records");
  const numeric = stage.columns.map(label => /%|\s(?:шт|тн)\.?$|^Часы /u.test(label));
  const columns = [
    {label: "Строка XLS", value: row => row.row},
    ...stage.columns.map((label, index) => ({
      label, value: row => row.values[index], numeric: numeric[index], marker: columnMarker(stage, index, link),
    })),
  ];
  if (!sharedBasis) {
    columns.push(showRowTone
      ? {label: "Сопоставление", value: row => labels[stage.outside_period ? "outside" : row.tone]}
      : {label: "Подбор", value: row => row.basis, hint: "Сортировать по пояснению подбора"});
  }
  const body = table.createTBody();
  container.append(table);
  panel.append(container);

  let orderedRows = stage.rows;
  let shown = 0;
  const more = button("Показать ещё строки", () => appendRows(true), "quiet show-more");
  addSortHeaders(table, columns, (getValue, direction) => {
    orderedRows = sortRows(stage.rows, getValue, direction);
    const visibleCount = shown;
    body.replaceChildren();
    shown = 0;
    appendRows(false, visibleCount);
    positionHelp();
  });
  function appendRows(focus = false, count = 25) {
    const batch = orderedRows.slice(shown, shown + count);
    let firstLink;
    for (const row of batch) {
      const tr = body.insertRow();
      const link = sourceLink({file: stage.file, month: row.month, row: row.row}, String(row.row));
      link.setAttribute("aria-label", `Строка ${row.row} · ${row.sheet}`);
      firstLink ||= link;
      const source = tr.insertCell();
      source.append(link);
      if (row.month !== app.month) source.append(el("small", row.sheet));
      for (const [index, value] of row.values.entries()) {
        const cell = tr.insertCell();
        if (index === markIndex) cell.className = "recipe-mark";
        if (numeric[index]) cell.className = "measure";
        if (datePattern.test(value)) {
          const time = el("time", visValue(value));
          time.dateTime = value;
          cell.append(time);
        } else {
          cell.textContent = visValue(value);
        }
      }
      if (!sharedBasis) {
        const cell = tr.insertCell();
        cell.className = "basis";
        const tone = stage.outside_period ? "outside" : row.tone;
        if (showRowTone) cell.append(badge(tone));
        cell.append(helpButton(`Строка ${row.row} · ${labels[tone]}`, row.basis));
      }
    }
    shown += batch.length;
    more.hidden = shown === stage.rows.length;
    more.textContent = `Показать ещё · ${shown} из ${stage.rows.length}`;
    if (focus) firstLink?.focus();
  }
  appendRows();
  panel.append(more);
  return panel;
}

async function openSource(ref, trigger) {
  const ticket = ++app.sourceRequest;
  sourceTrigger = trigger;
  get("sourceTitle").textContent = "Исходная строка";
  get("sourceBody").replaceChildren(el("p", "Загрузка…"));
  get("sourceBody").scrollTop = 0;
  if (!sourceDialog.open) sourceDialog.showModal();
  try {
    const record = await api("/api/source", {file: ref.file, month: ref.month, row: ref.row});
    if (ticket !== app.sourceRequest) return;
    get("sourceTitle").textContent = `Строка ${record.row} · ${record.sheet}`;
    const table = el("table", undefined, "source-table");
    const body = table.createTBody();
    function renderFields(fields) {
      body.replaceChildren();
      for (const {name, value} of fields) {
        const field = el("th", name || "Без названия");
        field.scope = "row";
        body.insertRow().append(field, el("td", visValue(value)));
      }
    }
    addSortHeaders(table, [{label: "Поле", value: field => field.name}, {label: "Значение", value: field => field.value}],
      (getValue, direction) => renderFields(sortRows(record.columns, getValue, direction)));
    renderFields(record.columns);
    get("sourceBody").replaceChildren(el("p", record.file, "file-name"), table);
  } catch (error) {
    if (ticket === app.sourceRequest) get("sourceBody").replaceChildren(el("p", error.message));
  }
}

sourceDialog.addEventListener("close", () => {
  if (sourceDialog.open) return;
  ++app.sourceRequest;
  sourceTrigger?.focus({preventScroll: true});
  sourceTrigger = null;
});

const tabs = [...get("views").querySelectorAll('[role="tab"]')];

function setView(id) {
  for (const tab of tabs) {
    const active = tab.id === id;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    get(tab.getAttribute("aria-controls")).hidden = !active;
  }
}

get("views").addEventListener("click", event => {
  if (tabs.includes(event.target)) setView(event.target.id);
});
get("views").addEventListener("keydown", event => {
  const index = tabs.indexOf(event.target);
  if (index === -1) return;
  const destination = {
    ArrowLeft: (index + tabs.length - 1) % tabs.length,
    ArrowRight: (index + 1) % tabs.length,
    Home: 0, End: tabs.length - 1,
  }[event.key];
  if (destination === undefined) return;
  event.preventDefault();
  const tab = tabs[destination];
  setView(tab.id);
  tab.focus();
});

get("month").addEventListener("change", () => {
  renderOrderSheet();
  renderOrders();
});
get("orderSearch").addEventListener("input", () => renderOrders());
get("orderMode").addEventListener("change", () => renderOrders());
get("searchForm").addEventListener("submit", async event => {
  event.preventDefault();
  const results = await renderOrders();
  if (!results) return;
  const match = results.find(o => String(o.row) === get("orderSearch").value.trim());
  const order = match || (results.length === 1 && results[0]);
  if (order) selectOrder(get("month").value, order);
  else get("orders").querySelector("button")?.focus();
});
get("filters").addEventListener("submit", event => {
  event.preventDefault();
  loadTrace();
});
get("recipeLabel").append(helpButton("Версия шихты",
  "Версии сгруппированы по сроку действия и совпадению доп. марки заказа. Технологическая допустимость требует подтверждения."));
get("orderModeLabel").append(helpButton("Отбор заказов",
  "Оценка за весь выбранный месяц, по обеим сменам и при автоматическом выборе шихты. В оба режима отбора входят заказы с подходящими записями подачи, дозирования и прессовки.",
  "Выше заказы с большим числом этапов, где есть хотя бы одна запись без расхождения. При равенстве учитываются число этапов с расхождениями, неоднозначность и совпадение шихты, даты и смены в дозировании и прессовке.",
  "Записи подачи подбираются по компоненту и дате. Для подтверждения переходов нужна связь между партиями."));
get("openOrder").addEventListener("click", event =>
  openSource({file: 1, month: app.month, row: app.order.row}, event.currentTarget));
function initOrdersPane() {
  const workspace = get("workspace");
  const pane = get("ordersPane");
  const resizer = get("ordersResizer");
  const toggle = get("toggleOrders");
  const picker = get("orderPicker");
  const list = get("orders");
  const storageKey = "trace-viewer.orders-width";
  const minWidth = 200;
  let preferredWidth;
  let drag;
  let orderScroll = 0;

  try {
    const savedWidth = Number(localStorage.getItem(storageKey));
    if (Number.isFinite(savedWidth) && savedWidth >= minWidth) preferredWidth = savedWidth;
  } catch {
    // Resizing is available even when the browser blocks storage.
  }

  function maxWidth() {
    return Math.max(minWidth, Math.min(520, Math.floor(workspace.clientWidth * 0.4)));
  }

  function limitWidth(value) {
    return Math.max(minWidth, Math.min(maxWidth(), Math.round(value)));
  }

  function updateWidth() {
    const defaultWidth = window.innerWidth <= 1240 ? 224 : 252;
    const width = limitWidth(preferredWidth ?? defaultWidth);
    workspace.style.setProperty("--orders-width", `${width}px`);
    resizer.setAttribute("aria-valuemax", maxWidth());
    resizer.setAttribute("aria-valuenow", width);
    resizer.setAttribute("aria-valuetext", `${width} пикс.`);
    positionHelp();
  }

  function rememberWidth() {
    if (preferredWidth === undefined) return;
    try {
      localStorage.setItem(storageKey, String(preferredWidth));
    } catch {
      // The current width is still kept for this page.
    }
  }

  resizer.setAttribute("aria-valuemin", minWidth);
  resizer.addEventListener("pointerdown", event => {
    if (!event.isPrimary || event.button !== 0) return;
    event.preventDefault();
    resizer.focus({preventScroll: true});
    drag = {id: event.pointerId, x: event.clientX, width: pane.getBoundingClientRect().width};
    resizer.setPointerCapture(drag.id);
    workspace.dataset.ordersResizing = "";
  });
  resizer.addEventListener("pointermove", event => {
    if (event.pointerId !== drag?.id) return;
    preferredWidth = limitWidth(drag.width + event.clientX - drag.x);
    updateWidth();
  });
  resizer.addEventListener("lostpointercapture", event => {
    if (event.pointerId !== drag?.id) return;
    drag = undefined;
    delete workspace.dataset.ordersResizing;
    rememberWidth();
  });
  resizer.addEventListener("keydown", event => {
    const width = Number(resizer.getAttribute("aria-valuenow"));
    const sizes = {ArrowLeft: width - 16, ArrowRight: width + 16, Home: minWidth, End: maxWidth()};
    const size = sizes[event.key];
    if (size === undefined) return;
    event.preventDefault();
    preferredWidth = limitWidth(size);
    updateWidth();
    rememberWidth();
  });
  toggle.addEventListener("click", () => {
    const collapsed = !picker.hidden;
    if (collapsed) orderScroll = list.scrollTop;
    if (drag && resizer.hasPointerCapture(drag.id)) resizer.releasePointerCapture(drag.id);
    picker.hidden = resizer.hidden = collapsed;
    workspace.toggleAttribute("data-orders-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.title = collapsed ? "Раскрыть панель заказов" : "Свернуть панель заказов";
    toggle.setAttribute("aria-label", toggle.title);
    if (!collapsed) list.scrollTop = orderScroll;
    positionHelp();
  });

  window.addEventListener("resize", updateWidth);
  updateWidth();
}

async function init() {
  try {
    app.months = await api("/api/months");
    get("month").append(...app.months.map(m => new Option(m.label, m.id)));
    const defaultMonth = app.months.some(m => m.id === "2022-03") ? "2022-03" : app.months[0].id;
    get("month").value = defaultMonth;
    const orders = await ordersFor(defaultMonth);
    const initialOrder = defaultMonth === "2022-03" && orders.find(o => o.row === 145);
    if (!orders.length) throw new Error("На этом листе нет заказов.");
    await Promise.all([
      selectOrder(defaultMonth, initialOrder || orders[0], false),
      renderOrders(true),
    ]);
  } catch (error) {
    get("orderTitle").textContent = "Заказ не выбран";
    get("main").setAttribute("aria-busy", "false");
    report(error.message);
  }
}

initOrdersPane();
init();
