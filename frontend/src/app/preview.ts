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

/** Real-ESRGAN in the retouch catalog enlarges each edge by this much. */
const RETOUCH_UPSCALE = 4;

/**
 * Pixel size of the upright crop, matching `upright_crop`: round to whole
 * pixels, then swap axes on an odd quarter turn.
 */
export function uprightPixels(
  width: number,
  height: number,
  quarterTurns: number,
): { width: number; height: number } {
  const across = Math.max(1, Math.round(width));
  const down = Math.max(1, Math.round(height));
  return quarterTurns % 2 === 1 ? { width: down, height: across } : { width: across, height: down };
}

/**
 * Facts for the photo in the large preview. The retouch line uses the
 * enlarged file when that version is on screen and upscale was part of it.
 * Denoise alone keeps the crop size.
 */
export function formatPhotoFacts(
  region: {
    width: number;
    height: number;
    quarter_turns: number;
    retouch_upscale: boolean;
  },
  dpi: number | null,
  version: PhotoVersion,
): string {
  const base = uprightPixels(region.width, region.height, region.quarter_turns);
  const enlarged = version === 'retouch' && region.retouch_upscale;
  const scale = enlarged ? RETOUCH_UPSCALE : 1;
  const width = base.width * scale;
  const height = base.height * scale;
  const scanDpi = dpi != null && dpi > 0 ? dpi : null;
  const fileDpi = scanDpi == null ? null : Math.max(1, Math.round(scanDpi * scale));
  const parts = [`${width} × ${height} px`, megapixels(width, height)];
  if (fileDpi != null) {
    parts.push(`${fileDpi} dpi`);
  }
  if (scanDpi != null) {
    parts.push(printSize(base.width, base.height, scanDpi));
  }
  return parts.filter((part) => part.length > 0).join(' · ');
}

function megapixels(width: number, height: number): string {
  const value = (width * height) / 1_000_000;
  if (value < 0.1) {
    return '';
  }
  return `${value.toFixed(1)} MP`;
}

function printSize(width: number, height: number, dpi: number): string {
  const widthMm = (width / dpi) * 25.4;
  const heightMm = (height / dpi) * 25.4;
  if (widthMm >= 10 && heightMm >= 10) {
    return `${(widthMm / 10).toFixed(1)} × ${(heightMm / 10).toFixed(1)} cm`;
  }
  return `${Math.round(widthMm)} × ${Math.round(heightMm)} mm`;
}
