import type { FormEvent } from 'react';
import { Button, Input } from './ui';

export function UrlInput({
  value,
  onChange,
  onSubmit,
  loading,
  onUpload,
  uploadDisabled,
  uploadAccept,
  busyLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  loading?: boolean;
  onUpload?: (file: File) => void;
  uploadDisabled?: boolean;
  uploadAccept?: string;
  busyLabel?: string;
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
        {loading ? busyLabel ?? 'Analyzing...' : 'Analyze Video →'}
      </Button>
      {onUpload ? (
        <label className="inline-flex min-h-12 cursor-pointer items-center justify-center rounded-xl border border-surface-600 px-4 text-sm text-slate-200 hover:border-accent-500/40">
          Upload video
          <input
            type="file"
            accept={uploadAccept ?? 'video/*,.mkv,.avi,.mov,.webm,.m4v'}
            className="sr-only"
            disabled={loading || uploadDisabled}
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
