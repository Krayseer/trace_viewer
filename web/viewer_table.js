import {badge, button, datePattern, el, helpButton, labels, positionHelp, sortText, visValue} from "./viewer_ui.js";

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

function stageBody(stage, title, {orderMonth, sourceLink, markColumn, routeStage}) {
  const panel = el("section", undefined, "stage-body");
  if (!stage.rows.length) {
    panel.append(el("p", "По выбранным фильтрам строк нет.", "muted"));
    return panel;
  }
  const sharedBasis = commonBasis(stage);
  const showRowTone = !routeStage || (!stage.outside_period && stage.rows.some(row => row.tone !== stage.tone));
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
      label, value: row => row.values[index], numeric: numeric[index], marker: markColumn(index),
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
      if (row.month !== orderMonth) source.append(el("small", row.sheet));
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

export {addSortHeaders, commonBasis, sortRows, stageBody};
