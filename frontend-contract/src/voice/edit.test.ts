import { expect, test } from 'vitest';
import { applyCorrections, isCancel } from './edit';

test('«стоп» и «отмена» последним словом — отмена', () => {
  expect(isCancel('стоп')).toBe(true);
  expect(isCancel('Отмена.')).toBe(true);
  expect(isCancel('завтра в 10 созвон, стоп')).toBe(true);
  expect(isCancel('отмена встречи с Иваном')).toBe(false);
  expect(isCancel('купить стопку бумаги')).toBe(false);
});

test('«не X, а Y» меняет ослышку', () => {
  expect(applyCorrections('завтра созвон с и вам не и вам а Иваном')).toBe('завтра созвон с Иваном');
  expect(applyCorrections('Завтра созвон с и вам, не «и вам», а «Иваном».')).toBe('Завтра созвон с Иваном');
  expect(applyCorrections('я не знаю когда звонить и вам нет не и вам а Ивану')).toBe('я не знаю когда звонить Ивану');
});

test('«исправь X на Y» меняет ослышку', () => {
  expect(applyCorrections('встреча с и вам в 10 исправь и вам на Иваном')).toBe('встреча с Иваном в 10');
  expect(applyCorrections('позвонить маме в пятницу поправь пятницу на субботу')).toBe('позвонить маме в субботу');
});

test('обычная речь без ослышки не меняется', () => {
  expect(applyCorrections('встреча не в понедельник, а во вторник')).toBe('встреча не в понедельник, а во вторник');
  expect(applyCorrections('не забыть хлеб а потом молоко')).toBe('не забыть хлеб а потом молоко');
  expect(applyCorrections('замени масло на синтетику')).toBe('замени масло на синтетику');
});
