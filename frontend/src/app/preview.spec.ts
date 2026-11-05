import {
  chosenVersion,
  displayedAspect,
  previewCacheKey,
  shownVersion,
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
