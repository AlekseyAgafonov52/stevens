import { z } from "zod";
import type { ChatResponse, RecordItem } from "./types";

/**
 * Проверка ответов по контракту v1.4. Поля «обяз.» должны быть всегда,
 * поля «необяз.» могут быть null или отсутствовать. Ответ не по контракту
 * фронт не чинит, а показывает как ошибку (см. api/index.ts).
 */
const date = z.string().regex(/^\d{4}-\d{2}-\d{2}$/);
const time = z.string().regex(/^\d{2}:\d{2}$/);

export const recordSchema = z.object({
  id: z.number().nullable().default(null),
  type: z.enum(["task", "meeting", "reminder"]).nullable().default(null),
  text: z.string(),
  date: date.nullable().default(null),
  time: time.nullable().default(null),
  date_kind: z.enum(["exact", "deadline", "none"]),
  status: z.enum(["open", "done"]).nullable().default(null),
  created_at: z.string().nullable().default(null),
  marks: z.array(z.enum(["new", "draft", "conflict", "deleted"])),
  highlight: z.enum(["date", "time", "text"]).nullable().default(null),
  remind_at: z.string().nullable().optional(),
});
const action = z.object({
  id: z.string(),
  record_id: z
    .number()
    .nullish()
    .transform((value) => value ?? undefined),
});
// «Ровно одно из двух». Ключ со значением null считаем отсутствующим:
// так сериализует Pydantic, и смысл от этого не меняется.
const send = z
  .object({ text: z.string().nullish(), action: action.nullish() })
  .refine(
    (value) => (value.text == null) !== (value.action == null),
    "send: нужно ровно одно из text и action",
  )
  .transform((value) =>
    value.action ? { action: value.action } : { text: value.text! },
  );
const responseSchema = z.object({
  message_id: z.string(),
  kind: z.string(),
  text: z.string(),
  speech: z.string().nullable().default(null),
  records: z.array(recordSchema),
  nearest: recordSchema.nullable().default(null),
  total: z.number().nullable().default(null),
  awaiting_reply: z.boolean(),
  buttons: z.array(
    z.object({
      label: z.string(),
      send,
      style: z.enum(["primary", "secondary"]).optional(),
    }),
  ),
});
export const healthSchema = z.object({ status: z.literal("ok") });
export const recordsSchema = z.object({ records: z.array(recordSchema) });
export const recordResponseSchema = z.object({ record: recordSchema });
export const userSchema = z.object({
  id: z.number(),
  email: z.string(),
  name: z.string(),
});
export const authSchema = z.object({
  token: z.string(),
  user: userSchema,
  expires_at: z.string(),
});

/** Где именно ответ разошёлся с контрактом — для технической подписи под ошибкой */
export function describeIssue(error: z.ZodError): string {
  const issue = error.issues[0];
  return issue
    ? `${issue.path.join(".") || "ответ"}: ${issue.message}`
    : "формат ответа";
}

export function parseChatResponse(input: unknown): ChatResponse {
  return responseSchema.parse(input);
}
export function parseRecord(input: unknown): RecordItem {
  return recordResponseSchema.parse(input).record;
}
