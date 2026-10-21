import { useEffect, useState } from "react";
import { ApiError, health, me } from "./api";
import type { AuthResponse } from "./api/types";
import { apiMode, features } from "./config/features";
import { T } from "./content/texts";
import { AuthScreen } from "./features/auth/AuthScreen";
import { ChatScreen } from "./features/chat/ChatScreen";
import {
  clearSession,
  loadSession,
  read,
  saveSession,
  write,
  type Session,
} from "./storage";

export default function App() {
  const [session, setSession] = useState<Session | null>(loadSession);
  const [sandbox, setSandbox] = useState(
    apiMode === "mock" &&
      (!features.auth || read<string>("mode") === "sandbox"),
  );
  const [expired, setExpired] = useState(false);
  const [checking, setChecking] = useState(apiMode === "real" && !!session);
  const [serverStatus, setServerStatus] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (apiMode !== "real") return;
    let active = true;
    const waking = setTimeout(() => {
      if (active) setServerStatus(T.status_waking);
    }, 1500);
    void health()
      .then(() => {
        if (active) {
          clearTimeout(waking);
          setServerStatus("");
        }
      })
      .catch(() => {
        if (active) {
          clearTimeout(waking);
          setServerStatus(T.status_server_down);
        }
      });
    return () => {
      active = false;
      clearTimeout(waking);
    };
  }, [attempt]);

  useEffect(() => {
    if (apiMode !== "real") return;
    const saved = loadSession();
    if (!saved) {
      setChecking(false);
      return;
    }
    let active = true;
    void me(saved.token)
      .then((user) => {
        if (active && user) {
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
    setSandbox(false);
    setExpired(false);
    setServerStatus("");
    setAttempt((value) => value + 1);
  }
  function exit(isExpired = false) {
    clearSession();
    setSession(null);
    setSandbox(false);
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
  if (!session && !sandbox)
    return (
      <AuthScreen
        expired={expired}
        serverStatus={serverStatus}
        onSuccess={login}
        onSandbox={() => {
          setSandbox(true);
          write("mode", "sandbox");
        }}
      />
    );
  return (
    <ChatScreen
      key={session ? `${apiMode}:${session.user.id}` : "sandbox"}
      session={session}
      onExit={exit}
      serverStatus={serverStatus}
    />
  );
}
