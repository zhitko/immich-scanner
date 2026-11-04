import {
  corners,
  hitTest,
  movedRect,
  rectFromPoints,
  resizeFromEdge,
  resizeFromOpposite,
  rotationAngle,
  snapAngle,
  toLocal,
  toWorld,
} from './geometry';

describe('region geometry', () => {
  const rect = { centerX: 100, centerY: 80, width: 40, height: 20, angleDeg: 0 };

  it('round-trips a local point through the rotation', () => {
    const local = { x: 12, y: -4 };
    const world = toWorld({ ...rect, angleDeg: 25 }, local);
    const back = toLocal({ ...rect, angleDeg: 25 }, world);
    expect(back.x).toBeCloseTo(local.x);
    expect(back.y).toBeCloseTo(local.y);
  });

  it('points the width axis clockwise as the angle increases', () => {
    const edge = toWorld({ ...rect, angleDeg: 90 }, { x: 10, y: 0 });
    expect(edge.x).toBeCloseTo(rect.centerX);
    expect(edge.y).toBeCloseTo(rect.centerY + 10);
  });

  it('reads zero when the pointer is straight above the center', () => {
    expect(rotationAngle({ x: 10, y: 10 }, { x: 10, y: 0 })).toBeCloseTo(0);
    expect(rotationAngle({ x: 10, y: 10 }, { x: 20, y: 10 })).toBeCloseTo(90);
  });

  it('keeps the opposite corner fixed while resizing', () => {
    const opposite = toWorld(rect, { x: -rect.width / 2, y: rect.height / 2 });
    const next = resizeFromOpposite(rect, 'ne', { x: 150, y: 50 });
    const held = toWorld(next, { x: -next.width / 2, y: next.height / 2 });
    expect(held.x).toBeCloseTo(opposite.x);
    expect(held.y).toBeCloseTo(opposite.y);
    expect(next.width).toBeGreaterThan(rect.width);
  });

  it('moves one edge and leaves the opposite edge and the other side alone', () => {
    const left = toWorld(rect, { x: -rect.width / 2, y: 0 });
    const wider = resizeFromEdge(rect, 'e', { x: 150, y: 80 });
    const heldLeft = toWorld(wider, { x: -wider.width / 2, y: 0 });
    expect(heldLeft.x).toBeCloseTo(left.x);
    expect(heldLeft.y).toBeCloseTo(left.y);
    expect(wider.width).toBeCloseTo(70);
    expect(wider.height).toBe(rect.height);
    expect(wider.angleDeg).toBe(0);

    const bottom = toWorld(rect, { x: 0, y: rect.height / 2 });
    const taller = resizeFromEdge(rect, 'n', { x: 100, y: 40 });
    const heldBottom = toWorld(taller, { x: 0, y: taller.height / 2 });
    expect(heldBottom.x).toBeCloseTo(bottom.x);
    expect(heldBottom.y).toBeCloseTo(bottom.y);
    expect(taller.height).toBeCloseTo(50);
    expect(taller.width).toBe(rect.width);
  });

  it('slides a rotated edge along the print, not the screen', () => {
    const turned = { ...rect, angleDeg: 90 };
    const opposite = toWorld(turned, { x: -turned.width / 2, y: 0 });
    const next = resizeFromEdge(turned, 'e', { x: 100, y: 130 });
    const held = toWorld(next, { x: -next.width / 2, y: 0 });
    expect(held.x).toBeCloseTo(opposite.x);
    expect(held.y).toBeCloseTo(opposite.y);
    expect(next.height).toBe(turned.height);
    expect(next.width).toBeCloseTo(70);
  });

  it('keeps a side at least 8 pixels when the pointer crosses the opposite edge', () => {
    const next = resizeFromEdge(rect, 'e', { x: rect.centerX - rect.width / 2, y: rect.centerY });
    expect(next.width).toBe(8);
    expect(next.height).toBe(rect.height);
  });

  it('moves from the original pointer, not from the last increment', () => {
    const next = movedRect(rect, { x: 0, y: 0 }, { x: 5, y: -2 }, { width: 200, height: 200 });
    expect(next.centerX).toBe(105);
    expect(next.centerY).toBe(78);
    const clamped = movedRect(rect, { x: 0, y: 0 }, { x: -500, y: 0 }, { width: 200, height: 200 });
    expect(clamped.centerX).toBe(0);
  });

  it('hits the body, a corner, an edge, and the rotation handle', () => {
    expect(hitTest(rect, { x: 100, y: 80 }, 1, false)?.kind).toBe('move');
    expect(hitTest(rect, { x: 120, y: 70 }, 1, true)?.kind).toBe('resize');
    expect(hitTest(rect, { x: 100, y: 70 }, 1, true)).toEqual({ kind: 'edge', edge: 'n' });
    const wide = { centerX: 200, centerY: 150, width: 160, height: 100, angleDeg: 0 };
    expect(hitTest(wide, { x: 280, y: 150 }, 1, true)).toEqual({ kind: 'edge', edge: 'e' });
    expect(hitTest(wide, { x: 200, y: 90 }, 1, true)).toEqual({ kind: 'edge', edge: 'n' });
    expect(hitTest(rect, { x: 100, y: 70 }, 1, false)?.kind).toBe('move');
    expect(hitTest(rect, { x: 100, y: 70 - 26 }, 1, true)?.kind).toBe('rotate');
    expect(hitTest(rect, { x: 0, y: 0 }, 1, true)).toBeNull();
  });

  it('draws an upright rectangle between two points inside the bed', () => {
    const drawn = rectFromPoints({ x: 50, y: 40 }, { x: 10, y: 260 }, { width: 200, height: 200 });
    expect(drawn).toEqual({ centerX: 30, centerY: 120, width: 40, height: 160, angleDeg: 0 });
  });

  it('lists corners clockwise from the top-left', () => {
    const [topLeft, topRight] = corners(rect);
    expect(topLeft).toEqual({ x: 80, y: 70 });
    expect(topRight).toEqual({ x: 120, y: 70 });
  });

  it('snaps near-straight angles and steps when asked', () => {
    expect(snapAngle(1.2, null)).toBe(0);
    expect(snapAngle(-89, null)).toBe(-90);
    expect(snapAngle(7, null)).toBe(7);
    expect(snapAngle(22, 15)).toBe(15);
  });
});
