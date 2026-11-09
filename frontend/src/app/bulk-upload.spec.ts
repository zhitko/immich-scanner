import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { BulkUploadPage } from './bulk-upload';
import { BulkUploadSummary } from './models';

describe('BulkUploadPage', () => {
  let http: HttpTestingController;
  const counts: BulkUploadSummary = {
    total: 10,
    eligible: 5,
    uploaded: 2,
    busy: 1,
    unavailable: 1,
    retouch_not_ready: 1,
    queued: 0,
  };
  const summaryUrl = '/api/uploads/bulk?include_uploaded=false';

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [BulkUploadPage],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('shows eligibility and skip reasons, excluding uploaded photos by default', () => {
    const fixture = TestBed.createComponent(BulkUploadPage);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Counting photos');
    expect(fixture.componentInstance.canRun()).toBe(false);
    http.expectOne(summaryUrl).flush(counts);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('5 photos eligible');
    expect(fixture.nativeElement.textContent).toContain('Retouch version not ready');
    expect(fixture.componentInstance.includeUploaded()).toBe(false);
    expect(fixture.componentInstance.canRun()).toBe(true);
  });

  it('recounts when including uploaded photos and ignores older responses', () => {
    const fixture = TestBed.createComponent(BulkUploadPage);
    const original = http.expectOne(summaryUrl);
    fixture.componentInstance.setIncludeUploaded(true);
    http.expectOne('/api/uploads/bulk?include_uploaded=true').flush({ ...counts, eligible: 7 });
    original.flush(counts);
    fixture.detectChanges();
    expect(fixture.componentInstance.summary()?.eligible).toBe(7);
    expect(fixture.nativeElement.textContent).toContain('previous assets are not deleted');
  });

  it('queues once and refreshes counts after starting', () => {
    const fixture = TestBed.createComponent(BulkUploadPage);
    http.expectOne(summaryUrl).flush(counts);
    const page = fixture.componentInstance;
    page.run();
    page.run();
    const request = http.expectOne('/api/uploads/bulk');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ include_uploaded: false });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('fieldset').disabled).toBe(true);
    request.flush({ ...counts, queued: 5 });
    expect(page.canRun()).toBe(false);
    http.expectOne(summaryUrl).flush({ ...counts, eligible: 0, busy: 6 });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('5 photos queued for upload');
    expect(page.canRun()).toBe(false);
  });

  it('blocks failed counts and displays start failures with retry', () => {
    const fixture = TestBed.createComponent(BulkUploadPage);
    const page = fixture.componentInstance;
    http.expectOne(summaryUrl).error(new ProgressEvent('error'));
    expect(page.canRun()).toBe(false);
    page.refresh();
    http.expectOne(summaryUrl).flush(counts);
    page.run();
    http
      .expectOne('/api/uploads/bulk')
      .flush({ detail: 'Could not queue uploads' }, { status: 500, statusText: 'Server Error' });
    http.expectOne(summaryUrl).flush(counts);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role=alert]').textContent).toContain(
      'Could not queue uploads',
    );
    expect(page.canRun()).toBe(true);
  });
});
