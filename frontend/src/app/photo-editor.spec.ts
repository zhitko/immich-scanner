import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { vi } from 'vitest';

import { routes } from './app.routes';
import { EditorPage } from './editor';
import { Region, ScanDetail } from './models';

describe('Photo editor', () => {
  let http: HttpTestingController;
  const photo = {
    id: 'photo-2',
    position: 2,
    center_x: 50,
    center_y: 60,
    width: 80,
    height: 100,
    angle_deg: 0,
    quarter_turns: 0,
    taken_at: null,
    description: '',
    album_id: null,
    latitude: null,
    longitude: null,
    is_favorite: false,
    rating: null,
    visibility: null,
    upload_status: 'pending',
    upload_source: 'crop',
    needs_upload: true,
    retouch_ready: false,
    retouch_status: 'none',
    updated_at: '2026-11-08T10:00:00Z',
  } as Region;
  const detail = {
    id: 'scan-1',
    created_at: '2026-11-08T10:00:00Z',
    width: 1000,
    height: 1000,
    dpi: 300,
    files_deleted: false,
    detecting: false,
    regions: [photo],
    region_count: 3,
    uploaded_count: 0,
    upload_state: 'pending',
  } as ScanDetail;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideRouter(routes), provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    vi.restoreAllMocks();
  });

  async function open(scanDetail = detail) {
    const harness = await RouterTestingHarness.create('/photos/photo-2?status=all&filter=original');
    http.expectOne('/api/photos/photo-2?apply_defaults=true').flush(scanDetail);
    http
      .expectOne('/api/photos?state=all&filters=original')
      .flush([{ id: 'photo-1' }, { id: 'photo-2' }, { id: 'photo-3' }]);
    http.expectOne('/api/immich/albums').flush([]);
    http.expectOne('/api/settings').flush({ immich_base_url: '' });
    http.expectOne('/api/retouch/models').flush([]);
    harness.detectChanges();
    return harness;
  }

  it('shows one photo with only Retouch and Details and uploads only that photo', async () => {
    const harness = await open();
    const element = harness.routeNativeElement!;
    expect(element.querySelector('canvas')).toBeNull();
    expect(element.querySelectorAll('.photo-stage-frame img')).toHaveLength(1);
    expect(
      [...element.querySelectorAll('summary')].map((summary) => summary.textContent?.trim()),
    ).toEqual(['Retouch', 'Details']);
    expect(element.textContent).not.toContain('Detect again');
    expect(element.textContent).not.toContain('Delete scan');
    expect(element.querySelector('.photo-stage-frame img')?.getAttribute('src')).toContain(
      '/api/scans/scan-1/regions/photo-2/preview',
    );
    (element.querySelector('.toolbar .primary') as HTMLButtonElement).click();
    const upload = http.expectOne('/api/scans/scan-1/upload');
    expect(upload.request.body).toEqual({ region_ids: ['photo-2'] });
    upload.flush({ job_id: 'upload-1' });
  });

  it('enables reupload for an already uploaded photo without local changes', async () => {
    const harness = await open({
      ...detail,
      uploaded_count: 1,
      regions: [{ ...photo, upload_status: 'uploaded', needs_upload: false, immich_asset_id: 'asset-2' }],
    });
    const button = harness.routeNativeElement!.querySelector('.toolbar .primary') as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(button.textContent).toContain('Reupload to Immich');
    button.click();
    const upload = http.expectOne('/api/scans/scan-1/upload');
    expect(upload.request.body).toEqual({ region_ids: ['photo-2'] });
    upload.flush({ job_id: 'reupload-1' });
  });

  it('saves metadata for the selected photo before navigating with the same filters', async () => {
    const harness = await open();
    const editor = harness.routeDebugElement!.componentInstance as EditorPage;
    editor.updateDraft('description', 'Family portrait');
    editor.navigateScan(editor.nextScanId());
    const save = http.expectOne('/api/scans/scan-1/regions/photo-2');
    expect(save.request.body.description).toBe('Family portrait');
    save.flush({ ...photo, description: 'Family portrait' });
    await harness.fixture.whenStable();
    http
      .expectOne('/api/photos/photo-3?apply_defaults=true')
      .flush({ ...detail, regions: [{ ...photo, id: 'photo-3' }] });
    harness.detectChanges();
    expect(TestBed.inject(Router).url).toBe('/photos/photo-3?status=all&filter=original');
    expect(editor.selectedId()).toBe('photo-3');
  });

  it('removes only the selected photo and returns to the filtered photo list', async () => {
    const harness = await open();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const editor = harness.routeDebugElement!.componentInstance as EditorPage;
    editor.removeRegion();
    http
      .expectOne('/api/scans/scan-1/regions/photo-2')
      .flush(null, { status: 204, statusText: 'No Content' });
    await harness.fixture.whenStable();
    http.expectOne('/api/photos?state=all&filters=original').flush([]);
    expect(TestBed.inject(Router).url).toBe('/photos?status=all&filter=original');
  });

  it('automatically selects and shows the retouched photo when the job finishes', async () => {
    const timer = vi.spyOn(window, 'setInterval').mockReturnValue(0);
    const harness = await open();
    const editor = harness.routeDebugElement!.componentInstance as EditorPage;
    editor.setRetouch('retouch_contrast', true);
    const settings = http.expectOne('/api/scans/scan-1/regions/photo-2');
    expect(settings.request.body).toEqual({ retouch_contrast: true });
    settings.flush({ ...photo, retouch_contrast: true });
    editor.runRetouch();
    const retouch = http.expectOne('/api/scans/scan-1/regions/photo-2/retouch');
    expect(retouch.request.body.contrast).toBe(true);
    retouch.flush({
      job_id: 'retouch-1',
      region: {
        ...photo,
        retouch_contrast: true,
        retouch_status: 'queued',
      },
    });
    expect(editor.selected()?.upload_source).toBe('crop');
    const poll = timer.mock.calls.find(([, delay]) => delay === 1500)![0] as () => void;
    poll();
    http.expectOne('/api/jobs/retouch-1').flush({ status: 'finished', error: null });
    http.expectOne('/api/photos/photo-2').flush({
      ...detail,
      regions: [
        {
          ...photo,
          retouch_contrast: true,
          upload_source: 'retouch',
          retouch_ready: true,
          retouch_status: 'ready',
          retouch_version: 'v1',
        },
      ],
    });
    harness.detectChanges();
    expect(editor.selected()?.upload_source).toBe('retouch');
    expect(
      harness.routeNativeElement!.querySelector('.version-choice button[aria-pressed="true"]')
        ?.textContent,
    ).toContain('Retouched');
    const images = harness.routeNativeElement!.querySelectorAll(
      '.photo-stage-frame img:not(.hidden)',
    );
    expect(images).toHaveLength(1);
    expect(images[0].getAttribute('src')).toContain(
      '/api/scans/scan-1/regions/photo-2/retouch-preview?v=v1',
    );
  });

  it('preserves a processing edit when background detection refreshes an untouched photo', async () => {
    const timer = vi.spyOn(window, 'setInterval').mockReturnValue(0);
    const harness = await open();
    const editor = harness.routeDebugElement!.componentInstance as EditorPage;
    editor.setRetouch('retouch_denoise', false);
    http.expectOne('/api/scans/scan-1/regions/photo-2').flush({
      ...photo,
      retouch_denoise: false,
    });
    editor.scan.update((scan) => ({ ...scan!, detecting: true }));
    const poll = timer.mock.calls.find(([, delay]) => delay === 1500)![0] as () => void;
    poll();
    http.expectOne('/api/photos/photo-2').flush({
      ...detail,
      regions: [{ ...photo, retouch_denoise: false }],
    });
    expect(editor.selected()?.retouch_denoise).toBe(false);
  });
});
