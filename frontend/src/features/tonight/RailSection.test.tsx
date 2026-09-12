import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import { RailSection } from '@/features/tonight/RailSection';

/**
 * Structure only. Whether an arrow appears, and where a press lands the rail,
 * are questions about the box model — jsdom has none, and faking scrollWidth
 * to answer them here is how the late-mount bug passed a green suite once
 * already. Those live in rail-arrows.browser.test.tsx, in a real browser.
 */

function cards(n: number) {
  return Array.from({ length: n }, (_, i) => (
    <button key={i} type="button">
      Card {i}
    </button>
  ));
}

test('the rail is a group named by its heading, holding the cards', () => {
  render(<RailSection heading="Films on soon">{cards(3)}</RailSection>);

  const rail = screen.getByRole('group', { name: 'Films on soon' });
  expect(rail).toContainElement(screen.getByRole('button', { name: 'Card 0' }));
  expect(screen.getByRole('heading', { name: 'Films on soon' })).toBeInTheDocument();
});

test('with no cards there is no rail at all, so nothing announces an empty row', () => {
  render(<RailSection heading="Films on soon" />);

  expect(screen.queryByRole('group')).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Films on soon' })).toBeInTheDocument();
});

test('a note replaces the rail, leaving the heading and its control in place', () => {
  render(
    <RailSection
      heading="On now"
      control={<button type="button">★ Favourites</button>}
      note={<p>Nothing on air right now.</p>}
    >
      {cards(3)}
    </RailSection>,
  );

  expect(screen.getByRole('heading', { name: 'On now' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '★ Favourites' })).toBeInTheDocument();
  expect(screen.getByText('Nothing on air right now.')).toBeInTheDocument();
  expect(screen.queryByRole('group')).not.toBeInTheDocument();
});
