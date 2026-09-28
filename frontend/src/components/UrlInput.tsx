import type { FormEvent } from 'react';
import { Button } from './ui';

export function UrlInput({
  value,
  onChange,
  onSubmit,
  loading,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading?: boolean;
}) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row">
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Paste YouTube URL here"
        className="min-h-12 flex-1 rounded-2xl border border-slate-700 bg-slate-950/80 px-4 py-3 text-sm text-white placeholder:text-slate-500 outline-none transition focus:border-sky-400/60 focus:ring-2 focus:ring-sky-400/20"
      />
      <Button type="submit" disabled={loading} className="min-h-12 px-5">
        {loading ? 'Analyzing...' : 'Analyze Video →'}
      </Button>
    </form>
  );
}
