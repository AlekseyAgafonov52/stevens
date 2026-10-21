# Правила для ИИ-агента — фронт Stevens по контракту v1.4

- Источник правды по API — `docs/reference/contract_v1.4_s_dopami.pdf` и `src/api/types.ts`.
  Подстраиваться под текущий бэк нельзя, кроме входа и регистрации (email, имя, пароль — как в `app/routers/auth.py`).
- Не имитировать на фронте то, что должен делать бэк. Не 2xx или ответ не по контракту — ошибка с «Повторить» и технической подписью (`ApiError.detail`).
- Песочницы и деморежима в этой версии нет.
- Внешний вид и поведение — `docs/01–04`, `src/styles/tokens.css`. Все тексты — `src/content/texts.ts`.
- Допы — `src/config/features.ts`. Новый доп добавлять туда же.
- Перед коммитом: `pnpm run lint && pnpm run typecheck && pnpm test`.
