import type { ChatRequest, ChatResponse } from "../../api/types";

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  source?: ChatRequest["source"];
  response?: ChatResponse;
  error?: boolean;
  /** Техническая подпись под ошибкой: какой запрос не прошёл */
  detail?: string;
  request?: ChatRequest;
  restored?: boolean;
  selectedButton?: number;
  /** Записи, исправленные через PATCH после ответа (Д10), по id */
  edited?: number[];
}
