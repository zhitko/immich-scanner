import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { JobsPage } from './jobs';

describe('JobsPage', () => {
  let http: HttpTestingController;
  const counts = { queued: 3, running: 1, finished: 205, failed: 2 };

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [JobsPage],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('shows overall counts independently of the filtered job list', () => {
    const fixture = TestBed.createComponent(JobsPage);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.job-statistics').textContent).toContain('—');
    http.expectOne('/api/jobs').flush([]);
    http.expectOne('/api/jobs/statistics').flush(counts);
    fixture.detectChanges();
    expect(
      Array.from(fixture.nativeElement.querySelectorAll('dd'), (node) =>
        (node as HTMLElement).textContent?.trim(),
      ),
    ).toEqual(['3', '1', '205', '2']);

    fixture.componentInstance.choose('failed');
    http.expectOne('/api/jobs?status=failed').flush([]);
    http.expectOne('/api/jobs/statistics').flush({ ...counts, failed: 4 });
    fixture.detectChanges();
    expect(fixture.componentInstance.statistics()).toEqual({ ...counts, failed: 4 });
    expect(fixture.nativeElement.textContent).toContain('No jobs in this view.');
  });

  it('shows zero counts for an empty queue', () => {
    const fixture = TestBed.createComponent(JobsPage);
    http.expectOne('/api/jobs').flush([]);
    http.expectOne('/api/jobs/statistics').flush({ queued: 0, running: 0, finished: 0, failed: 0 });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('dd').length).toBe(4);
    expect(fixture.nativeElement.querySelector('dd').textContent.trim()).toBe('0');
  });

  it('ignores stale responses after changing filters', () => {
    const fixture = TestBed.createComponent(JobsPage);
    const originalJobs = http.expectOne('/api/jobs');
    const originalStatistics = http.expectOne('/api/jobs/statistics');
    fixture.componentInstance.choose('running');
    http.expectOne('/api/jobs?status=running').flush([]);
    http.expectOne('/api/jobs/statistics').flush(counts);
    originalJobs.flush([]);
    originalStatistics.flush({ ...counts, running: 0 });
    expect(fixture.componentInstance.statistics()).toEqual(counts);
  });

  it('reports failures without replacing counts with misleading zeros', () => {
    const fixture = TestBed.createComponent(JobsPage);
    http.expectOne('/api/jobs').flush([]);
    http.expectOne('/api/jobs/statistics').error(new ProgressEvent('error'));
    fixture.detectChanges();
    expect(fixture.componentInstance.statistics()).toBeNull();
    expect(fixture.nativeElement.querySelector('[role=alert]').textContent).toContain(
      'unreachable',
    );
  });
});
