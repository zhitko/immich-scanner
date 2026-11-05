import {
  chosenVersion,
  displayedAspect,
  formatPhotoFacts,
  previewCacheKey,
  shownVersion,
  uprightPixels,
  uploadVersionLabel,
} from './preview';

describe('preview orientation', () => {
  const region = {
    center_x: 10,
    center_y: 20,
    width: 400,
    height: 200,
    angle_deg: 0,
  };

  it('swaps the frame when the photo is on its side', () => {
    expect(displayedAspect(400, 200, 0)).toBeCloseTo(2);
    expect(displayedAspect(400, 200, 1)).toBeCloseTo(0.5);
    expect(displayedAspect(400, 200, 2)).toBeCloseTo(2);
    expect(displayedAspect(400, 200, 3)).toBeCloseTo(0.5);
  });

  it('changes the image only when the crop changes', () => {
    expect(previewCacheKey(region)).toBe(previewCacheKey({ ...region }));
    expect(previewCacheKey(region)).not.toBe(previewCacheKey({ ...region, angle_deg: 15 }));
  });
});

describe('retouch preview choice', () => {
  it('shows the version chosen for upload', () => {
    expect(chosenVersion({ upload_source: 'crop', retouch_ready: true })).toBe('crop');
    expect(chosenVersion({ upload_source: 'retouch', retouch_ready: true })).toBe('retouch');
    expect(chosenVersion({ upload_source: 'retouch', retouch_ready: false })).toBe('crop');
  });

  it('shows the other version only while the image is held', () => {
    expect(shownVersion('crop', true, false)).toBe('crop');
    expect(shownVersion('crop', true, true)).toBe('retouch');
    expect(shownVersion('retouch', true, true)).toBe('crop');
    expect(shownVersion('crop', false, true)).toBe('crop');
  });

  it('describes the upright crop under the large preview', () => {
    const region = {
      width: 1800.4,
      height: 1200.2,
      quarter_turns: 0,
      retouch_upscale: false,
    };
    expect(uprightPixels(1800.4, 1200.2, 0)).toEqual({ width: 1800, height: 1200 });
    expect(uprightPixels(1800.4, 1200.2, 1)).toEqual({ width: 1200, height: 1800 });
    expect(formatPhotoFacts(region, 600, 'crop')).toBe(
      '1800 × 1200 px · 2.2 MP · 600 dpi · 7.6 × 5.1 cm',
    );
    expect(formatPhotoFacts(region, null, 'crop')).toBe('1800 × 1200 px · 2.2 MP');
    expect(formatPhotoFacts({ ...region, width: 40, height: 30 }, 600, 'crop')).toBe(
      '40 × 30 px · 600 dpi · 2 × 1 mm',
    );
  });

  it('uses the enlarged file when the retouch on screen was upscaled', () => {
    const region = {
      width: 800,
      height: 600,
      quarter_turns: 0,
      retouch_upscale: true,
    };
    expect(formatPhotoFacts(region, 300, 'crop')).toBe(
      '800 × 600 px · 0.5 MP · 300 dpi · 6.8 × 5.1 cm',
    );
    expect(formatPhotoFacts(region, 300, 'retouch')).toBe(
      '3200 × 2400 px · 7.7 MP · 1200 dpi · 6.8 × 5.1 cm',
    );
  });

  it('keeps the crop size when the retouch on screen was not upscaled', () => {
    const region = {
      width: 800,
      height: 600,
      quarter_turns: 0,
      retouch_upscale: false,
    };
    expect(formatPhotoFacts(region, 300, 'retouch')).toBe(
      '800 × 600 px · 0.5 MP · 300 dpi · 6.8 × 5.1 cm',
    );
  });

  it('says which pixels an upload will send', () => {
    expect(uploadVersionLabel({ upload_source: 'crop', retouch_ready: false })).toBe(
      'Upload sends the original crop.',
    );
    expect(uploadVersionLabel({ upload_source: 'crop', retouch_ready: true })).toBe(
      'Upload sends the original crop.',
    );
    expect(uploadVersionLabel({ upload_source: 'retouch', retouch_ready: true })).toBe(
      'Upload sends the retouched image.',
    );
    expect(uploadVersionLabel({ upload_source: 'retouch', retouch_ready: false })).toContain(
      'out of date',
    );
  });
});
