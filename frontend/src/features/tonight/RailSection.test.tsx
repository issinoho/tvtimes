import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { RailSection } from '@/features/tonight/RailSection';

/**
 * jsdom has no box model, so a rail's own widths have to be dictated: these
 * two getters are the whole of what decides an arrow is needed. The real
 * scrolling is measured in RailSection.browser.test.tsx.
 */
function railWidths(client: number, scroll: number) {
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(client);
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(scroll);
}

function cards(n: number) {
  return Array.from({ length: n }, (_, i) => (
    <button key={i} type="button">
      Card {i}
    </button>
  ));
}

afterEach(() => {
  vi.restoreAllMocks();
});

test('a rail that overflows gets arrows, and one scrolls it a near-screenful', async () => {
  railWidths(600, 2000);
  const scrollBy = vi.spyOn(HTMLElement.prototype, 'scrollBy').mockImplementation(() => {});
  render(<RailSection heading="Films on soon">{cards(12)}</RailSection>);
  const user = userEvent.setup();

  const forward = screen.getByRole('button', { name: 'Scroll forward through Films on soon' });
  await user.click(forward);

  expect(scrollBy).toHaveBeenCalledWith(expect.objectContaining({ left: 510 }));
});

test('the far end of a rail is dimmed but still focusable, so a d-pad keeps its place', () => {
  railWidths(600, 2000);
  render(<RailSection heading="Films on soon">{cards(12)}</RailSection>);

  // scrollLeft is 0 — there is nothing to the left yet.
  const back = screen.getByRole('button', { name: 'Scroll back through Films on soon' });
  expect(back).toHaveAttribute('aria-disabled', 'true');
  expect(back).not.toBeDisabled();
  expect(
    screen.getByRole('button', { name: 'Scroll forward through Films on soon' }),
  ).toHaveAttribute('aria-disabled', 'false');
});

test('a rail with nowhere to scroll draws no arrows', () => {
  railWidths(600, 600);
  render(<RailSection heading="Films on soon">{cards(2)}</RailSection>);

  expect(screen.queryByRole('button', { name: /^Scroll/ })).not.toBeInTheDocument();
  expect(screen.getByRole('group', { name: 'Films on soon' })).toBeInTheDocument();
});

test('an empty rail renders its note instead, heading and control intact', () => {
  railWidths(600, 2000);
  render(
    <RailSection
      heading="On now"
      control={<button type="button">★ Favourites</button>}
      note={<p>Nothing on air right now.</p>}
    />,
  );

  expect(screen.getByRole('heading', { name: 'On now' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '★ Favourites' })).toBeInTheDocument();
  expect(screen.getByText('Nothing on air right now.')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Scroll/ })).not.toBeInTheDocument();
});
