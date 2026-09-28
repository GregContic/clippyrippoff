import type { FormEvent } from 'react';
import { Button, Input } from './ui';

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
      <Input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Paste YouTube URL here"
        className="min-h-12 flex-1"
      />
      <Button type="submit" disabled={loading} className="min-h-12 px-5">
        {loading ? 'Analyzing...' : 'Analyze Video →'}
      </Button>
    </form>
  );
}
