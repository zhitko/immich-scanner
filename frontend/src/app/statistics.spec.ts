import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { Statistics } from './models';
import { StatisticsPage } from './statistics';

describe('StatisticsPage', () => {
  let http: HttpTestingController;
  const empty: Statistics = {
    scans: 0,
    scans_uploaded: 0,
    scans_cleaned_up: 0,
    detection_errors: 0,
    photos: 0,
    uploaded: 0,
    pending: 0,
    uploading: 0,
    failed: 0,
    with_date: 0,
    with_description: 0,
    with_album: 0,
    with_location: 0,
    favorites: 0,
    with_rating: 0,
    metadata_synced: 0,
    albums: 0,
    retouched: 0,
    retouched_upscale: 0,
    retouched_denoise: 0,
    retouched_faces: 0,
    retouched_colorize: 0,
    retouched_scratches: 0,
    retouched_color_balance: 0,
    retouched_contrast: 0,
    first_scan_at: null,
    latest_scan_at: null,
    earliest_photo_at: null,
    latest_photo_at: null,
    latest_upload_at: null,
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [StatisticsPage],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('handles an empty collection without invalid percentages or dates', () => {
    const fixture = TestBed.createComponent(StatisticsPage);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Loading statistics');
    http.expectOne('/api/statistics').flush(empty);
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('No scans yet');
    expect(text).toContain('Not available');
    expect(text).not.toMatch(/NaN|Infinity/);
    expect(fixture.componentInstance.percentage(0, 0)).toBe(0);
  });

  it('renders totals and coverage and refreshes without overlapping requests', () => {
    const fixture = TestBed.createComponent(StatisticsPage);
    fixture.componentInstance.load();
    const request = http.expectOne('/api/statistics');
    expect(request.request.method).toBe('GET');
    request.flush({ ...empty, scans: 2, photos: 4, uploaded: 3, with_description: 2 });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('75% of photos');
    const progress = fixture.nativeElement.querySelector(
      'progress[aria-label="Description"]',
    ) as HTMLProgressElement;
    expect(progress.value).toBe(2);
    expect(progress.max).toBe(4);

    (fixture.nativeElement.querySelector('button') as HTMLButtonElement).click();
    http.expectOne('/api/statistics').flush({ ...empty, scans: 3 });
    expect(fixture.componentInstance.statistics()?.scans).toBe(3);
  });

  it('shows errors and allows retry while retaining previously loaded totals', () => {
    const fixture = TestBed.createComponent(StatisticsPage);
    http.expectOne('/api/statistics').error(new ProgressEvent('error'));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain(
      'unreachable',
    );
    expect(fixture.componentInstance.loading()).toBe(false);

    fixture.componentInstance.load();
    http.expectOne('/api/statistics').flush({ ...empty, scans: 2 });
    fixture.componentInstance.load();
    http
      .expectOne('/api/statistics')
      .flush('Unavailable', { status: 503, statusText: 'Unavailable' });
    expect(fixture.componentInstance.statistics()?.scans).toBe(2);
    expect(fixture.componentInstance.error()).toBe('Request failed (503)');
  });

  it('shows the completed retouch total and all seven step counts', () => {
    const fixture = TestBed.createComponent(StatisticsPage);
    http.expectOne('/api/statistics').flush({
      ...empty,
      scans: 2,
      photos: 4,
      retouched: 3,
      retouched_scratches: 2,
      retouched_color_balance: 1,
      retouched_contrast: 3,
      retouched_colorize: 1,
      retouched_upscale: 2,
      retouched_denoise: 3,
      retouched_faces: 1,
    });
    fixture.detectChanges();
    const section = fixture.nativeElement.querySelector(
      '[aria-labelledby="retouch-title"]',
    ) as HTMLElement;
    expect(section.querySelector('.stat-number')?.textContent).toBe('3');
    expect(section.textContent).toContain('75% of photos');
    const counts = [...section.querySelectorAll('.stat-row')].map((row) => [
      row.querySelector('dt')?.textContent?.trim(),
      row.querySelector('dd')?.textContent?.trim(),
    ]);
    expect(counts).toEqual([
      ['Fill scratches', '2'],
      ['Correct color cast', '1'],
      ['Restore contrast', '3'],
      ['Colorize', '1'],
      ['Upscale', '2'],
      ['Denoise', '3'],
      ['Restore faces', '1'],
    ]);
    expect(section.textContent).toContain('latest completed retouch');
  });
});
