import { displayedAspect, previewCacheKey } from './preview';

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
