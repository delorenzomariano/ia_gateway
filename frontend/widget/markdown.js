// Renderer de Markdown mínimo y seguro: crea nodos con textContent, nunca interpreta HTML.
// Soporta párrafos, saltos de línea, listas, bloques de código, código en línea y negrita.

const FENCE = /^```/;
const BULLET = /^\s*[-*]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*)/g;

function appendInline(parent, text) {
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    if (match.index > last) parent.appendChild(document.createTextNode(text.slice(last, match.index)));
    const token = match[0];
    const el = document.createElement(token.startsWith('`') ? 'code' : 'strong');
    el.textContent = token.startsWith('`') ? token.slice(1, -1) : token.slice(2, -2);
    parent.appendChild(el);
    last = match.index + token.length;
  }
  if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
}

function paragraph(lines) {
  const p = document.createElement('p');
  lines.forEach((line, i) => {
    if (i > 0) p.appendChild(document.createElement('br'));
    appendInline(p, line);
  });
  return p;
}

function list(tag, items) {
  const el = document.createElement(tag);
  for (const item of items) {
    const li = document.createElement('li');
    appendInline(li, item);
    el.appendChild(li);
  }
  return el;
}

function codeBlock(lines) {
  const pre = document.createElement('pre');
  const code = document.createElement('code');
  code.textContent = lines.join('\n');
  pre.appendChild(code);
  return pre;
}

export function renderMarkdown(text) {
  const fragment = document.createDocumentFragment();
  const lines = String(text ?? '').replace(/\r\n?/g, '\n').split('\n');
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (FENCE.test(line.trim())) {
      const code = [];
      i += 1;
      while (i < lines.length && !FENCE.test(lines[i].trim())) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1; // salta el cierre (o el final si quedó sin cerrar)
      fragment.appendChild(codeBlock(code));
      continue;
    }

    if (!line.trim()) {
      i += 1;
      continue;
    }

    const listKind = BULLET.test(line) ? [BULLET, 'ul'] : NUMBERED.test(line) ? [NUMBERED, 'ol'] : null;
    if (listKind) {
      const [pattern, tag] = listKind;
      const items = [];
      while (i < lines.length && pattern.test(lines[i])) {
        items.push(lines[i].match(pattern)[1]);
        i += 1;
      }
      fragment.appendChild(list(tag, items));
      continue;
    }

    const para = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !FENCE.test(lines[i].trim()) &&
      !BULLET.test(lines[i]) &&
      !NUMBERED.test(lines[i])
    ) {
      para.push(lines[i]);
      i += 1;
    }
    fragment.appendChild(paragraph(para));
  }

  return fragment;
}
