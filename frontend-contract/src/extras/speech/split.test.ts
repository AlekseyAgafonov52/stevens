import { describe, expect, it } from 'vitest';
import { splitSentences } from './index';

describe('splitSentences', () => {
  it('режет по концу предложения', () => {
    expect(splitSentences('На сегодня у вас три дела. Первое — созвон в 10:00! Что-нибудь ещё?')).toEqual([
      'На сегодня у вас три дела.',
      'Первое — созвон в 10:00!',
      'Что-нибудь ещё?',
    ]);
  });
  it('одно предложение и многоточие', () => {
    expect(splitSentences('Встреча — завтра в 15:00.')).toEqual(['Встреча — завтра в 15:00.']);
    expect(splitSentences('Минутку… Готово.')).toEqual(['Минутку…', 'Готово.']);
  });
  it('не рвёт нумерацию и даты', () => {
    expect(splitSentences('Дела: 1. созвон, 2. отчёт к 15.10. Всё.')).toEqual(['Дела: 1. созвон, 2. отчёт к 15.10.', 'Всё.']);
  });
});
