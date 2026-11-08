import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { routes } from './app.routes';
import { ScanSummary } from './models';
import { ScanListPage } from './scan-list';

describe('ScanListPage', () => {
  let http: HttpTestingController;

  const waiting: ScanSummary = {
    id: 'waiting',
    created_at: '2026-11-08T10:00:00Z',
    width: 100,
    height: 100,
    dpi: 300,
    device_name: null,
    upload_state: 'pending',
    files_deleted: false,
    detection_error: null,
    detecting: false,
    region_count: 2,
    uploaded_count: 0,
    original_filename: 'bed.png',
  };
  const uploaded: ScanSummary = {
    ...waiting,
    id: 'uploaded',
    upload_state: 'complete',
    uploaded_count: 2,
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter(routes), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  async function open(url = '/scans'): Promise<RouterTestingHarness> {
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl(url, ScanListPage);
    http.expectOne('/api/scanner').flush({ phase: 'idle', scanner_found: true });
    return harness;
  }

  it('defaults to Waiting and switches all three filters through the toggle', async () => {
    const harness = await open();
    http.expectOne('/api/scans?state=open').flush([waiting]);
    harness.detectChanges();
    const buttons = () => [
      ...harness.routeNativeElement!.querySelectorAll<HTMLButtonElement>('.filters button'),
    ];
    expect(buttons().map((button) => button.textContent?.trim())).toEqual([
      'Waiting',
      'Uploaded',
      'All',
    ]);
    expect(buttons()[0].getAttribute('aria-pressed')).toBe('true');

    buttons()[1].click();
    await harness.fixture.whenStable();
    http.expectOne('/api/scans?state=uploaded').flush([uploaded]);
    harness.detectChanges();
    expect(buttons()[1].getAttribute('aria-pressed')).toBe('true');
    expect(harness.routeNativeElement!.textContent).toContain('Free disk space');
    expect(harness.routeNativeElement!.textContent).toContain('Scan bed');

    buttons()[2].click();
    await harness.fixture.whenStable();
    http.expectOne('/api/scans?state=all').flush([waiting, uploaded]);
    harness.detectChanges();
    const cards = [...harness.routeNativeElement!.querySelectorAll('.card')];
    expect(cards).toHaveLength(2);
    expect(cards[0].querySelector('.actions a')?.textContent?.trim()).toBe('Review');
    expect(cards[0].textContent).not.toContain('Free disk space');
    expect(cards[1].querySelector('.actions a')?.textContent?.trim()).toBe('Open');
    expect(cards[1].textContent).toContain('Free disk space');

    buttons()[0].click();
    await harness.fixture.whenStable();
    http.expectOne('/api/scans?state=open').flush([]);
    harness.detectChanges();
    expect(TestBed.inject(Router).url).toBe('/scans');
    expect(harness.routeNativeElement!.textContent).toContain('Nothing waiting');
  });

  it('redirects old Uploaded links to the Uploaded filter', async () => {
    const harness = await open('/uploaded');
    http.expectOne('/api/scans?state=uploaded').flush([]);
    harness.detectChanges();
    expect(TestBed.inject(Router).url).toBe('/scans?status=uploaded');
    expect(harness.routeNativeElement!.textContent).toContain('No finished scans yet');
  });

  it('ignores responses from a previously selected filter', async () => {
    const harness = await open();
    const pending = http.expectOne('/api/scans?state=open');
    await harness.navigateByUrl('/scans?status=all', ScanListPage);
    http.expectOne('/api/scans?state=all').flush([waiting, uploaded]);
    pending.flush([]);
    harness.detectChanges();
    expect(harness.routeNativeElement!.querySelectorAll('.card')).toHaveLength(2);
  });
});
