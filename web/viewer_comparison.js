import {el, formatNumber, get, initTabs} from "./viewer_ui.js";

const methods = {
  fast: ["Быстрый алгоритм", "Выбор по баллам, устранение перегрузок, улучшение плана"],
  cold: ["Холодный MILP", "HiGHS без начального плана"],
  warm: ["MILP с тёплым стартом", "HiGHS с проверенным планом быстрого алгоритма"],
};
const statuses = {
  optimal: "Оптимум по допуску решателя",
  feasible_not_proven_optimal: "Допустимый план",
  proven_infeasible: "Несовместность доказана",
  no_plan_within_limit: "План не найден",
  no_valid_plan_from_solver: "Решатель не вернул допустимый план",
  no_warm_start: "Начальный план не найден",
  invalid_plan: "План отклонён проверкой",
};
const metricNumber = new Intl.NumberFormat("ru-RU", {maximumFractionDigits: 6});
const units = value => value == null ? "—" : metricNumber.format(value);
const signed = value => (value > 0 ? "+" : "") + units(value);

async function readJson(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || "Не удалось получить данные сравнения.");
  }
  return response.json();
}

function table(headers, rows) {
  const node = el("table");
  const head = node.createTHead().insertRow();
  headers.forEach(label => {
    const cell = el("th", label);
    cell.scope = "col";
    head.append(cell);
  });
  const body = node.createTBody();
  for (const values of rows) {
    const row = body.insertRow();
    for (const [column, value] of values.entries()) {
      const cell = el(column === 0 ? "th" : "td");
      if (column === 0) cell.scope = "row";
      else cell.dataset.label = headers[column];
      cell.append(value);
      row.append(cell);
    }
  }
  return node;
}

function methodCell(result) {
  const [name, info] = methods[result.method];
  const cell = el("div", name, "comparison-method");
  cell.append(el("small", info));
  if (result.repair_moves != null) {
    cell.append(el("small", `Исправления перегрузок — ${result.repair_moves} · улучшения — ${result.improvement_moves}`));
  }
  return cell;
}

function timeCell(result, max, budget) {
  const cell = el("div", units(result.seconds), "comparison-time");
  if (max > 0 && result.seconds != null) {
    const track = el("span", undefined, "comparison-track");
    const bar = el("span");
    bar.style.width = `${Math.min(100, 100 * result.seconds / max)}%`;
    track.append(bar);
    track.setAttribute("aria-hidden", "true");
    cell.append(track);
  }
  if (result.seconds > budget) cell.append(el("small", "Превышен бюджет"));
  return cell;
}

function planDetails(result) {
  const details = el("details", undefined, "comparison-detail");
  details.append(el("summary", methods[result.method][0]));
  details.addEventListener("toggle", () => {
    if (!details.open || details.children.length > 1) return;
    const plan = el("div", undefined, "table-wrap");
    plan.tabIndex = 0;
    plan.setAttribute("role", "region");
    plan.setAttribute("aria-label", "Назначения рецептур");
    plan.append(table(["Заказ", "Рецептура"], result.plan.map(row => [row.order_id, row.version_id])));
    const resources = el("div", undefined, "table-wrap");
    resources.tabIndex = 0;
    resources.setAttribute("role", "region");
    resources.setAttribute("aria-label", "Расход компонентов");
    resources.append(table(["Компонент", "Расход, т", "Лимит, т", "Остаток, т"],
      Object.entries(result.resources).map(([id, resource]) =>
        [id, units(resource.used_tonnes), units(resource.limit_tonnes), units(resource.slack_tonnes)])));
    details.append(el("h3", "Назначения рецептур"), plan, el("h3", "Расход компонентов"), resources);
  });
  return details;
}

function initComparison({usesWorkbooks}) {
  const dataset = get("comparisonDataset");
  const repeat = get("comparisonRepeat");
  const input = get("comparisonInput");
  const file = get("comparisonFile");
  const status = get("comparisonStatus");
  const error = get("comparisonError");
  const form = get("comparisonForm");
  const resultPanel = get("comparisonResult");
  let archive;
  let liveResult;
  let liveError = "";
  let archiveError = "";
  let mode = "archive";
  let archiveLoading = false;
  let running = false;

  function render() {
    const saved = mode === "archive";
    const benchmark = archive?.datasets.find(item => item.id === dataset.value);
    const pair = benchmark?.repeats.find(item => item.repeat === Number(repeat.value));
    const result = saved ? (pair && {...benchmark, methods: pair.methods}) : liveResult;
    const message = saved ? archiveError : liveError;
    const loading = saved ? archiveLoading : running;
    error.textContent = message;
    error.hidden = !message;
    status.textContent = saved ? "Загружаю сохранённые результаты…" : "Выполняю три метода последовательно…";
    status.hidden = !loading;
    resultPanel.hidden = !result;
    if (!result) return;

    const {orders, options, components, budget} = result;
    const description = saved
      ? `Повтор ${repeat.value} из ${benchmark.repeats.length} · ${archive.date.split("-").reverse().join(".")} · ${archive.environment}`
      : `${result.id} · ${result.kind === "synthetic" ? "синтетический вход" : "вход из JSON"}`;
    get("comparisonContext").textContent = [
      description, `${formatNumber.format(orders)} заказов`, `${formatNumber.format(options)} вариантов`,
      `${formatNumber.format(components)} компонентов`, `${units(budget)} с на метод`,
    ].join(" · ");
    const max = Math.max(...result.methods.map(method => method.seconds ?? 0));
    get("comparisonMetrics").replaceChildren(table(
      ["Метод", "Результат", "Назначено", "Цель", "Полное время, с", "Первый проверенный план, с", "Первое событие HiGHS, с", "Разрыв, %", "Тёплый старт"],
      result.methods.map(method => [
        methodCell(method), statuses[method.status] || method.status,
        method.assigned == null ? "—" : `${method.assigned} из ${orders}`,
        units(method.objective), timeCell(method, max, budget), units(method.first_verified_seconds),
        units(method.first_solver_event_seconds), units(method.gap == null ? null : method.gap * 100),
        method.start_accepted === true ? "Принят"
          : method.start_accepted === false ? "Передан · принятие не подтверждено" : "—",
      ]),
    ));
    const cold = result.methods.find(item => item.method === "cold");
    const warm = result.methods.find(item => item.method === "warm");
    const summary = get("comparisonSummary");
    summary.hidden = cold.objective == null || warm.objective == null;
    if (!summary.hidden) {
      const difference = warm.objective - cold.objective;
      const goal = Math.abs(difference) < 1e-7 ? "Итоговые цели совпали" : `Изменение цели ${signed(difference)}`;
      summary.textContent = `${goal}. Разница времени тёплого и холодного запуска ${signed(warm.seconds - cold.seconds)} с.`;
    }
    get("comparisonDetails").replaceChildren(...result.methods.filter(method => method.plan).map(planDetails));
  }

  async function open() {
    if (archive || archiveLoading) return;
    archiveLoading = true;
    archiveError = "";
    render();
    try {
      archive = await readJson("./comparison_runs.json");
    } catch (failure) {
      archiveError = failure.message;
    } finally {
      archiveLoading = false;
      render();
    }
  }

  initTabs(get("comparisonModes"), tab => {
    mode = tab === "comparisonArchiveTab" ? "archive" : "live";
    render();
  });
  form.hidden = usesWorkbooks;
  get("comparisonStaticNote").hidden = !usesWorkbooks;
  dataset.addEventListener("change", render);
  repeat.addEventListener("change", render);
  input.addEventListener("change", () => {
    get("comparisonFileLabel").hidden = input.value !== "file";
    file.required = input.value === "file";
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (running || usesWorkbooks) return;
    const fields = [...form.elements];
    running = true;
    liveError = "";
    liveResult = undefined;
    fields.forEach(field => { field.disabled = true; });
    render();
    try {
      const instance = input.value === "file"
        ? JSON.parse(await file.files[0].text())
        : await readJson(`./api/planning/examples/${input.value}`);
      liveResult = await readJson("./api/comparison/run", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({instance, budget: get("comparisonBudget").valueAsNumber}),
      });
    } catch (failure) {
      liveError = failure instanceof SyntaxError ? "Файл сценария должен содержать корректный JSON." : failure.message;
    } finally {
      running = false;
      fields.forEach(field => { field.disabled = false; });
      render();
    }
  });
  return {open};
}

export {initComparison};
