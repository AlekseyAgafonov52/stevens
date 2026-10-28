/**
 * Голосовые правки надиктованного текста, до отправки.
 * «стоп» / «отмена» в конце — отменить запись целиком.
 * «…с и вам, не „и вам“, а „Иван“» или «…исправь и вам на Иван» — заменить ослышку.
 */

/** Последнее слово — «стоп» или «отмена»: запись отменяется, ничего не уходит */
const CANCEL_WORD = /(?:^|[\s,.!?])(?:стоп|отмена)[\s.!?]*$/i;

export function isCancel(text: string): boolean {
  return CANCEL_WORD.test(text.trim());
}

const QUOTES = /[«»"„“”']/g;
/**
 * «не X, а Y» и «исправь / поправь / замени X на Y» — только в самом конце фразы.
 * Начало поправки ищем с конца: в «я не знаю, с кем, с и вам, не и вам, а Иван» берём последнее «не»
 */
const CORRECTIONS = [
  /не\s+(.+?)[\s,—-]+а\s+(.+?)[\s.!?]*$/iy,
  /(?:исправь|исправить|поправь|замени)\s+(.+?)\s+на\s+(.+?)[\s.!?]*$/iy,
];
/** Где может начаться поправка: начало текста или после пробела / знака */
const WORD_START = /(?:^|[\s,.!?—-])(?=[а-яё])/gi;

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function findWrong(before: string, wrong: string): { start: number; length: number } | null {
  // Последнее вхождение, целыми словами, без учёта регистра и ё/е
  const flex = escape(wrong).replace(/\s+/g, '\\s+').replace(/[её]/gi, '[её]');
  const re = new RegExp(`(^|[^а-яёa-z0-9])(${flex})(?![а-яёa-z0-9])`, 'gi');
  let last: RegExpExecArray | null = null;
  for (let m = re.exec(before); m; m = re.exec(before)) last = m;
  return last && { start: last.index + last[1].length, length: last[2].length };
}

/**
 * Применяет голосовую поправку в конце текста. Если исправляемых слов в тексте нет,
 * это обычная речь («встреча не в понедельник, а во вторник») — текст не трогаем.
 */
export function applyCorrections(text: string): string {
  const starts = [...text.matchAll(WORD_START)].map((m) => m.index + m[0].length).reverse();
  for (const pattern of CORRECTIONS) {
    for (const at of starts) {
      pattern.lastIndex = at;
      const hit = pattern.exec(text);
      if (!hit) continue;
      // «…и вам, нет, не и вам, а Ивану» — «нет» тоже часть поправки
      const before = text.slice(0, at).replace(/(?:^|[\s,.!?—-])нет[\s,.!?—-]*$/i, '').replace(/[\s,.!?—-]+$/, '');
      const wrong = hit[1].replace(QUOTES, '').replace(/[\s,.!?—-]+$/, '').trim();
      const right = hit[2].replace(QUOTES, '').trim();
      if (!wrong || !right || !before) continue;
      const found = findWrong(before, wrong);
      if (!found) continue;
      return applyCorrections(before.slice(0, found.start) + right + before.slice(found.start + found.length));
    }
  }
  return text;
}
