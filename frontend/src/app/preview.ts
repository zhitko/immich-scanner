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

export type PhotoVersion = 'crop' | 'retouch';

/** The version set to upload. A retouch that is not current never counts. */
export function chosenVersion(region: {
  upload_source: string;
  retouch_ready: boolean;
}): PhotoVersion {
  return region.upload_source === 'retouch' && region.retouch_ready ? 'retouch' : 'crop';
}

/** Holding the image shows the other version, when there is a current one to compare. */
export function shownVersion(
  base: PhotoVersion,
  retouchReady: boolean,
  holding: boolean,
): PhotoVersion {
  if (!holding || !retouchReady) {
    return base;
  }
  return base === 'retouch' ? 'crop' : 'retouch';
}

export function uploadVersionLabel(region: {
  upload_source: string;
  retouch_ready: boolean;
}): string {
  if (chosenVersion(region) === 'retouch') {
    return 'Upload sends the retouched image.';
  }
  if (region.upload_source === 'retouch') {
    return 'Retouch is out of date, so this photo will not upload until you run it again or switch to Original.';
  }
  return 'Upload sends the original crop.';
}

/** Width / height of the frame after `quarterTurns` clockwise steps. */
export function displayedAspect(width: number, height: number, quarterTurns: number): number {
  const odd = quarterTurns % 2 === 1;
  const across = odd ? height : width;
  const down = odd ? width : height;
  return down > 0 ? across / down : 1;
}
