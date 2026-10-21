import { useEffect, useState } from "react";
import { ApiError, health, me } from "./api";
import type { AuthResponse } from "./api/types";
import { T } from "./content/texts";
import { AuthScreen } from "./features/auth/AuthScreen";
import { ChatScreen } from "./features/chat/ChatScreen";
import {
  clearSession,
  loadSession,
  saveSession,
  type Session,
} from "./storage";

export default function App() {
  const [session, setSession] = useState<Session | null>(loadSession);
  const [expired, setExpired] = useState(false);
  const [checking, setChecking] = useState(!!session);
  const [serverStatus, setServerStatus] = useState("");
  const [attempt, setAttempt] = useState(0);

  // GET /api/health при открытии; пока нет ответа — «Просыпаюсь…» (раздел 2, Р-46)
  useEffect(() => {
    let active = true;
    const waking = setTimeout(() => {
      if (active) setServerStatus(T.status_waking);
    }, 1500);
    void health()
      .then(() => {
        if (active) setServerStatus("");
      })
      .catch((error) => {
        if (!active) return;
        setServerStatus(
          error instanceof ApiError &&
            (error.kind === "network" || error.kind === "timeout")
            ? T.status_server_down
            : `${T.status_health_failed} (${error instanceof ApiError ? error.detail : ""})`,
        );
      })
      .finally(() => clearTimeout(waking));
    return () => {
      active = false;
      clearTimeout(waking);
    };
  }, [attempt]);

  useEffect(() => {
    const saved = loadSession();
    if (!saved) {
      setChecking(false);
      return;
    }
    let active = true;
    void me(saved.token)
      .then((user) => {
        if (active) {
          const current = { token: saved.token, user };
          setSession(current);
          saveSession(current);
        }
      })
      .catch((error) => {
        if (!active) return;
        if (error instanceof ApiError && error.kind === "unauthorized") {
          clearSession();
          setSession(null);
          setExpired(true);
        } else {
          setServerStatus(T.status_server_down);
          setSession(null);
        }
      })
      .finally(() => {
        if (active) setChecking(false);
      });
    return () => {
      active = false;
    };
  }, []);

  function login(response: AuthResponse) {
    const current = { token: response.token, user: response.user };
    setSession(current);
    saveSession(current);
    setExpired(false);
    setServerStatus("");
    setAttempt((value) => value + 1);
  }
  // Выход удаляет токен в браузере: в текущем бэке нет /api/auth/logout
  function exit(isExpired = false) {
    clearSession();
    setSession(null);
    setExpired(isExpired);
  }
  if (checking)
    return (
      <main className="auth-page">
        <div className="auth-column">
          <h1 className="auth-brand">{T.app_name}</h1>
          <p className="auth-status" role="status">
            {T.auth_check}
          </p>
        </div>
      </main>
    );
  if (!session)
    return (
      <AuthScreen
        expired={expired}
        serverStatus={serverStatus}
        onSuccess={login}
      />
    );
  return (
    <ChatScreen
      key={session.user.id}
      session={session}
      onExit={exit}
      serverStatus={serverStatus}
    />
  );
}
