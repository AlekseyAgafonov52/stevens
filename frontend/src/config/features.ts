/** Адрес бэка. Пусто — тот же адрес, что у страницы (nginx проксирует /api). Задаётся при сборке: VITE_API_URL */
export const apiUrl: string = import.meta.env.VITE_API_URL ?? '';
