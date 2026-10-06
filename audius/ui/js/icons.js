// A small icon set drawn on a 24 px grid in the spirit of SF Symbols: 1.7 px strokes, round joins.
const P = {
  headphones: '<path d="M4 15.5v-3a8 8 0 0 1 16 0v3"/><rect x="3" y="14" width="4.6" height="6.8" rx="2"/><rect x="16.4" y="14" width="4.6" height="6.8" rx="2"/>',
  speaker: '<path d="M3.5 9.6h3.4L11.6 5.6v12.8l-4.7-4H3.5a.9.9 0 0 1-.9-.9V10.5a.9.9 0 0 1 .9-.9z"/><path d="M15.2 9.2a4.2 4.2 0 0 1 0 5.6"/><path d="M18 6.6a8 8 0 0 1 0 10.8"/>',
  speakerSlash: '<path d="M3.5 9.6h3.4L11.6 5.6v12.8l-4.7-4H3.5a.9.9 0 0 1-.9-.9V10.5a.9.9 0 0 1 .9-.9z"/><path d="M15.5 9.5l5 5M20.5 9.5l-5 5"/>',
  both: '<path d="M2.5 13.5v-2a6 6 0 0 1 12 0v2"/><rect x="1.8" y="12.6" width="3.6" height="5.6" rx="1.6"/><rect x="11.6" y="12.6" width="3.6" height="5.6" rx="1.6"/><path d="M18.2 8.5a4.6 4.6 0 0 1 0 7"/><path d="M20.6 6.2a8 8 0 0 1 0 11.6"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.6 11.2a6.4 6.4 0 0 0 12.8 0"/><path d="M12 17.6V21"/>',
  instrument: '<path d="M13.4 10.6l5.4-5.4"/><path d="M17.4 3.6l3 3"/><path d="M11.3 8.6a3.2 3.2 0 0 0-4.5 2.1 4.8 4.8 0 1 0 6.5 6.5 3.2 3.2 0 0 0 2.1-4.5 3.1 3.1 0 0 1-4.1-4.1z"/><circle cx="10.3" cy="13.7" r="1.2"/>',
  optical: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>',
  computer: '<rect x="3" y="4" width="18" height="12.6" rx="2.2"/><path d="M9 20.4h6M12 16.6v3.8"/>',
  dial: '<circle cx="12" cy="12" r="8.4"/><path d="M12 12V6.6"/>',
  link: '<path d="M10.2 13.8a4 4 0 0 0 5.7 0l2.9-2.9a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M13.8 10.2a4 4 0 0 0-5.7 0l-2.9 2.9a4 4 0 0 0 5.7 5.7l1-1"/>',
  unlink: '<path d="M15.9 13.4l2.9-2.5a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M8.1 10.6l-2.9 2.5a4 4 0 0 0 5.7 5.7l1-1"/><path d="M4 4l16 16"/>',
  undo: '<path d="M9 13.8L4.2 9 9 4.2"/><path d="M4.4 9h10.1a5.4 5.4 0 0 1 0 10.8H11"/>',
  redo: '<path d="M15 13.8L19.8 9 15 4.2"/><path d="M19.6 9H9.5a5.4 5.4 0 0 0 0 10.8H13"/>',
  scenes: '<rect x="3.6" y="9" width="16.8" height="11" rx="2.6"/><path d="M6.2 5.8h11.6M8.8 2.8h6.4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  xmark: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  chevronRight: '<path d="M9.5 5.8L15.7 12l-6.2 6.2"/>',
  chevronDown: '<path d="M5.8 9.5l6.2 6.2 6.2-6.2"/>',
  ellipsis: '<circle cx="5.8" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="18.2" cy="12" r="1.5" fill="currentColor" stroke="none"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 10.8v5.6"/><circle cx="12" cy="7.6" r="1.1" fill="currentColor" stroke="none"/>',
  check: '<path d="M5 12.6l4.4 4.4L19 7.4"/>',
  resend: '<path d="M19.6 8.4A8.3 8.3 0 0 0 4.8 8.6"/><path d="M19.8 3.8v4.8H15"/><path d="M4.4 15.6a8.3 8.3 0 0 0 14.8-.2"/><path d="M4.2 20.2v-4.8H9"/>',
  warning: '<path d="M12 3.8L21 19.6H3z"/><path d="M12 9.8v4.6"/><circle cx="12" cy="17" r="1.05" fill="currentColor" stroke="none"/>',
  waveform: '<path d="M4 10v4M8 7v10M12 3.5v17M16 7.5v9M20 10.5v3"/>',
  trash: '<path d="M4.6 6.8h14.8M9.6 6.8V4.6h4.8v2.2M6.8 6.8l.9 13h8.6l.9-13"/>',
  pencil: '<path d="M15.2 5.2l3.6 3.6L9 18.6l-4.4.8.8-4.4z"/>',
  bolt: '<path d="M13.2 2.8L5.4 13.4h6.2L10.8 21.2l7.8-10.6h-6.2z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.2l3.4 2"/>',
  power: '<path d="M12 3.5v8"/><path d="M7 6.3a7.5 7.5 0 1 0 10 0"/>',
  mixer: '<path d="M6 4v16M12 4v16M18 4v16"/><rect x="3.8" y="13" width="4.4" height="3.2" rx="1" fill="currentColor"/><rect x="9.8" y="7" width="4.4" height="3.2" rx="1" fill="currentColor"/><rect x="15.8" y="11" width="4.4" height="3.2" rx="1" fill="currentColor"/>',
  grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.6"/>',
  bookmark: '<path d="M6.5 3.8h11v16.4L12 16.4l-5.5 3.8z"/>',
  sparkle: '<path d="M12 3.5l1.8 5.2 5.2 1.8-5.2 1.8L12 17.5l-1.8-5.2L5 10.5l5.2-1.8z"/>',
};

export function svg(name, extra = "") {
  const body = P[name] || P.info;
  return `<svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${body}</svg>`;
}

export function icon(name) {
  const t = document.createElement("template");
  t.innerHTML = svg(name);
  return t.content.firstElementChild;
}
