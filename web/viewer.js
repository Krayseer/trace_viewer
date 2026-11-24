import {
  badge, button, el, formatNumber, get, helpButton, labels, plural, positionHelp, rowCount, tooltipButton, visValue,
} from "./viewer_ui.js";
import {addSortHeaders, commonBasis, sortRows, stageBody} from "./viewer_table.js";
import {initOrdersPane} from "./viewer_orders_panel.js";
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
const sourceDialog = get("sourceDialog");
let sourceTrigger = null;
let workbookApi;

async function api(path, query) {
  if (workbookApi) return workbookApi(path, query);
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
  get("orderTitle").textContent = o.name.trim() || (o.product ? `Изделие ${o.product}` : "Наименование отсутствует");
  get("orderProduct").textContent = visValue(o.product);
  get("orderRaw").textContent = visValue(o.raw);
  get("orderMass").textContent = visValue(o.mass);
  get("orderMark").textContent = o.mark || "—";
  get("orderBase").textContent = typeof o.base === "number" ? `${formatNumber.format(o.base)} т` : visValue(o.base);
  get("orderExtra").textContent = typeof o.extra === "number" ? `${formatNumber.format(o.extra)} т` : visValue(o.extra);
  get("orderExtraField").hidden = o.extra === 0 || o.extra === "" || o.extra == null;
  get("orderFacts").hidden = false;
  const sourceButton = get("openOrder");
  sourceButton.textContent = `Строка XLS · ${o.row}`;
  sourceButton.hidden = false;
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
    get("status").textContent = "Маршрут заказа обновлён";
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
  panel.append(renderTable(stage, title, link));
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
  node.append(stageHeading(stage, title, note), renderTable(stage, title));
  return node;
}

function renderTable(stage, title, link) {
  return stageBody(stage, title, {
    orderMonth: app.month, sourceLink, markColumn: index => columnMarker(stage, index, link), routeStage: Boolean(link),
  });
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
get("openOrder").addEventListener("click", event =>
  openSource({file: 1, month: app.month, row: app.order.row}, event.currentTarget));

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

function initWorkbookAccess() {
  const form = get("unlockBooks");
  const key = get("workbookKey");
  const submit = get("unlockButton");
  const search = [...get("searchForm").elements];
  form.hidden = false;
  for (const control of search) control.disabled = true;
  get("orderTitle").textContent = "Маршрут заказа";
  get("main").setAttribute("aria-busy", "false");

  form.addEventListener("submit", async event => {
    event.preventDefault();
    const value = key.value.trim();
    key.disabled = submit.disabled = true;
    submit.textContent = "Открываю XLS…";
    report();
    try {
      const {openWorkbookApi} = await import("./viewer_workbooks.js");
      workbookApi = await openWorkbookApi(value);
    } catch (error) {
      report(error.message);
      key.disabled = submit.disabled = false;
      submit.textContent = "Открыть";
      key.select();
      return;
    }
    key.value = "";
    form.hidden = true;
    for (const control of search) control.disabled = false;
    await init();
  });
}

initOrdersPane();
if (document.documentElement.dataset.source === "workbooks") initWorkbookAccess();
else init();
