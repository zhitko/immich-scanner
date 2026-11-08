import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { routes } from './app.routes';
import { Photo } from './models';
import { PhotoListPage } from './photo-list';

describe('PhotoListPage', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter(routes), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('combines multiple filters with each upload status and preserves them in photo links', async () => {
    const harness = await RouterTestingHarness.create('/photos');
    http.expectOne('/api/photos?state=open').flush([]);
    harness.detectChanges();
    const checkboxes = () => [
      ...harness.routeNativeElement!.querySelectorAll<HTMLInputElement>('.photo-filters input'),
    ];
    const statuses = () => [
      ...harness.routeNativeElement!.querySelectorAll<HTMLButtonElement>('.filters button'),
    ];
    expect(statuses().map((button) => button.textContent?.trim())).toEqual([
      'Waiting',
      'Uploaded',
      'All',
    ]);
    checkboxes()[0].click();
    await harness.fixture.whenStable();
    http.expectOne('/api/photos?state=open&filters=original').flush([]);
    harness.detectChanges();
    checkboxes()[2].click();
    await harness.fixture.whenStable();
    http.expectOne('/api/photos?state=open&filters=original&filters=has-date').flush([]);
    harness.detectChanges();
    statuses()[1].click();
    await harness.fixture.whenStable();
    http.expectOne('/api/photos?state=uploaded&filters=original&filters=has-date').flush([]);
    harness.detectChanges();
    expect(checkboxes()[0].checked).toBe(true);
    expect(checkboxes()[2].checked).toBe(true);
    statuses()[2].click();
    await harness.fixture.whenStable();
    http.expectOne('/api/photos?state=all&filters=original&filters=has-date').flush([
      {
        id: 'photo-1',
        scan_id: 'scan-1',
        position: 2,
        created_at: '2026-11-08T10:00:00Z',
        width: 100,
        height: 200,
        quarter_turns: 1,
        retouch_ready: false,
        upload_source: 'crop',
        upload_status: 'pending',
        files_deleted: false,
      },
    ]);
    harness.detectChanges();
    expect(harness.routeNativeElement!.querySelector('.card-title')?.getAttribute('href')).toBe(
      '/photos/photo-1?status=all&filter=original&filter=has-date',
    );
    checkboxes()[0].click();
    await harness.fixture.whenStable();
    http.expectOne('/api/photos?state=all&filters=has-date').flush([]);
    harness.detectChanges();
    expect(checkboxes()[0].checked).toBe(false);
    expect(TestBed.inject(Router).url).toBe('/photos?filter=has-date&status=all');
  });

  it('restores filters from the URL and ignores responses for previous filters', async () => {
    const harness = await RouterTestingHarness.create('/photos?filter=retouched');
    const previous = http.expectOne('/api/photos?state=open&filters=retouched');
    await harness.navigateByUrl('/photos?status=all&filter=has-date', PhotoListPage);
    http.expectOne('/api/photos?state=all&filters=has-date').flush([]);
    previous.flush([{ id: 'old-photo' }]);
    harness.detectChanges();
    expect(harness.routeNativeElement!.querySelectorAll('.card')).toHaveLength(0);
    expect(harness.routeNativeElement!.textContent).toContain('No photos match');
  });

  it('uses the current upload version and the correct rotation for thumbnails', async () => {
    const harness = await RouterTestingHarness.create('/photos');
    http.expectOne('/api/photos?state=open').flush([]);
    const page = harness.routeDebugElement!.componentInstance as PhotoListPage;
    const photo = {
      id: 'photo-1',
      scan_id: 'scan-1',
      upload_source: 'retouch',
      retouch_ready: true,
      retouch_version: 'v1',
      quarter_turns: 1,
    } as Photo;
    expect(page.previewUrl(photo)).toContain('/retouch-preview?v=v1');
    expect(page.previewTurns(photo)).toBe(0);
    expect(page.previewTurns({ ...photo, retouch_ready: false })).toBe(1);
  });
});
