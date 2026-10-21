import type { RecordItem, RecordPatch } from "../../api/types";
import { T } from "../../content/texts";

/**
 * Правка записи через PATCH /api/records/{id} (Д10 «Исправить», Д6 календарь).
 * Шлём только изменённые поля. Правила 15.5 проверяем до отправки,
 * но решает всё равно бэк.
 */
export function buildPatch(
  record: RecordItem,
  values: { text: string; date: string; time: string; noDate: boolean },
): { patch: RecordPatch; error: string | null } {
  const text = values.text.trim();
  const date = values.noDate ? null : values.date || null;
  const time = values.noDate ? null : values.time || null;
  if (!text || text.length > 300) return { patch: {}, error: T.edit_err_text };
  if (record.type === "meeting" || record.type === "reminder") {
    if (!date || !time) return { patch: {}, error: T.edit_err_required };
  } else if (time && !date)
    return { patch: {}, error: T.edit_err_time_without_date };
  const patch: RecordPatch = {};
  if (text !== record.text) patch.text = text;
  if (date !== record.date) patch.date = date;
  if (time !== record.time) patch.time = time;
  return { patch, error: null };
}
