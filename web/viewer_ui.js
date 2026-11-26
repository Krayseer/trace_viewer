const get = id => document.getElementById(id);
const labels = {
  empty: "Нет строк", match: "Совпали поля", conflict: "Расхождение",
  context: "Контекст", candidate: "Кандидаты", outside: "Вне периода",
};

const formatNumber = new Intl.NumberFormat("ru-RU", {maximumFractionDigits: 8});
const sortText = new Intl.Collator("ru", {numeric: true, sensitivity: "base"});
const plural = new Intl.PluralRules("ru-RU");
const rowForms = {one: "строка", few: "строки", many: "строк", other: "строк"};
const datePattern = /^([0-9]{4})-([0-9]{2})-([0-9]{2})(T[0-9:]+)?$/;
const helpPopover = get("fieldHelp");
let helpTrigger = null;

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

function initTabs(tabList, onChange = () => {}) {
  const tabs = [...tabList.querySelectorAll('[role="tab"]')];
  function activate(id) {
    const changed = tabs.find(tab => tab.getAttribute("aria-selected") === "true")?.id !== id;
    for (const tab of tabs) {
      const active = tab.id === id;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      get(tab.getAttribute("aria-controls")).hidden = !active;
    }
    if (changed) onChange(id);
  }
  tabList.addEventListener("click", event => {
    if (tabs.includes(event.target)) activate(event.target.id);
  });
  tabList.addEventListener("keydown", event => {
    const index = tabs.indexOf(event.target);
    if (index === -1) return;
    const destination = {
      ArrowLeft: (index + tabs.length - 1) % tabs.length,
      ArrowRight: (index + 1) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    }[event.key];
    if (destination === undefined) return;
    event.preventDefault();
    activate(tabs[destination].id);
    tabs[destination].focus();
  });
  return activate;
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

function badge(tone) {
  const status = el("span", tone === "ambiguous" ? "Неоднозначность" : labels[tone], "record-status");
  status.dataset.tone = tone;
  return status;
}

export {
  badge, button, datePattern, el, formatNumber, get, helpButton, initTabs, labels, plural, positionHelp,
  rowCount, sortText, tooltipButton, visValue,
};
