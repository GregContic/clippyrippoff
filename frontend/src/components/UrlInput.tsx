import type { FormEvent } from 'react';
import { Button, Input } from './ui';

export function UrlInput({
  value,
  onChange,
  onSubmit,
  loading,
  onUpload,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading?: boolean;
  onUpload?: (file: File) => void;
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
      {onUpload ? (
        <label className="inline-flex min-h-12 cursor-pointer items-center justify-center rounded-xl border border-surface-600 px-4 text-sm text-slate-200 hover:border-accent-500/40">
          Upload video
          <input
            type="file"
            accept="video/*,.mkv,.avi,.mov,.webm,.m4v"
            className="sr-only"
            disabled={loading}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onUpload(file);
              event.currentTarget.value = '';
            }}
          />
        </label>
      ) : null}
    </form>
  );
}
