export interface Point {
  x: number;
  y: number;
}

export interface Rect {
  centerX: number;
  centerY: number;
  width: number;
  height: number;
  angleDeg: number;
}

export interface Bounds {
  width: number;
  height: number;
}

export type Corner = 'nw' | 'ne' | 'se' | 'sw';

export type Hit = { kind: 'rotate' } | { kind: 'resize'; corner: Corner } | { kind: 'move' };

const CORNER_SIGN: Record<Corner, Point> = {
  nw: { x: -1, y: -1 },
  ne: { x: 1, y: -1 },
  se: { x: 1, y: 1 },
  sw: { x: -1, y: 1 },
};

/** Screen pixels, converted by the caller into original-image pixels. */
export const HANDLE_GAP_PX = 26;
export const HANDLE_TOLERANCE_PX = 14;

/**
 * OpenCV `RotatedRect` and the canvas both treat a positive angle as clockwise
 * when the Y axis points down. `ctx.rotate(angle)` therefore matches the crop.
 */
export function toWorld(rect: Rect, local: Point): Point {
  const rad = (rect.angleDeg * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  return {
    x: rect.centerX + local.x * cos - local.y * sin,
    y: rect.centerY + local.x * sin + local.y * cos,
  };
}

export function toLocal(rect: Rect, point: Point): Point {
  const dx = point.x - rect.centerX;
  const dy = point.y - rect.centerY;
  const rad = (rect.angleDeg * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  return {
    x: dx * cos + dy * sin,
    y: -dx * sin + dy * cos,
  };
}

/** Angle whose upright direction points from `center` toward `pointer`. */
export function rotationAngle(center: Point, pointer: Point): number {
  const dx = pointer.x - center.x;
  const dy = pointer.y - center.y;
  return normalizeAngle((Math.atan2(dx, -dy) * 180) / Math.PI);
}

export function normalizeAngle(deg: number): number {
  const wrapped = ((((deg + 180) % 360) + 360) % 360) - 180;
  return wrapped === -180 ? 180 : wrapped;
}

export function clampRect(rect: Rect, bounds: Bounds): Rect {
  return {
    ...rect,
    centerX: clamp(rect.centerX, 0, bounds.width),
    centerY: clamp(rect.centerY, 0, bounds.height),
    width: clamp(rect.width, 8, bounds.width * 2),
    height: clamp(rect.height, 8, bounds.height * 2),
    angleDeg: normalizeAngle(rect.angleDeg),
  };
}

export function movedRect(start: Rect, origin: Point, pointer: Point, bounds: Bounds): Rect {
  return {
    ...start,
    centerX: clamp(start.centerX + (pointer.x - origin.x), 0, bounds.width),
    centerY: clamp(start.centerY + (pointer.y - origin.y), 0, bounds.height),
  };
}

export function resizeFromOpposite(rect: Rect, corner: Corner, pointer: Point): Rect {
  const sign = CORNER_SIGN[corner];
  const fixed = toWorld(rect, {
    x: -sign.x * (rect.width / 2),
    y: -sign.y * (rect.height / 2),
  });
  const centerX = (fixed.x + pointer.x) / 2;
  const centerY = (fixed.y + pointer.y) / 2;
  const local = toLocal({ ...rect, centerX, centerY }, pointer);
  return {
    centerX,
    centerY,
    width: Math.max(8, Math.abs(local.x) * 2),
    height: Math.max(8, Math.abs(local.y) * 2),
    angleDeg: rect.angleDeg,
  };
}

export function hitTest(rect: Rect, point: Point, scale: number, selected: boolean): Hit | null {
  if (selected) {
    const tolerance = HANDLE_TOLERANCE_PX / scale;
    const gap = HANDLE_GAP_PX / scale;
    const handle = toWorld(rect, { x: 0, y: -rect.height / 2 - gap });
    if (distance(handle, point) <= tolerance) {
      return { kind: 'rotate' };
    }
    for (const corner of Object.keys(CORNER_SIGN) as Corner[]) {
      const sign = CORNER_SIGN[corner];
      const world = toWorld(rect, {
        x: sign.x * (rect.width / 2),
        y: sign.y * (rect.height / 2),
      });
      if (distance(world, point) <= tolerance) {
        return { kind: 'resize', corner };
      }
    }
  }
  const local = toLocal(rect, point);
  if (Math.abs(local.x) <= rect.width / 2 && Math.abs(local.y) <= rect.height / 2) {
    return { kind: 'move' };
  }
  return null;
}

export function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
