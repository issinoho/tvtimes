import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const updateServiceWorker = vi.fn();
const setNeedRefresh = vi.fn();
let needRefresh = true;

vi.mock('virtual:pwa-register/react', () => ({
  useRegisterSW: () => ({
    needRefresh: [needRefresh, setNeedRefresh],
    offlineReady: [false, vi.fn()],
    updateServiceWorker,
  }),
}));

import { UpdatePrompt } from './UpdatePrompt';

describe('UpdatePrompt', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows nothing until an update is waiting', () => {
    needRefresh = false;
    const { container } = render(<UpdatePrompt />);
    expect(container).toBeEmptyDOMElement();
  });

  it('offers a Reload that activates the new service worker', async () => {
    needRefresh = true;
    render(<UpdatePrompt />);
    expect(screen.getByText(/new version of tvtimes/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reload' }));
    expect(updateServiceWorker).toHaveBeenCalledWith(true);
  });

  it('Later dismisses without reloading', async () => {
    needRefresh = true;
    render(<UpdatePrompt />);
    await userEvent.click(screen.getByRole('button', { name: 'Later' }));
    expect(setNeedRefresh).toHaveBeenCalledWith(false);
    expect(updateServiceWorker).not.toHaveBeenCalled();
  });
});
