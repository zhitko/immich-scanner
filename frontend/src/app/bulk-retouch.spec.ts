import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { BulkRetouchPage } from './bulk-retouch';
import { BulkRetouchSummary } from './models';

describe('BulkRetouchPage', () => {
  let http: HttpTestingController;
  const counts: BulkRetouchSummary = {
    total: 10,
    eligible: 6,
    retouched: 2,
    busy: 1,
    unavailable: 1,
    queued: 0,
  };
  const summaryUrl = '/api/retouch/bulk?state=all&include_retouched=false';

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [BulkRetouchPage],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('shows counts, skips previous results by default, and requires at least one stage', () => {
    const fixture = TestBed.createComponent(BulkRetouchPage);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Counting photos');
    http.expectOne(summaryUrl).flush(counts);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('6 photos eligible');
    expect(fixture.componentInstance.includeRetouched()).toBe(false);
    expect(fixture.componentInstance.canRun()).toBe(false);
    const firstStage = fixture.nativeElement.querySelector('input') as HTMLInputElement;
    firstStage.click();
    fixture.detectChanges();
    expect(fixture.componentInstance.choice().dust).toBe(true);
    expect(fixture.componentInstance.canRun()).toBe(true);
  });

  it('recounts for upload status and the option to reprocess existing results', () => {
    const fixture = TestBed.createComponent(BulkRetouchPage);
    http.expectOne(summaryUrl).flush(counts);
    const page = fixture.componentInstance;
    page.chooseState('uploaded');
    expect(page.summary()).toBeNull();
    http.expectOne('/api/retouch/bulk?state=uploaded&include_retouched=false').flush(counts);
    page.setIncludeRetouched(true);
    http.expectOne('/api/retouch/bulk?state=uploaded&include_retouched=true').flush({
      ...counts,
      eligible: 8,
      retouched: 0,
    });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('8 photos eligible');
    expect(fixture.nativeElement.textContent).toContain('Existing results will be replaced');
  });

  it('sends all stage choices and prevents repeated starts while queueing', () => {
    const fixture = TestBed.createComponent(BulkRetouchPage);
    http.expectOne(summaryUrl).flush(counts);
    const page = fixture.componentInstance;
    page.setStage('contrast', true);
    page.setStage('faces', true);
    page.setOutputScale('2');
    page.run();
    page.run();
    const request = http.expectOne('/api/retouch/bulk');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({
      choice: {
        upscale: true,
        denoise: false,
        faces: true,
        colorize: false,
        scratches: false,
        color_balance: false,
        contrast: true,
        dust: false,
        deblur: false,
        gentle_denoise: false,
        paper_mesh: false,
        paper_embossed: false,
        output_scale: 2,
      },
      state: 'all',
      include_retouched: false,
    });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('fieldset').disabled).toBe(true);
    request.flush({ ...counts, queued: 6 });
    expect(page.canRun()).toBe(false);
    http.expectOne(summaryUrl).flush({ ...counts, eligible: 0, busy: 7 });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('6 photos queued for retouch');
    expect(page.canRun()).toBe(false);
  });

  it('supports upscale alone and clears it for original output size', () => {
    const fixture = TestBed.createComponent(BulkRetouchPage);
    http.expectOne(summaryUrl).flush(counts);
    const page = fixture.componentInstance;
    page.setOutputScale('4');
    expect(page.hasStage()).toBe(true);
    expect(page.choice().denoise).toBe(false);
    page.setOutputScale('1');
    expect(page.hasStage()).toBe(false);
  });

  it('ignores an older count response after the scope changes', () => {
    const fixture = TestBed.createComponent(BulkRetouchPage);
    const original = http.expectOne(summaryUrl);
    fixture.componentInstance.chooseState('open');
    http.expectOne('/api/retouch/bulk?state=open&include_retouched=false').flush({
      ...counts,
      total: 1,
      eligible: 1,
    });
    original.flush(counts);
    expect(fixture.componentInstance.summary()?.eligible).toBe(1);
  });

  it('shows errors, allows retry, and does not permit starting from failed counts', () => {
    const fixture = TestBed.createComponent(BulkRetouchPage);
    http.expectOne(summaryUrl).error(new ProgressEvent('error'));
    const page = fixture.componentInstance;
    page.setStage('dust', true);
    expect(page.canRun()).toBe(false);
    page.refresh();
    http.expectOne(summaryUrl).flush(counts);
    page.run();
    http
      .expectOne('/api/retouch/bulk')
      .flush(
        { detail: 'Missing weights. Download them under Settings first.' },
        { status: 400, statusText: 'Bad Request' },
      );
    http.expectOne(summaryUrl).flush(counts);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role=alert]').textContent).toContain(
      'Missing weights',
    );
    expect(page.canRun()).toBe(true);
    page.refresh();
    http.expectOne(summaryUrl).error(new ProgressEvent('error'));
    expect(page.canRun()).toBe(false);
  });
});
