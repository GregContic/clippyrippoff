import { FormEvent, useState } from 'react';
import { Button, Card, Input } from '../components/ui';
import { useAuth } from '../auth';

export function LoginPage() {
  const { login, error } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);
    if (!username.trim() || !password) {
      setValidationError('Enter your username and password.');
      return;
    }
    setSubmitting(true);
    try {
      await login(username, password);
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
          <h1 className="mt-3 text-2xl font-semibold text-white">Sign in to your workspace</h1>
          <p className="mt-2 text-sm leading-6 text-slate-400">Use the owner account created during local or deployment setup.</p>
        </div>
        <form className="mt-6 space-y-5" onSubmit={handleSubmit}>
          <label className="block text-sm font-medium text-slate-200">
            Username
            <Input className="mt-2" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </label>
          <label className="block text-sm font-medium text-slate-200">
            Password
            <Input className="mt-2" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
          </label>
          {validationError || error ? <p className="rounded-xl border border-danger-500/30 bg-danger-500/10 px-3 py-2 text-sm text-danger-100">{validationError || error}</p> : null}
          <Button className="w-full" type="submit" disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in'}</Button>
        </form>
      </Card>
    </main>
  );
}
