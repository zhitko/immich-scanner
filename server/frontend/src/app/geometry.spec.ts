import {
  hitTest,
  movedRect,
  resizeFromOpposite,
  rotationAngle,
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

  it('moves from the original pointer, not from the last increment', () => {
    const next = movedRect(rect, { x: 0, y: 0 }, { x: 5, y: -2 }, { width: 200, height: 200 });
    expect(next.centerX).toBe(105);
    expect(next.centerY).toBe(78);
    const clamped = movedRect(rect, { x: 0, y: 0 }, { x: -500, y: 0 }, { width: 200, height: 200 });
    expect(clamped.centerX).toBe(0);
  });

  it('hits the body, a corner, and the rotation handle', () => {
    expect(hitTest(rect, { x: 100, y: 80 }, 1, false)?.kind).toBe('move');
    expect(hitTest(rect, { x: 120, y: 70 }, 1, true)?.kind).toBe('resize');
    expect(hitTest(rect, { x: 100, y: 70 - 26 }, 1, true)?.kind).toBe('rotate');
    expect(hitTest(rect, { x: 0, y: 0 }, 1, true)).toBeNull();
  });
});
