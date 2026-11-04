import { Region } from './models';

/**
 * Identity of the unrotated crop. Quarter turns are drawn in CSS so the
 * preview turns with the click, matching `apply_quarter_turns` (clockwise).
 */
export function previewCacheKey(
  region: Pick<Region, 'center_x' | 'center_y' | 'width' | 'height' | 'angle_deg'>,
): string {
  return `${region.center_x}:${region.center_y}:${region.width}:${region.height}:${region.angle_deg}`;
}

/** Width / height of the frame after `quarterTurns` clockwise steps. */
export function displayedAspect(width: number, height: number, quarterTurns: number): number {
  const odd = quarterTurns % 2 === 1;
  const across = odd ? height : width;
  const down = odd ? width : height;
  return down > 0 ? across / down : 1;
}
