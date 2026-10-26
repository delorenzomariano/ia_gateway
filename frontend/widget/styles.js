// Estilos del Shadow DOM de <ia-chat-widget>. Personalizable con --ia-chat-accent,
// --ia-chat-font y --ia-chat-z-index.

export const STYLES = `
:host {
  --accent: var(--ia-chat-accent, #38bdf8);
  --font: var(--ia-chat-font, "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif);
  --z: var(--ia-chat-z-index, 2147483000);
  --on-accent: #004965;
  --secondary: #bdc2ff;
  --secondary-container: #2f3aa3;
  --surface-lowest: #010f1f;
  --surface-low: #0d1c2d;
  --surface: #122131;
  --surface-high: #1c2b3c;
  --surface-highest: #273647;
  --fg: #d4e4fa;
  --muted: #bdc8d1;
  --outline: #87929a;
  --danger: #ffb4ab;
  --glow: rgba(56, 189, 248, .4);
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: var(--z);
  font-family: var(--font);
  color: var(--fg);
}
:host([position="bottom-left"]) { right: auto; left: 24px; }
* { box-sizing: border-box; }
[hidden] { display: none !important; }
button { font: inherit; cursor: pointer; }
button:focus-visible, textarea:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
svg { display: block; }

.launcher {
  width: 56px; height: 56px; border-radius: 50%; border: none;
  background: linear-gradient(45deg, var(--accent), #8ed5ff 55%, var(--secondary));
  color: #00354a;
  box-shadow: 0 0 25px rgba(56, 189, 248, .5);
  display: grid; place-items: center;
  transition: transform .2s ease, box-shadow .3s ease;
}
.launcher:hover { transform: scale(1.05); box-shadow: 0 0 35px rgba(56, 189, 248, .8); }
.launcher:active { transform: scale(.95); }
.launcher svg { width: 26px; height: 26px; }
.launcher .icon-close { display: none; }
.launcher[aria-expanded="true"] .icon-chat { display: none; }
.launcher[aria-expanded="true"] .icon-close { display: block; }

.panel {
  position: absolute; bottom: 72px; right: 0;
  width: 400px; height: min(580px, calc(100vh - 110px));
  display: flex; flex-direction: column;
  background: rgba(13, 28, 45, .95);
  -webkit-backdrop-filter: blur(24px); backdrop-filter: blur(24px);
  border-radius: 24px;
  box-shadow: 0 20px 60px -10px rgba(0, 0, 0, .8), 0 0 30px rgba(56, 189, 248, .2);
  overflow: hidden;
  animation: ia-pop .2s ease-out;
  transform-origin: bottom right;
}
:host([position="bottom-left"]) .panel { right: auto; left: 0; transform-origin: bottom left; }
@keyframes ia-pop { from { opacity: 0; transform: scale(.92); } to { opacity: 1; transform: none; } }

header {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 14px 12px 18px; background: rgba(18, 33, 49, .9);
  box-shadow: 0 1px 2px rgba(0, 0, 0, .2);
}
.avatar {
  width: 36px; height: 36px; border-radius: 50%; flex: none;
  display: grid; place-items: center; color: #00354a;
  background: linear-gradient(45deg, var(--accent), var(--secondary));
  box-shadow: 0 2px 6px rgba(0, 0, 0, .3);
}
.avatar svg { width: 20px; height: 20px; }
.heading { flex: 1; min-width: 0; }
header h2 {
  margin: 0; font-size: .9rem; font-weight: 600; line-height: 1.2;
  font-family: "Plus Jakarta Sans", var(--font);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.subtitle { margin: 2px 0 0; font-size: .7rem; color: var(--muted); }
header button {
  display: grid; place-items: center; width: 32px; height: 32px; padding: 0;
  background: transparent; border: none; border-radius: 8px; color: var(--muted);
  transition: background .2s, color .2s;
}
header button:hover { background: var(--surface-highest); color: var(--fg); }
header button svg { width: 18px; height: 18px; }

.log {
  flex: 1; overflow-y: auto; padding: 16px 16px 8px 46px;
  display: flex; flex-direction: column; gap: 14px;
  scrollbar-width: thin; scrollbar-color: var(--surface-highest) transparent;
}
.empty {
  position: relative; align-self: flex-start; max-width: 85%; margin: 0;
  padding: 12px 14px; border-radius: 4px 18px 18px 18px;
  background: rgba(18, 33, 49, .9); font-size: .875rem; line-height: 1.5;
}
.msg { position: relative; max-width: 85%; padding: 12px 14px; line-height: 1.5; font-size: .875rem;
  overflow-wrap: anywhere; box-shadow: 0 1px 2px rgba(0, 0, 0, .2); }
.msg[data-sender="user"] {
  align-self: flex-end; border-radius: 18px 4px 18px 18px;
  background: rgba(47, 58, 163, .4); white-space: pre-wrap;
}
.msg[data-sender="assistant"] {
  align-self: flex-start; border-radius: 4px 18px 18px 18px; background: rgba(18, 33, 49, .9);
}
.msg[data-sender="assistant"]::before, .empty::before {
  content: ""; position: absolute; left: -32px; top: 2px;
  width: 24px; height: 24px; border-radius: 50%;
  background:
    radial-gradient(circle at 50% 50%, var(--accent) 0 3px, transparent 4px),
    rgba(142, 213, 255, .2);
}
.msg[data-status="streaming"]::before { animation: ia-pulse 1.2s ease-in-out infinite; }
.msg[data-status="incomplete"]::after { content: "(respuesta incompleta)"; display: block;
  margin-top: 6px; font-size: .7rem; color: var(--muted); }
.msg[data-status="error"] { box-shadow: inset 0 0 0 1px var(--danger); }
.msg p { margin: 0 0 .5em; } .msg p:last-child { margin-bottom: 0; }
.msg ul, .msg ol { margin: .25em 0 .5em; padding-left: 1.25em; }
.msg pre { margin: .5em 0; padding: 10px; background: var(--surface-lowest); border-radius: 12px;
  overflow-x: auto; color: var(--muted); }
.msg code { font-family: ui-monospace, Consolas, monospace; font-size: .8em; }
.msg :not(pre) > code { padding: 1px 6px; border-radius: 4px; background: var(--surface-lowest);
  color: var(--secondary); }

.status {
  display: flex; align-items: center; gap: 6px;
  padding: 0 16px 8px 46px; color: var(--accent); font-size: .75rem; font-weight: 500;
}
.status::before {
  content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor;
  box-shadow: 0 0 8px currentColor; animation: ia-pulse 1.2s ease-in-out infinite;
}
@keyframes ia-pulse { 50% { opacity: .35; } }
.notice { margin: 0 14px 8px; padding: 8px 12px; border-radius: 12px; font-size: .8rem;
  background: rgba(147, 0, 10, .35); color: #ffdad6;
  display: flex; gap: 8px; align-items: center; justify-content: space-between; }
.notice button { background: transparent; border: 1px solid currentColor; color: inherit;
  border-radius: 999px; padding: 2px 10px; font-size: .75rem; }
.notice button:hover { background: rgba(255, 218, 214, .1); }

form { padding: 12px; background: rgba(18, 33, 49, .9); }
.field {
  display: flex; align-items: flex-end; gap: 6px;
  padding: 6px 6px 6px 14px; border-radius: 18px; background: rgba(1, 15, 31, .9);
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, .3);
  transition: box-shadow .2s;
}
.field:focus-within { box-shadow: inset 0 2px 4px rgba(0, 0, 0, .3), 0 0 0 1px rgba(142, 213, 255, .6); }
textarea {
  flex: 1; resize: none; min-height: 32px; max-height: 120px; padding: 6px 0;
  border: none; background: transparent; color: var(--fg);
  font: inherit; font-size: .875rem; line-height: 1.4;
}
textarea::placeholder { color: var(--outline); }
textarea:focus-visible { outline: none; }
.field button {
  width: 32px; height: 32px; flex: none; padding: 0; border: none; border-radius: 50%;
  display: grid; place-items: center;
  background: var(--accent); color: var(--on-accent);
  box-shadow: 0 0 12px var(--glow); transition: background .2s, opacity .2s;
}
.field button svg { width: 16px; height: 16px; }
.field button:hover:not(:disabled) { background: #8ed5ff; }
.field button:disabled { opacity: .4; cursor: not-allowed; box-shadow: none; }
.field button[data-role="stop"] { background: var(--danger); color: #690005; box-shadow: none; }
.field button.attach {
  background: transparent; color: var(--muted); box-shadow: none;
}
.field button.attach:hover:not(:disabled) { background: var(--surface-high); color: var(--accent); }

.attachment-preview {
  display: flex; align-items: center; gap: 10px; margin: 0 0 8px; padding: 6px 6px 6px 8px;
  border-radius: 14px; background: rgba(1, 15, 31, .9);
}
.preview-thumb { width: 48px; height: 48px; flex: none; object-fit: cover; border-radius: 10px;
  background: var(--surface); }
.preview-name { flex: 1; min-width: 0; font-size: .8rem; color: var(--muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.attachment-preview button {
  width: 28px; height: 28px; flex: none; padding: 0; border: none; border-radius: 50%;
  display: grid; place-items: center; background: transparent; color: var(--muted);
}
.attachment-preview button:hover { background: var(--surface-highest); color: var(--fg); }
.attachment-preview button svg { width: 16px; height: 16px; }

.msg .attachment { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
.msg .attachment + .body:not(:empty) { margin-top: 8px; }
.msg .body:empty { display: none; }
.attachment-thumb { display: block; max-width: 220px; max-height: 220px; border-radius: 12px; }
.attachment-chip { font-size: .8rem; color: var(--muted); }
.msg details.ocr { width: 100%; font-size: .8rem; white-space: normal; }
.msg details.ocr summary { cursor: pointer; color: var(--accent); }
.msg details.ocr summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.ocr-text {
  margin-top: 6px; padding: 8px 10px; max-height: 200px; overflow-y: auto; border-radius: 10px;
  background: var(--surface-lowest); color: var(--muted); white-space: pre-wrap;
  font-size: .8rem; line-height: 1.45;
}

.hint { display: flex; justify-content: space-between; margin: 8px 4px 0;
  font-size: .65rem; color: rgba(189, 200, 209, .6); }
kbd { font-family: ui-monospace, Consolas, monospace; padding: 0 4px; border-radius: 4px;
  background: var(--surface); }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}

@media (max-width: 480px) {
  :host { bottom: 16px; right: 16px; }
  :host([position="bottom-left"]) { left: 16px; }
  .panel {
    position: fixed; inset: 0; width: 100vw; height: 100dvh; border-radius: 0;
  }
}
`;
