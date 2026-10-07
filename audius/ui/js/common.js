// Toolbar pieces shared by pages: DIM, undo/redo and scenes.
import { h, ico, menu, popover, closePopover, toast, inlineEdit } from "./ui.js";
import { state, subscribe } from "./store.js";
import { call, send } from "./bridge.js";
import { fmtDb } from "./dsp.js";

export const anyDimmed = () => (state.outputs || []).some((o) => o.dimmed);
export const toggleDim = () => send("dim", { on: !anyDimmed() });

// Like the DIM key on the Babyface: what you hear drops by a set amount until you press it again.
export function dimButton() {
  const btn = h("button", { class: "pill dim-pill", "aria-pressed": "false", onclick: toggleDim },
    h("span", { class: "led" }), "Dim");
  const sync = () => {
    const on = anyDimmed();
    btn.setAttribute("aria-pressed", String(on));
    const depth = fmtDb(state.prefs?.dim_db ?? -20, { digits: 0 });
    btn.title = on ? "Back to full level (Ctrl+D)" : `Lower what you hear by ${depth.replace("−", "")} (Ctrl+D)`;
  };
  subscribe(["outputs", "prefs"], sync);
  sync();
  return btn;
}

export function undoGroup() {
  const undo = h("button", { class: "btn icon plain", "aria-label": "Undo", onclick: () => send("undo") }, ico("undo"));
  const redo = h("button", { class: "btn icon plain", "aria-label": "Redo", onclick: () => send("redo") }, ico("redo"));
  const sync = () => {
    const u = state.undo || {};
    undo.disabled = !u.can_undo;
    redo.disabled = !u.can_redo;
    undo.title = u.can_undo ? `Undo ${u.undo_label} (Ctrl+Z)` : "Nothing to undo";
    redo.title = u.can_redo ? `Redo ${u.redo_label} (Ctrl+Shift+Z)` : "Nothing to redo";
  };
  subscribe(["undo"], sync);
  sync();
  return h("div", { class: "undo-group" }, undo, redo);
}

const when = (ts) => {
  const d = new Date(ts * 1000);
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" });
};

export function scenesButton() {
  const btn = h("button", { class: "btn", "aria-haspopup": "dialog", title: "Save and recall mixes" }, ico("scenes"), h("span", {}, "Scenes"));
  btn.addEventListener("click", () => openScenes(btn));
  return btn;
}

function openScenes(anchor) {
  const box = h("div", { class: "scenes-pop" });
  const list = h("div", { role: "menu" });
  const scenes = state.scenes || [];
  if (!scenes.length) {
    list.append(h("div", { class: "pop-body scenes-empty" },
      "Save your current mix as a scene, then bring it back with one click. Scenes keep routing, levels and on/off, never volume or 48V."));
  }
  for (const sc of scenes) {
    const row = h("div", { class: "scene-row" },
      h("button", {
        class: "menu-item", role: "menuitem", onclick: () => {
          closePopover();
          send("scene_recall", { id: sc.id });
          toast(`Recalled “${sc.name}”`, { label: "Undo", run: () => send("undo") });
        },
      }, ico("bookmark"), h("span", { class: "grow" }, sc.name), h("span", { class: "meta" }, when(sc.created))),
      h("button", {
        class: "icon-btn", "aria-label": `More for ${sc.name}`, onclick: (e) => {
          e.stopPropagation();
          sceneMenu(anchor, sc);
        },
      }, ico("ellipsis")));
    list.append(row);
  }
  const name = h("input", { class: "field", type: "text", placeholder: "Name this mix", "aria-label": "Scene name" });
  const save = async () => {
    const n = name.value.trim();
    closePopover();
    await call("scene_save", { name: n });
    toast(`Saved “${n || "Scene " + (scenes.length + 1)}”`);
  };
  name.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
  box.append(h("div", { class: "menu-label" }, "Scenes"), list, h("div", { class: "menu-sep" }),
    h("div", { class: "menu-field" }, name, h("button", { class: "btn accent", onclick: save }, "Save")));
  popover(anchor, box, { align: "end", width: 300, label: "Scenes" });
}

function sceneMenu(anchor, sc) {
  menu(anchor, [
    { heading: sc.name },
    { label: "Update with current mix", icon: "resend", action: () => { send("scene_update", { id: sc.id }); toast(`Updated “${sc.name}”`); } },
    { label: "Rename…", icon: "pencil", action: () => inlineEdit(anchor, { value: sc.name, width: 200, onCommit: (v) => send("scene_rename", { id: sc.id, name: v }) }) },
    "-",
    { label: "Delete", icon: "trash", danger: true, action: () => send("scene_delete", { id: sc.id }) },
  ], { align: "end" });
}
