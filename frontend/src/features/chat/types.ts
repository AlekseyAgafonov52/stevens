import type { ChatRequest, ChatResponse } from "../../api/types";

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  source?: ChatRequest["source"];
  response?: ChatResponse;
  error?: boolean;
  request?: ChatRequest;
  restored?: boolean;
  selectedButton?: number;
}
