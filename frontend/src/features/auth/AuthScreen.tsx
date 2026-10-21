import { useState } from "react";
import { CircleAlert, Eye, EyeOff } from "lucide-react";
import { authenticate, ApiError } from "../../api";
import type { AuthResponse } from "../../api/types";
import { T } from "../../content/texts";
import { apiMode } from "../../config/features";

export function AuthScreen({
  onSuccess,
  onSandbox,
  expired,
  serverStatus,
}: {
  onSuccess: (response: AuthResponse) => void;
  onSandbox: () => void;
  expired: boolean;
  serverStatus: string;
}) {
  const [register, setRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setError(T.auth_err_login_format);
      return;
    }
    if (register && !name.trim()) {
      setError(T.auth_err_name);
      return;
    }
    if (
      !password ||
      (register && password.length < 6) ||
      password.length > 128
    ) {
      setError(T.auth_err_password_short);
      return;
    }
    setBusy(true);
    try {
      onSuccess(
        await authenticate(
          {
            email: email.trim(),
            password,
            ...(register ? { name: name.trim() } : {}),
          },
          register,
        ),
      );
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : T.err_server);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <div className="auth-column">
        <h1 className="auth-brand">{T.app_name}</h1>
        <p className="auth-subtitle">{T.start_subtitle}</p>
        {expired && (
          <p className="session-expired" role="status">
            {T.auth_session_expired}
          </p>
        )}
        <form className="auth-card" onSubmit={submit}>
          <div className="auth-tabs" aria-label={T.profile_label}>
            <button
              type="button"
              className={!register ? "active" : ""}
              disabled={busy}
              onClick={() => {
                setRegister(false);
                setError("");
              }}
            >
              {T.auth_tab_login}
            </button>
            <button
              type="button"
              className={register ? "active" : ""}
              disabled={busy}
              onClick={() => {
                setRegister(true);
                setError("");
              }}
            >
              {T.auth_tab_register}
            </button>
          </div>
          {register && (
            <label className="form-field">
              {T.auth_field_name}
              <input
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setError("");
                }}
                autoComplete="name"
                maxLength={255}
                disabled={busy}
                required
              />
            </label>
          )}
          <label className="form-field">
            {T.auth_field_login}
            <input
              type="email"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
                setError("");
              }}
              autoComplete="username"
              maxLength={255}
              disabled={busy}
              required
            />
          </label>
          <label className="form-field" htmlFor="password">
            {T.auth_field_password}
          </label>
          <div className="password-field">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                setError("");
              }}
              autoComplete={register ? "new-password" : "current-password"}
              minLength={register ? 6 : 1}
              maxLength={128}
              disabled={busy}
              required
            />
            <button
              type="button"
              aria-label={
                showPassword ? T.auth_hide_password : T.auth_show_password
              }
              onClick={() => setShowPassword((value) => !value)}
            >
              {showPassword ? (
                <EyeOff strokeWidth={1.5} />
              ) : (
                <Eye strokeWidth={1.5} />
              )}
            </button>
          </div>
          {error && (
            <p className="auth-error" role="alert">
              <CircleAlert strokeWidth={1.5} />
              {error}
            </p>
          )}
          <button className="primary-submit" disabled={busy}>
            {busy ? (
              <span className="thinking" aria-label={T.auth_check}>
                <i />
                <i />
                <i />
              </span>
            ) : register ? (
              T.auth_submit_register
            ) : (
              T.auth_submit_login
            )}
          </button>
          {register && <p className="auth-hint">{T.auth_register_hint}</p>}
        </form>
        {apiMode === "mock" && (
          <>
            <div className="auth-or">
              <span>{T.auth_or}</span>
            </div>
            <button className="sandbox-button" onClick={onSandbox}>
              {T.auth_sandbox_button}
            </button>
            <p className="auth-hint">{T.auth_sandbox_hint}</p>
          </>
        )}
        <p className="auth-status" role="status">
          {serverStatus ||
            (apiMode === "mock" ? T.mock_login_hint : T.real_hint)}
        </p>
      </div>
    </main>
  );
}
