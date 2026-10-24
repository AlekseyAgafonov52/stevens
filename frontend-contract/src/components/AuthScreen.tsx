/** Экран входа — 02-screens.md, раздел 1; проверка полей — 03-behavior.md, раздел 8. */
import { CircleAlert, Eye, EyeOff } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { ApiFailure, errorKey } from '../api';
import { T } from '../content/texts';
import { LoginTitleAside } from '../extensions/points';
import { authenticate, chooseSandbox } from '../state/session';
import { useApp } from '../state/store';
import { Dots } from './Dots';

const LOGIN_RE = /^[A-Za-zА-Яа-яЁё0-9._-]{3,32}$/;
type Tab = 'login' | 'register';
type Errors = { login?: string; password?: string; common?: string };

function validate(login: string, password: string): Errors {
  const errors: Errors = {};
  if (!LOGIN_RE.test(login.trim())) errors.login = T.auth_err_login_format;
  if (password.length < 5 || password.length > 128) errors.password = T.auth_err_password_short;
  return errors;
}

function serverErrors(error: unknown): Errors {
  if (error instanceof ApiFailure && error.error.type === 'http') {
    const { status, code } = error.error;
    if (status === 401) return { common: T.auth_err_credentials };
    if (code === 'login_taken') return { login: T.auth_err_login_taken };
    if (code === 'invalid_login') return { login: T.auth_err_login_format };
    if (code === 'invalid_password') return { password: T.auth_err_password_short };
  }
  return { common: T[errorKey(error) === 'err_network' ? 'err_network' : 'err_server'] };
}

export function AuthScreen() {
  const notice = useApp((s) => s.authNotice);
  const server = useApp((s) => s.server);
  const [tab, setTab] = useState<Tab>('login');
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [visible, setVisible] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const phone = typeof window !== 'undefined' && window.matchMedia('(max-width: 760px)').matches;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    const found = validate(login, password);
    setErrors(found);
    if (found.login || found.password) return;
    setBusy(true);
    try {
      await authenticate(tab, login.trim(), password);
    } catch (error) {
      setErrors(serverErrors(error));
      setBusy(false);
    }
  };

  const switchTab = (next: Tab) => {
    setTab(next);
    setErrors({});
  };

  return (
    <main className="auth">
      <div className="auth__column">
        <div className="auth__title-row">
          <h1 className="auth__title">{T.app_name}</h1>
          <LoginTitleAside />
        </div>
        <p className="auth__subtitle">{T.start_subtitle}</p>
        {notice === 'expired' && <div className="auth__notice">{T.auth_session_expired}</div>}

        <form className="auth__card" onSubmit={submit} noValidate>
          <div className="auth__tabs" role="tablist">
            {(['login', 'register'] as const).map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t}
                className={`auth__tab ${tab === t ? 'auth__tab--active' : ''}`} onClick={() => switchTab(t)}>
                {t === 'login' ? T.auth_tab_login : T.auth_tab_register}
              </button>
            ))}
          </div>

          <label className="field field--first">
            <span className="field__label">{T.auth_field_login}</span>
            <input
              className={`field__input ${errors.login ? 'field__input--error' : ''}`}
              value={login}
              autoComplete="username"
              autoFocus={!phone}
              disabled={busy}
              onChange={(e) => { setLogin(e.target.value); setErrors((v) => ({ ...v, login: undefined })); }}
            />
            {errors.login && <span className="field__error">{errors.login}</span>}
          </label>

          <label className="field">
            <span className="field__label">{T.auth_field_password}</span>
            <span className="field__wrap">
              <input
                className={`field__input field__input--password ${errors.password ? 'field__input--error' : ''}`}
                type={visible ? 'text' : 'password'}
                maxLength={128}
                value={password}
                autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
                disabled={busy}
                onChange={(e) => { setPassword(e.target.value); setErrors((v) => ({ ...v, password: undefined })); }}
              />
              <button type="button" className="field__eye" aria-label={visible ? T.auth_hide_password : T.auth_show_password}
                onClick={() => setVisible((v) => !v)}>
                {visible ? <EyeOff size={18} strokeWidth={1.5} aria-hidden="true" /> : <Eye size={18} strokeWidth={1.5} aria-hidden="true" />}
              </button>
            </span>
            {errors.password && <span className="field__error">{errors.password}</span>}
          </label>

          {errors.common && (
            <div className="auth__common-error" role="alert">
              <CircleAlert size={14} strokeWidth={1.5} aria-hidden="true" />
              {errors.common}
            </div>
          )}

          <button type="submit" className="auth__submit" disabled={busy}>
            {busy ? <Dots className="dots--light" /> : tab === 'login' ? T.auth_submit_login : T.auth_submit_register}
          </button>
          {tab === 'register' && <p className="auth__hint auth__hint--register">{T.auth_register_hint}</p>}
        </form>

        <div className="auth__or"><span>{T.auth_or}</span></div>
        <button type="button" className="auth__sandbox" onClick={chooseSandbox}>{T.auth_sandbox_button}</button>
        <p className="auth__hint">{T.auth_sandbox_hint}</p>

        {server === 'waking' && <p className="auth__status">{T.status_waking}</p>}
        {server === 'down' && (
          <p className="auth__status auth__status--alarm">
            <CircleAlert size={14} strokeWidth={1.5} aria-hidden="true" />
            {T.status_server_down}
          </p>
        )}
      </div>
    </main>
  );
}
