// DOM helpers, popovers, menus, toasts and inline editing.
import { icon } from "./icons.js";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "vars") for (const [n, val] of Object.entries(v)) el.style.setProperty(n, val);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") el.innerHTML = v;
    else if (k === "text") el.textContent = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export const ico = (name, cls) => {
  const i = icon(name);
  if (cls) i.classList.add(cls);
  return i;
};

export function clear(el) {
  while (el.firstChild) el.firstChild.remove();
  return el;
}

// ---------------------------------------------------------------- popovers
let layer;
let open = null;

function getLayer() {
  if (!layer) {
    layer = h("div", { class: "layer" });
    document.body.append(layer);
    document.addEventListener("pointerdown", (e) => {
      if (open && !open.el.contains(e.target) && !(open.anchor && open.anchor.contains(e.target))) closePopover();
    }, true);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && open) {
        e.preventDefault();
        closePopover();
      }
    });
  }
  return layer;
}

export function closePopover() {
  if (!open) return;
  const { el, onClose, anchor } = open;
  open = null;
  el.classList.add("closing");
  setTimeout(() => el.remove(), 120);
  if (anchor) anchor.setAttribute("aria-expanded", "false");
  if (onClose) onClose();
}

export function popover(anchor, content, { align = "center", width, onClose, role = "dialog", label, focus = true } = {}) {
  closePopover();
  const el = h("div", { class: "popover", role, "aria-label": label });
  if (width) el.style.width = width + "px";
  el.append(content);
  getLayer().append(el);
  const r = anchor.getBoundingClientRect();
  const pw = el.offsetWidth;
  const ph = el.offsetHeight;
  let left = align === "start" ? r.left : align === "end" ? r.right - pw : r.left + r.width / 2 - pw / 2;
  left = Math.max(10, Math.min(window.innerWidth - pw - 10, left));
  let top = r.bottom + 8;
  let origin = "top";
  if (top + ph > window.innerHeight - 10 && r.top - ph - 8 > 10) {
    top = r.top - ph - 8;
    origin = "bottom";
  }
  el.style.left = left + "px";
  el.style.top = top + "px";
  el.style.setProperty("--origin", `${r.left + r.width / 2 - left}px ${origin}`);
  anchor.setAttribute("aria-expanded", "true");
  open = { el, onClose, anchor };
  requestAnimationFrame(() => {
    const f = focus ? el.querySelector("[autofocus], input, .menu-item, button") : content;
    if (f) f.focus({ preventScroll: true });
  });
  return { el, close: closePopover };
}

// items: {label, icon, meta, danger, action, disabled} | "-" | {heading}
export function menu(anchor, items, opts = {}) {
  const box = h("div", { role: "menu" });
  for (const it of items) {
    if (it === "-") box.append(h("div", { class: "menu-sep", role: "separator" }));
    else if (it.heading) box.append(h("div", { class: "menu-label" }, it.heading));
    else if (it.node) box.append(it.node);
    else {
      box.append(h("button", {
        class: "menu-item" + (it.danger ? " danger" : ""), role: "menuitem", disabled: it.disabled,
        onclick: () => { closePopover(); it.action && it.action(); },
      }, it.icon ? ico(it.icon) : null, h("span", { class: "grow" }, it.label), it.meta ? h("span", { class: "meta" }, it.meta) : null));
    }
  }
  box.addEventListener("keydown", (e) => {
    const list = [...box.querySelectorAll(".menu-item:not([disabled])")];
    const i = list.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); list[(i + 1) % list.length]?.focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); list[(i - 1 + list.length) % list.length]?.focus(); }
  });
  return popover(anchor, box, { role: "menu", ...opts });
}

export function confirmPop(anchor, { title, body, ok = "OK", okClass = "accent", cancel = "Cancel" }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    const okBtn = h("button", { class: `btn ${okClass}`, onclick: () => { finish(true); closePopover(); } }, ok);
    // No default button: Return must not confirm a warning before it's read (Escape cancels).
    const box = h("div", { tabindex: "-1", class: "confirm" },
      h("div", { class: "pop-title" }, title),
      h("div", { class: "pop-body" }, body),
      h("div", { class: "pop-actions" },
        h("button", { class: "btn", onclick: () => { finish(false); closePopover(); } }, cancel), okBtn));
    popover(anchor, box, { width: 300, onClose: () => finish(false), role: "alertdialog", label: title, focus: false });
  });
}

// ---------------------------------------------------------------- toasts
let toastBox;
export function toast(text, action) {
  if (!toastBox) {
    toastBox = h("div", { class: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(toastBox);
  }
  while (toastBox.children.length > 1) toastBox.firstChild.remove();
  const t = h("div", { class: "toast" }, h("span", {}, text),
    action ? h("button", { class: "btn small accent", onclick: () => { action.run(); dismiss(); } }, action.label) : null);
  toastBox.append(t);
  let timer = setTimeout(dismiss, action ? 6000 : 3800);
  t.addEventListener("pointerenter", () => clearTimeout(timer));
  t.addEventListener("pointerleave", () => { timer = setTimeout(dismiss, 2000); });
  function dismiss() {
    t.classList.add("leaving");
    setTimeout(() => t.remove(), 200);
  }
}

// ---------------------------------------------------------------- inline editing
export function inlineEdit(anchor, { value, onCommit, width = 84, align = "center" }) {
  const r = anchor.getBoundingClientRect();
  const input = h("input", { class: "inline-edit", type: "text", value, spellcheck: "false", "aria-label": "Value" });
  input.style.position = "fixed";
  input.style.width = width + "px";
  const left = align === "start" ? r.left : r.left + r.width / 2 - width / 2;
  input.style.left = Math.max(6, Math.min(window.innerWidth - width - 6, left)) + "px";
  input.style.top = r.top + r.height / 2 - 13 + "px";
  document.body.append(input);
  input.focus();
  input.select();
  let done = false;
  const finish = (commit) => {
    if (done) return;
    done = true;
    if (commit) onCommit(input.value);
    input.remove();
    anchor.focus?.({ preventScroll: true });
  };
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") finish(true);
    if (e.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
}

export function renameable(el, { get, set }) {
  el.addEventListener("dblclick", () => {
    inlineEdit(el, { value: get(), width: Math.max(140, el.offsetWidth + 30), align: "start", onCommit: (v) => set(v) });
  });
  el.title = "Double-click to rename";
}

export const reduceMotion = () => document.documentElement.dataset.reduceMotion === "true" ||
  matchMedia("(prefers-reduced-motion: reduce)").matches;
