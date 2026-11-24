import {get, positionHelp} from "./viewer_ui.js";

export function initOrdersPane() {
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
