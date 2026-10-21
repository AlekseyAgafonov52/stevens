import { z } from "zod";
import { T } from "../content/texts";
import type { ChatResponse } from "./types";

const record = z.object({
  id: z.number().nullable().default(null),
  type: z.enum(["task", "meeting", "reminder"]).nullable().default(null),
  text: z.string(),
  date: z.string().nullable().default(null),
  time: z.string().nullable().default(null),
  date_kind: z.enum(["exact", "deadline", "none"]),
  status: z.enum(["open", "done"]).nullable().default(null),
  created_at: z.string().nullable().default(null),
  marks: z.array(z.enum(["new", "draft", "conflict"])).default([]),
  highlight: z.enum(["date", "time", "text"]).nullable().default(null),
});
const action = z.object({
  id: z.string(),
  record_id: z
    .number()
    .nullish()
    .transform((value) => value ?? undefined),
});
// Current Pydantic serializes ButtonSend with both keys, one of them null.
const send = z
  .object({ text: z.string().nullish(), action: action.nullish() })
  .transform((value) => {
    if (value.action) return { action: value.action };
    if (typeof value.text === "string") return { text: value.text };
    return null;
  })
  .refine((value) => value !== null)
  .transform((value) => value!);
const responseSchema = z.object({
  message_id: z.string(),
  kind: z.string(),
  text: z.string(),
  speech: z.string().nullable().default(null),
  records: z.array(record),
  nearest: record.nullable().default(null),
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

export function parseChatResponse(input: unknown): ChatResponse {
  const result = responseSchema.safeParse(input);
  if (result.success) return result.data;
  if (
    typeof input === "object" &&
    input !== null &&
    "text" in input &&
    typeof input.text === "string"
  ) {
    return {
      message_id: crypto.randomUUID(),
      kind: "text",
      text: input.text,
      speech: null,
      records: [],
      nearest: null,
      total: null,
      awaiting_reply: false,
      buttons: [],
    };
  }
  throw new Error(T.network_invalid);
}
