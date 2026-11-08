import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';

import { MatchingPage } from './matching';
import { Job, MatchingStatus, Photo, PhotoMatch } from './models';

describe('MatchingPage', () => {
  let http: HttpTestingController;
  const photo = {
    id: 'source',
    scan_id: 'source-scan',
    position: 1,
    width: 280,
    height: 200,
    center_x: 140,
    center_y: 100,
    angle_deg: 0,
    quarter_turns: 1,
    taken_at: '1980-05-01T00:00:00Z',
    description: 'Family picnic',
    album_id: null,
    latitude: 0,
    longitude: 0,
    is_favorite: false,
    rating: null,
    visibility: null,
    updated_at: '2026-11-08T10:00:00Z',
  } as Photo;
  const pair: PhotoMatch = {
    source: photo,
    target: {
      ...photo,
      id: 'target',
      scan_id: 'target-scan',
      description: 'Existing caption',
      taken_at: null,
      latitude: null,
      longitude: null,
    },
    fields: ['taken_at', 'location'],
    score: 0.94,
  };
  const finished: MatchingStatus = {
    job: { id: 'job-1', status: 'finished', finished_at: '2026-11-08T10:00:00Z' } as Job,
    progress: {
      minimum_score: 0.82,
      phase: 'finished',
      total: 2,
      indexed: 2,
      processed: 2,
      reused: 0,
      skipped: 0,
      pairs: 1,
    },
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [MatchingPage],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function create(
    status: MatchingStatus = finished,
    items: PhotoMatch[] = [pair],
    total = items.length,
  ) {
    const fixture = TestBed.createComponent(MatchingPage);
    http.expectOne('/api/matching/status').flush(status);
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({ items, total });
    http.expectOne('/api/immich/albums').flush([]);
    fixture.detectChanges();
    return fixture;
  }

  function copyButton(element: HTMLElement, label: string): HTMLButtonElement | undefined {
    return [...element.querySelectorAll<HTMLButtonElement>('button[aria-label]')].find(
      (button) => button.getAttribute('aria-label') === `Copy ${label} to matched photo`,
    );
  }

  it('restores the URL page and keeps pagination and route navigation in sync', async () => {
    TestBed.inject(Router).resetConfig([{ path: 'matching', component: MatchingPage }]);
    const harness = await RouterTestingHarness.create('/matching?page=3&filter=kept');
    http.expectOne('/api/matching/status').flush(finished);
    http.expectOne('/api/matching/pairs?offset=20&limit=10').flush({ items: [pair], total: 41 });
    http.expectOne('/api/immich/albums').flush([]);
    const page = harness.routeDebugElement!.componentInstance as MatchingPage;
    expect(page.offset()).toBe(20);
    const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
    page.page(1);
    http.expectOne('/api/matching/pairs?offset=30&limit=10').flush({ items: [pair], total: 41 });
    await harness.fixture.whenStable();
    expect(TestBed.inject(Router).url).toBe('/matching?page=4&filter=kept');
    expect(scroll).toHaveBeenCalledWith({ top: 0, behavior: 'auto' });
    scroll.mockRestore();
    await harness.navigateByUrl('/matching?page=3&filter=kept');
    http.expectOne('/api/matching/pairs?offset=20&limit=10').flush({ items: [pair], total: 41 });
    expect(page.offset()).toBe(20);
  });

  it('corrects a URL page that no longer has any results', async () => {
    TestBed.inject(Router).resetConfig([{ path: 'matching', component: MatchingPage }]);
    const harness = await RouterTestingHarness.create('/matching?page=8');
    http.expectOne('/api/matching/status').flush(finished);
    http.expectOne('/api/matching/pairs?offset=70&limit=10').flush({ items: [], total: 11 });
    http.expectOne('/api/matching/pairs?offset=10&limit=10').flush({ items: [pair], total: 11 });
    http.expectOne('/api/immich/albums').flush([]);
    await harness.fixture.whenStable();
    expect(TestBed.inject(Router).url).toBe('/matching?page=2');
    expect((harness.routeDebugElement!.componentInstance as MatchingPage).offset()).toBe(10);
  });

  it('shows two photos and copies only the requested missing field with revision checks', () => {
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;
    expect(element.querySelectorAll('.match-photo img')).toHaveLength(2);
    expect(element.querySelectorAll('.crop-ratio.odd')).toHaveLength(2);
    expect(element.textContent).toContain('similarity 94 / 100');
    expect(element.textContent).toContain('Already set: Existing caption');
    expect(copyButton(element, 'Description')).toBeUndefined();
    const button = copyButton(element, 'Date taken')!;
    button.click();
    fixture.detectChanges();
    expect(button.disabled).toBe(true);
    const request = http.expectOne('/api/matching/pairs/source/target/copy');
    expect(request.request.body).toEqual({
      field: 'taken_at',
      source_updated_at: photo.updated_at,
      target_updated_at: photo.updated_at,
    });
    fixture.componentInstance.copy(pair, 'location');
    http.expectNone('/api/matching/pairs/source/target/copy');
    request.flush({ ...pair.target, taken_at: photo.taken_at });
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({
      items: [
        { ...pair, target: { ...pair.target, taken_at: photo.taken_at }, fields: ['location'] },
      ],
      total: 1,
    });
    fixture.detectChanges();
    expect(element.textContent).toContain('Date taken copied. Saved locally');
    expect(copyButton(element, 'Date taken')).toBeUndefined();
    expect(
      element.querySelector('button[aria-label="Replace Date taken on matched photo"]'),
    ).toBeNull();
    expect(copyButton(element, 'Location')).toBeDefined();
  });

  it('replaces an existing value only through the Replace button', () => {
    const fixture = create();
    const element = fixture.nativeElement as HTMLElement;
    const button = element.querySelector<HTMLButtonElement>(
      'button[aria-label="Replace Description on matched photo"]',
    )!;
    expect(button.textContent?.trim()).toBe('Replace');
    expect(element.textContent).toContain('Already set: Existing caption');
    button.click();
    fixture.detectChanges();
    expect(button.disabled).toBe(true);
    expect(button.textContent).toContain('Replacing…');
    const request = http.expectOne('/api/matching/pairs/source/target/copy');
    expect(request.request.body).toEqual({
      field: 'description',
      replace: true,
      source_updated_at: photo.updated_at,
      target_updated_at: pair.target.updated_at,
    });
    request.flush({ ...pair.target, description: photo.description });
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({
      items: [{ ...pair, target: { ...pair.target, description: photo.description } }],
      total: 1,
    });
    fixture.detectChanges();
    expect(element.textContent).toContain('Description replaced. Saved locally');
    expect(element.textContent).toContain('Already set: Family picnic');
    expect(
      element.querySelector('button[aria-label="Replace Description on matched photo"]'),
    ).toBeNull();
    expect(fixture.componentInstance.saving()).toBe('');
  });

  it('refreshes suggestions after a stale replacement conflict', () => {
    const fixture = create();
    fixture.componentInstance.copy(pair, 'description', true);
    http
      .expectOne('/api/matching/pairs/source/target/copy')
      .flush(
        { detail: 'This suggestion changed. Refresh before copying metadata.' },
        { status: 409, statusText: 'Conflict' },
      );
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({ items: [pair], total: 1 });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role=alert]').textContent).toContain(
      'suggestion changed',
    );
    expect(fixture.nativeElement.textContent).toContain('Already set: Existing caption');
    expect(fixture.componentInstance.saving()).toBe('');
    expect(fixture.componentInstance.notice()).toBe('');
  });

  it('keeps existing values and refreshes suggestions after a stale copy conflict', () => {
    const fixture = create();
    fixture.componentInstance.copy(pair, 'taken_at');
    http
      .expectOne('/api/matching/pairs/source/target/copy')
      .flush(
        { detail: 'This suggestion changed. Refresh before copying metadata.' },
        { status: 409, statusText: 'Conflict' },
      );
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({ items: [], total: 0 });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role=alert]').textContent).toContain(
      'suggestion changed',
    );
    expect(fixture.componentInstance.saving()).toBe('');
    expect(fixture.componentInstance.notice()).toBe('');
  });

  it('runs once, follows background progress and fetches finished suggestions', () => {
    const fixture = create({ job: null, progress: null }, []);
    const page = fixture.componentInstance;
    expect(fixture.nativeElement.textContent).toContain('Run matching to find suggestions');
    page.minimumScore.set(0.7);
    page.run();
    page.run();
    const request = http.expectOne('/api/matching/run');
    expect(request.request.body).toEqual({ minimum_score: 0.7 });
    request.flush({ job_id: 'job-1' });
    http
      .expectOne('/api/matching/status')
      .flush({ ...finished, job: { ...finished.job, status: 'queued' } });
    fixture.detectChanges();
    expect(page.busy()).toBe(true);
    expect(fixture.nativeElement.textContent).toContain('Matching queued');
    page.refreshStatus();
    http.expectOne('/api/matching/status').flush(finished);
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({ items: [pair], total: 1 });
    fixture.detectChanges();
    expect(page.busy()).toBe(false);
    expect(fixture.nativeElement.querySelectorAll('.match-card')).toHaveLength(1);
  });

  it('resumes an existing run and displays skipped photos and failed jobs', () => {
    const fixture = create(
      {
        ...finished,
        job: { ...finished.job!, status: 'running' },
        progress: { ...finished.progress!, phase: 'indexing', processed: 1 },
      },
      [],
    );
    expect(fixture.componentInstance.busy()).toBe(true);
    expect(fixture.nativeElement.querySelector('progress')?.value).toBe(1);
    fixture.componentInstance.refreshStatus();
    http.expectOne('/api/matching/status').flush({
      ...finished,
      job: { ...finished.job, status: 'failed', error: 'Disk full' },
      progress: { ...finished.progress, skipped: 1, warnings: ['Photo 123: file removed'] },
    });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Matching failed: Disk full');
    expect(fixture.nativeElement.textContent).toContain('Photo 123: file removed');
    expect(fixture.componentInstance.busy()).toBe(false);
  });

  it('skips a card without copying values and returns to the last available page', () => {
    const scroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
    const fixture = create(finished, [pair], 11);
    const page = fixture.componentInstance;
    page.page(1);
    expect(scroll).not.toHaveBeenCalled();
    http.expectOne('/api/matching/pairs?offset=10&limit=10').flush({ items: [pair], total: 11 });
    expect(scroll).toHaveBeenCalledWith({ top: 0, behavior: 'auto' });
    scroll.mockRestore();
    fixture.detectChanges();
    const button = fixture.nativeElement.querySelector(
      '.match-card-actions button',
    ) as HTMLButtonElement;
    expect(button.textContent?.trim()).toBe('Skip');
    button.click();
    fixture.detectChanges();
    expect(button.disabled).toBe(true);
    expect(button.textContent).toContain('Skipping…');
    http.expectNone('/api/matching/pairs/source/target/copy');
    http
      .expectOne('/api/matching/pairs/source/target/dismiss')
      .flush(null, { status: 204, statusText: 'No Content' });
    http.expectOne('/api/matching/pairs?offset=10&limit=10').flush({ items: [], total: 10 });
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({ items: [pair], total: 10 });
    expect(page.offset()).toBe(0);
    expect(page.notice()).toContain('Suggestion skipped. No values were copied.');
  });

  it('allows matching offline and can retry after a network error', () => {
    const fixture = TestBed.createComponent(MatchingPage);
    http.expectOne('/api/matching/status').error(new ProgressEvent('error'));
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({ items: [], total: 0 });
    http.expectOne('/api/immich/albums').error(new ProgressEvent('error'));
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('unreachable');
    fixture.componentInstance.refreshStatus();
    http.expectOne('/api/matching/status').flush(finished);
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({ items: [], total: 0 });
    fixture.componentInstance.run();
    http.expectOne('/api/matching/run').error(new ProgressEvent('error'));
    expect(fixture.componentInstance.starting()).toBe(false);
    expect(fixture.componentInstance.error()).toContain('unreachable');
    expect(fixture.componentInstance.value({ ...photo, album_id: 'album-123' }, 'album_id')).toBe(
      'album-123',
    );
  });

  it('ignores an older status request after starting a new matching run', () => {
    const fixture = create();
    const page = fixture.componentInstance;
    page.refreshStatus();
    const older = http.expectOne('/api/matching/status');
    page.run();
    http.expectOne('/api/matching/run').flush({ job_id: 'job-2' });
    http.expectOne('/api/matching/status').flush({
      ...finished,
      job: { ...finished.job, id: 'job-2', status: 'running' },
    });
    older.flush(finished);
    expect(page.status()?.job?.id).toBe('job-2');
    expect(page.busy()).toBe(true);
    expect(page.starting()).toBe(false);
    page.refreshStatus();
    http.expectOne('/api/matching/status').flush({
      ...finished,
      job: { ...finished.job, id: 'job-2' },
    });
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({ items: [pair], total: 1 });
    expect(page.busy()).toBe(false);
  });

  it('loads initial suggestions after learning a job has finished', () => {
    const fixture = TestBed.createComponent(MatchingPage);
    http.expectNone('/api/matching/pairs?offset=0&limit=10');
    http.expectOne('/api/matching/status').flush(finished);
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({ items: [pair], total: 1 });
    http.expectOne('/api/immich/albums').flush([]);
    expect(fixture.componentInstance.results()?.total).toBe(1);
  });

  it('ignores stale pair responses and clears pair errors after a successful retry', () => {
    const fixture = create();
    const page = fixture.componentInstance;
    page.loadPairs();
    const older = http.expectOne('/api/matching/pairs?offset=0&limit=10');
    page.loadPairs();
    http.expectOne('/api/matching/pairs?offset=0&limit=10').error(new ProgressEvent('error'));
    expect(page.pairsError()).toContain('unreachable');
    page.loadPairs();
    http.expectOne('/api/matching/pairs?offset=0&limit=10').flush({ items: [], total: 0 });
    older.flush({ items: [pair], total: 1 });
    expect(page.pairsError()).toBe('');
    expect(page.results()?.total).toBe(0);
    expect(page.loading()).toBe(false);
  });
});
