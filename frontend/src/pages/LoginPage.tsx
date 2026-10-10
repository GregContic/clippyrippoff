import { FormEvent, useState } from 'react';
import { Button, Card, Input } from '../components/ui';
import { useAuth } from '../auth';

export function LoginPage() {
  const { login, register, error } = useAuth();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);
    if (!username.trim() || !password) {
      setValidationError(mode === 'login' ? 'Enter your email and password.' : 'Enter your email and a password of at least 12 characters.');
      return;
    }
    if (mode === 'register' && password.length < 12) {
      setValidationError('Password must contain at least 12 characters.');
      return;
    }
    setSubmitting(true);
    try {
      if (mode === 'login') {
        await login(username, password);
      } else {
        await register(username, password);
        setMode('login');
        setPassword('');
        setValidationError(null);
      }
    } catch {
      // The provider exposes the server error below the form.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-surface-950 px-4 py-8 text-slate-100">
      <Card className="w-full max-w-md p-8">
        <div className="border-b border-surface-700 pb-6">
          <div className="text-[11px] uppercase tracking-[0.28em] text-slate-500">ClippyRipoff</div>
          <h1 className="mt-3 text-2xl font-semibold text-white">{mode === 'login' ? 'Sign in to your workspace' : 'Create your workspace account'}</h1>
          <p className="mt-2 text-sm leading-6 text-slate-400">{mode === 'login' ? 'Use your account credentials to continue.' : 'Create an account with an email and a strong password.'}</p>
        </div>
        <form className="mt-6 space-y-5" onSubmit={handleSubmit}>
          <label className="block text-sm font-medium text-slate-200">
            Email
            <Input className="mt-2" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </label>
          <label className="block text-sm font-medium text-slate-200">
            Password
            <Input className="mt-2" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
          </label>
          {validationError || error ? <p className="rounded-xl border border-danger-500/30 bg-danger-500/10 px-3 py-2 text-sm text-danger-100">{validationError || error}</p> : null}
          <Button className="w-full" type="submit" disabled={submitting}>{submitting ? (mode === 'login' ? 'Signing in…' : 'Creating account…') : mode === 'login' ? 'Sign in' : 'Create account'}</Button>
        </form>
        <button
          type="button"
          className="mt-5 w-full text-center text-sm text-accent-300 transition hover:text-accent-200"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login');
            setValidationError(null);
          }}
        >
          {mode === 'login' ? 'Need an account? Create one' : 'Already have an account? Sign in'}
        </button>
      </Card>
    </main>
  );
}
