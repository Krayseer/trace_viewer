import {el, formatNumber, get, initTabs} from "./viewer_ui.js";

const examplesPath = "/api/planning/examples";
const protectedExamples = ["march_subset_scenario", "may_integration_scenario"];
const percent = new Intl.NumberFormat("ru-RU", {style: "percent", maximumFractionDigits: 2});
const assumptionLabels = [
  ["horizon", "Горизонт"],
  ["consumption_basis", "База расхода"],
  ["volume_source", "Источник объёмов"],
  ["score_scale", "Шкала оценки"],
  ["scores_source", "Источник оценок"],
  ["limits_source", "Источник лимитов"],
];
const statuses = {
  optimal: ["План найден. Решатель завершил поиск.", "success"],
  feasible_not_proven_optimal: ["Допустимый план найден. Оптимальность не доказана.", "success"],
  proven_infeasible: ["При заданных лимитах допустимого плана нет.", "warning"],
  no_plan_within_limit: ["За отведённое время допустимый план не найден.", "warning"],
  solver_invalid_plan: ["Решение не прошло независимую проверку.", "error"],
  solver_failure: ["Решатель завершился с ошибкой.", "error"],
};

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Не удалось получить данные.");
  return data;
}

function table(headers, rows) {
  const node = el("table");
  const header = node.createTHead().insertRow();
  for (const label of headers) {
    const cell = el("th", label);
    cell.scope = "col";
    header.append(cell);
  }
  const body = node.createTBody();
  for (const cells of rows) body.insertRow().append(...cells);
  return node;
}

function exact(node, value, formatter = formatNumber) {
  node.dataset.exact = String(value ?? "null");
  node.removeAttribute("title");
  if (value == null) {
    node.textContent = "–";
  } else {
    node.textContent = formatter.format(value);
    node.title = String(value);
  }
  return node;
}

function measurement(value, formatter) {
  return exact(el("td", undefined, "measure"), value, formatter);
}

function resourceLimit(row) {
  const cell = measurement(row.limit_tonnes);
  if (row.edited) {
    const badge = el("small", "Изменён", "muted");
    badge.title = row.source;
    cell.append(badge);
  }
  return cell;
}

function resourceUsage(row) {
  const value = exact(el("span"), row.utilization, percent);
  const cell = el("td", undefined, "planning-utilization");
  cell.append(value);
  if (row.utilization == null) return cell;
  const track = el("span", undefined, "planning-track");
  const fill = el("span");
  fill.style.width = `${Math.max(0, Math.min(100, row.utilization * 100))}%`;
  track.append(fill);
  track.setAttribute("aria-hidden", "true");
  cell.append(track);
  if (row.bottleneck) {
    cell.dataset.bottleneck = "";
    const badge = el("span", "Узкое место", "record-status");
    badge.dataset.tone = "ambiguous";
    cell.append(badge);
  }
  return cell;
}

function fact(label, value) {
  const group = el("div");
  group.append(el("dt", label), el("dd", value));
  return group;
}

function numberField(label, value, allowZero) {
  const input = el("input");
  input.type = "number";
  input.min = "0";
  input.step = "any";
  input.value = value ?? "";
  input.dataset.original = input.value;
  input.dataset.allowZero = String(allowZero);
  input.setAttribute("aria-label", label);
  return input;
}

function positiveNumber(input, allowZero = false) {
  const value = input.valueAsNumber;
  if (!Number.isFinite(value) || value < 0 || (!allowZero && value === 0)) {
    const error = new Error(`Задайте ${allowZero ? "неотрицательное" : "положительное"} число. ${input.getAttribute("aria-label") || "Лимит решателя, с"}.`);
    error.input = input;
    throw error;
  }
  return value;
}

function edits(container) {
  const values = Object.create(null);
  for (const input of container.querySelectorAll('input[data-touched="true"]')) {
    const value = positiveNumber(input, input.dataset.allowZero === "true");
    if (value !== Number(input.dataset.original) || !input.dataset.original) values[input.dataset.id] = value;
  }
  return values;
}

function isRecord(value) {
  return value != null && typeof value === "object" && !Array.isArray(value);
}

export function initPlanning({usesWorkbooks}) {
  const form = get("planningForm");
  const fields = [...form.querySelectorAll("fieldset")];
  const examples = [...get("planningExamples").querySelectorAll("[data-example]")];
  const file = get("planningFile");
  const submit = get("planningSolve");
  const orders = get("planningOrders");
  const limits = get("planningLimits");
  const content = get("planningContent");
  const overview = get("planningOverview");
  const basis = get("planningBasis");
  const planOutput = get("planningPlanOutput");
  const resourcesOutput = get("planningResourcesOutput");
  const error = get("planningError");
  const lockNote = get("planningAccessNote");
  const setView = initTabs(get("planningViews"));
  let source, worker, workbookApi;
  let opened = false;

  function setStatus(message, tone = "") {
    const node = get("planningStatus");
    node.textContent = message;
    node.dataset.tone = tone;
  }

  function report(message = "") {
    error.textContent = message;
    error.hidden = !message;
  }

  function hideResult() {
    planOutput.hidden = resourcesOutput.hidden = true;
    get("planningAssigned").textContent = "–";
    exact(get("planningObjective"), null);
  }

  async function run(action) {
    if (fields[0].disabled) return false;
    const previousFocus = document.activeElement;
    let invalidInput;
    for (const fieldset of fields) fieldset.disabled = true;
    content.setAttribute("aria-busy", "true");
    hideResult();
    report();
    try {
      await action();
      return true;
    } catch (failure) {
      invalidInput = failure.input;
      report(failure.message);
      setStatus("Расчёт не выполнен.");
      return false;
    } finally {
      for (const fieldset of fields) fieldset.disabled = false;
      submit.disabled = !source;
      content.setAttribute("aria-busy", "false");
      if (invalidInput) {
        const panel = invalidInput.closest(".planning-view");
        if (panel) setView(panel.getAttribute("aria-labelledby"));
        invalidInput.focus();
      } else if (document.activeElement === document.body && form.contains(previousFocus)) {
        previousFocus.focus({preventScroll: true});
      }
    }
  }

  function showSource(instance) {
    if (!isRecord(instance) || !isRecord(instance.components) || !Array.isArray(instance.orders)
        || instance.orders.some(order => !isRecord(order) || typeof order.id !== "string")
        || !["synthetic", "scenario"].includes(instance.kind)) {
      throw new Error("Нужен полный сценарий JSON с массивом заказов, лимитами компонентов и типом scenario или synthetic.");
    }
    source = instance;
    basis.textContent = source.kind === "scenario"
      ? "Лимиты и оценки заданы для сценария. Фактические запасы и качество требуют подтверждения."
      : "Расчёт на синтетических данных.";
    get("planningOrderCount").textContent = formatNumber.format(source.orders.length);
    get("planningComponentCount").textContent = formatNumber.format(Object.keys(source.components).length);
    overview.hidden = basis.hidden = content.hidden = false;
    const assumptions = assumptionLabels.map(([key, label]) => fact(label, source[key] ?? "Не задано"));
    assumptions.push(fact("Пересчёт при изменении объёма", "Расход и оценка варианта масштабируются пропорционально объёму заказа."));
    get("planningAssumptions").replaceChildren(...assumptions);
    orders.replaceChildren(table(["Заказ", "Объём, т", "Вариантов"], source.orders.map(order => {
      const volume = numberField(`Объём заказа ${order.id}, т`, order.volume_tonnes, false);
      volume.dataset.id = order.id;
      const cell = el("td", undefined, "planning-input-cell");
      cell.append(volume);
      const count = Array.isArray(order.allowed_versions) ? order.allowed_versions.length : null;
      return [el("td", order.id), cell, measurement(count)];
    })));
    const sourcesByDescription = new Map();
    limits.replaceChildren(table(["Компонент", "Лимит, т"], Object.entries(source.components).map(([id, value]) => {
      const description = source.component_sources?.[id] ?? "Не задан";
      if (!sourcesByDescription.has(description)) sourcesByDescription.set(description, []);
      sourcesByDescription.get(description).push(id);
      const limit = numberField(`Лимит компонента ${id}, т`, value, true);
      limit.dataset.id = id;
      const cell = el("td", undefined, "planning-input-cell");
      cell.append(limit);
      return [el("td", id), cell];
    })));
    get("planningLimitSources").replaceChildren(table(
      ["Компоненты", "Источник лимита"],
      Array.from(sourcesByDescription, ([description, components]) => [
        el("td", components.join(", ")), el("td", description),
      ]),
    ));
  }

  async function solveInBrowser(body) {
    worker ??= new Worker(new URL("./viewer_planning_worker.js", import.meta.url), {type: "module"});
    try {
      const [code, data] = await new Promise((resolve, reject) => {
        worker.onmessage = event => resolve(event.data);
        worker.onerror = () => {
          worker.terminate();
          worker = undefined;
          reject(new Error("Не удалось запустить расчётное ядро в браузере."));
        };
        worker.postMessage(body);
      });
      if (code === 200) return data;
      if (code >= 500) {
        worker.terminate();
        worker = undefined;
      }
      throw new Error(data.error);
    } finally {
      if (worker) worker.onmessage = worker.onerror = null;
    }
  }

  function renderResult(data) {
    const hasPlan = Array.isArray(data.plan) && data.independent_validation?.valid === true;
    const [message, tone] = statuses[data.status] ?? statuses.solver_failure;
    setStatus(message, tone);
    get("planningAssigned").textContent = hasPlan ? `${formatNumber.format(data.plan.length)} из ${formatNumber.format(source.orders.length)}` : "–";
    exact(get("planningObjective"), data.objective);
    const coverage = hasPlan ? "Все назначения и лимиты проверены" : "Допустимый план отсутствует";
    const metrics = [
      ["Верхняя граница, баллы", data.upper_bound],
      ["Относительный разрыв", data.mip_gap, percent],
      ["Решение и проверка, с", data.total_seconds],
    ];
    get("planningSummary").replaceChildren(fact("Независимая проверка", coverage), ...metrics.map(([label, value, formatter]) => {
      const group = fact(label);
      exact(group.lastElementChild, value, formatter);
      return group;
    }));
    get("planningSolverMessage").textContent = data.solver_message;
    get("planningPlanSection").hidden = !hasPlan;
    if (hasPlan) {
      get("planningPlan").replaceChildren(table(["Заказ", "Версия шихты", "Объём, т", "Вклад в цель"], data.plan.map(row => [
        el("td", row.order_id), el("td", row.version_id), measurement(row.volume_tonnes), measurement(row.score),
      ])));
    }
    get("planningResources").replaceChildren(table(
      ["Компонент", "Расход, т", "Лимит, т", "Остаток, т", "Загрузка"],
      data.resources.map(row => [
        el("td", row.component), measurement(row.used_tonnes), resourceLimit(row), measurement(row.slack_tonnes),
        resourceUsage(row),
      ]),
    ));
    planOutput.hidden = resourcesOutput.hidden = false;
  }

  async function recalculate() {
    setStatus("Выполняется расчёт…");
    const body = JSON.stringify({
      instance: source,
      volume_overrides_tonnes: edits(orders),
      limit_overrides_tonnes: edits(limits),
      time_limit_seconds: positiveNumber(get("planningSeconds")),
    });
    const data = usesWorkbooks ? await solveInBrowser(body) : await requestJson("/api/planning/solve", {
      method: "POST", headers: {"Content-Type": "application/json"}, body,
    });
    renderResult(data);
  }

  async function loadScenario(title, load, selected) {
    source = undefined;
    overview.hidden = basis.hidden = content.hidden = true;
    get("planningTitle").textContent = title;
    for (const example of examples) {
      if (example === selected) example.setAttribute("aria-current", "true");
      else example.removeAttribute("aria-current");
    }
    setStatus("Загружается сценарий…");
    showSource(await load());
    await recalculate();
  }

  function loadExample(name) {
    if (!usesWorkbooks) return requestJson(`${examplesPath}/${name}`);
    if (protectedExamples.includes(name)) return workbookApi(`${examplesPath}/${name}`);
    return requestJson(new URL(`./planning_examples/${name}.json`, import.meta.url));
  }

  function updateWorkbookAccess() {
    lockNote.hidden = !usesWorkbooks || Boolean(workbookApi);
    for (const example of examples) {
      if (protectedExamples.includes(example.dataset.example)) example.disabled = !workbookApi;
    }
  }

  function chooseExample(example) {
    return loadScenario(example.textContent, () => loadExample(example.dataset.example), example);
  }

  if (usesWorkbooks) updateWorkbookAccess();
  for (const example of examples) example.addEventListener("click", () => run(() => chooseExample(example)));
  get("planningImport").addEventListener("click", () => file.click());
  file.addEventListener("change", () => {
    const selected = file.files[0];
    if (!selected) return;
    file.value = "";
    run(() => loadScenario(selected.name, async () => {
      try {
        return JSON.parse(await selected.text());
      } catch {
        throw new Error("Не удалось прочитать файл сценария как JSON.");
      }
    }));
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (source && await run(recalculate)) {
      setView("planningTabPlan");
      if (!form.closest("[hidden]")) get("planningTabPlan").focus();
    }
  });
  form.addEventListener("input", event => {
    if (event.target.type !== "number" || !source) return;
    event.target.dataset.touched = "true";
    hideResult();
    report();
    setStatus("Параметры изменены. Пересчитайте план.");
  });

  return {
    open() {
      if (opened) return;
      opened = true;
      run(async () => {
        if (!usesWorkbooks) {
          const {examples: available} = await requestJson(examplesPath);
          for (const example of examples) example.disabled = !available.includes(example.dataset.example);
        }
        const initial = examples.find(example => !example.disabled);
        if (!initial) throw new Error("Загрузите сценарий JSON.");
        await chooseExample(initial);
      });
    },
    setWorkbookApi(api) {
      workbookApi = api;
      updateWorkbookAccess();
    },
  };
}
