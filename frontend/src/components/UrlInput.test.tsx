import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { UrlInput } from './UrlInput';

afterEach(cleanup);

describe('UrlInput video picker', () => {
  it('opens the native file picker when the upload button is clicked', () => {
    const inputClick = vi.spyOn(HTMLInputElement.prototype, 'click');
    render(<UrlInput value="" onChange={vi.fn()} onSubmit={vi.fn()} onUpload={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Upload video' }));

    expect(inputClick).toHaveBeenCalledOnce();
    inputClick.mockRestore();
  });

  it('passes a selected supported video to the upload handler', () => {
    const onUpload = vi.fn();
    const file = new File(['video'], 'clip.mp4', { type: 'video/mp4' });
    render(<UrlInput value="" onChange={vi.fn()} onSubmit={vi.fn()} onUpload={onUpload} />);

    fireEvent.change(screen.getByLabelText('Select a video file'), { target: { files: [file] } });

    expect(onUpload).toHaveBeenCalledWith(file);
  });
});
