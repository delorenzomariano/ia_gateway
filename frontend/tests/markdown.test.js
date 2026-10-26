import { describe, expect, it } from 'vitest';
import { renderMarkdown } from '../widget/markdown.js';

function render(text) {
  const host = document.createElement('div');
  host.appendChild(renderMarkdown(text));
  return host;
}

describe('renderMarkdown', () => {
  it('separa párrafos por líneas en blanco', () => {
    const host = render('Primer párrafo.\n\nSegundo párrafo.');
    const ps = host.querySelectorAll('p');
    expect(ps).toHaveLength(2);
    expect(ps[0].textContent).toBe('Primer párrafo.');
  });

  it('mantiene saltos de línea dentro de un párrafo', () => {
    const host = render('línea 1\nlínea 2');
    expect(host.querySelectorAll('p')).toHaveLength(1);
    expect(host.querySelectorAll('br')).toHaveLength(1);
  });

  it('renderiza listas con viñetas y numeradas', () => {
    const host = render('- uno\n- dos\n\n1. primero\n2. segundo');
    expect([...host.querySelectorAll('ul > li')].map((li) => li.textContent)).toEqual(['uno', 'dos']);
    expect([...host.querySelectorAll('ol > li')].map((li) => li.textContent)).toEqual([
      'primero',
      'segundo',
    ]);
  });

  it('renderiza bloques de código sin interpretar su contenido', () => {
    const host = render('```js\nconst a = "<b>";\n```');
    const code = host.querySelector('pre > code');
    expect(code.textContent).toBe('const a = "<b>";');
    expect(host.querySelector('b')).toBeNull();
  });

  it('renderiza código en línea y negrita', () => {
    const host = render('Usá `npm test` y **listo**.');
    expect(host.querySelector('p > code').textContent).toBe('npm test');
    expect(host.querySelector('p > strong').textContent).toBe('listo');
  });

  it('muestra HTML como texto literal', () => {
    const malicious = '<script>alert(1)</script><img src=x onerror="alert(2)">';
    const host = render(malicious);
    expect(host.querySelector('script')).toBeNull();
    expect(host.querySelector('img')).toBeNull();
    expect(host.textContent).toBe(malicious);
  });

  it('tolera un bloque de código sin cerrar (respuesta parcial)', () => {
    const host = render('Mirá:\n```\nlinea');
    expect(host.querySelector('pre > code').textContent).toBe('linea');
  });
});
