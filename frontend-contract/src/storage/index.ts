import type { User } from "../api/types";
import { apiUrl } from "../config/features";

const prefix = "stevens-contract:v1:";
const sessionKey = `session:${apiUrl}`;

export function read<T>(key: string): T | null {
  try {
    return JSON.parse(localStorage.getItem(prefix + key) ?? "null") as T | null;
  } catch {
    return null;
  }
}
export function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(prefix + key, JSON.stringify(value));
  } catch {
    /* Storage is optional. */
  }
}
export function remove(key: string): void {
  try {
    localStorage.removeItem(prefix + key);
  } catch {
    /* Storage is optional. */
  }
}
export interface Session {
  token: string;
  user: User;
}
export function loadSession(): Session | null {
  const session = read<Session>(sessionKey);
  return session &&
    typeof session.token === "string" &&
    session.user &&
    typeof session.user.email === "string" &&
    typeof session.user.name === "string" &&
    typeof session.user.id === "number"
    ? session
    : null;
}
export function saveSession(session: Session): void {
  write(sessionKey, session);
}
export function clearSession(): void {
  remove(sessionKey);
}

export function loadFeed<T>(key: string): T[] {
  const saved = read<{ savedAt: number; messages: T[] }>(`feed:${key}`);
  if (
    !saved ||
    !Array.isArray(saved.messages) ||
    typeof saved.savedAt !== "number" ||
    Date.now() - saved.savedAt > 3_600_000
  ) {
    remove(`feed:${key}`);
    return [];
  }
  return saved.messages;
}
export function saveFeed(key: string, messages: unknown[]): void {
  write(`feed:${key}`, { savedAt: Date.now(), messages: messages.slice(-50) });
}
