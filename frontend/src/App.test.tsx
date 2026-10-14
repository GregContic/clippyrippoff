import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

vi.mock('./auth', () => ({
  useAuth: () => ({ user: { id: 'user-1', username: 'tester' }, loading: false, logout: vi.fn() }),
}));

vi.mock('./components/Sidebar', () => ({ Sidebar: () => <div /> }));
vi.mock('./components/TopBar', () => ({ TopBar: () => <div /> }));
vi.mock('./pages/AnalyzePage', () => ({ AnalyzePage: () => <div>Analysis page</div> }));
vi.mock('./pages/ProjectWorkspacePage', () => ({ ProjectWorkspacePage: () => <div>Project workspace</div> }));
vi.mock('./pages/DashboardPage', () => ({ DashboardPage: () => <div>Dashboard page</div> }));
vi.mock('./pages/RendersPage', () => ({ RendersPage: () => <div>Renders page</div> }));
vi.mock('./pages/LibraryPage', () => ({ LibraryPage: () => <div>Library page</div> }));
vi.mock('./pages/SettingsPage', () => ({ SettingsPage: () => <div>Settings page</div> }));
vi.mock('./pages/ProjectsPage', () => ({ ProjectsPage: () => <div>Projects page</div> }));
vi.mock('./pages/LoginPage', () => ({ LoginPage: () => <div>Login page</div> }));
vi.mock('./pages/AboutPage', () => ({ AboutPage: () => <div>About page</div> }));

function LocationPath() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}${location.hash}`}</output>;
}

function renderApp(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <App />
      <LocationPath />
    </MemoryRouter>,
  );
}

afterEach(cleanup);

describe('project workspace routes', () => {
  it('redirects legacy project paths to the canonical workspace and preserves query/hash', async () => {
    renderApp('/analyze/video-123?source=history#renders');

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/projects/video-123?source=history#renders');
    });
    expect(screen.getByText('Project workspace')).toBeTruthy();
  });

  it('keeps /analyze without a video ID on the analysis page', () => {
    renderApp('/analyze?source=menu');

    expect(screen.getByTestId('location').textContent).toBe('/analyze?source=menu');
    expect(screen.getByText('Analysis page')).toBeTruthy();
  });
});
