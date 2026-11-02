import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ArchiveApi, httpError } from './api';
import { Settings } from './models';

describe('ArchiveApi', () => {
  let api: ArchiveApi;
  let http: HttpTestingController;

  const settings: Settings = {
    immich_base_url: 'http://immich.local:2283',
    immich_api_key: 'key',
    output_format: 'jpeg',
    jpeg_quality: 95,
    default_album_id: '',
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ArchiveApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('lists scans that still need review', () => {
    api.listScans('open').subscribe((scans) => expect(scans).toEqual([]));
    const request = http.expectOne('/api/scans?state=open');
    expect(request.request.method).toBe('GET');
    request.flush([]);
  });

  it('uploads one region and asks for detection', () => {
    api.upload('scan-1', ['region-1']).subscribe((body) => expect(body.job_id).toBe('job-1'));
    const upload = http.expectOne('/api/scans/scan-1/upload');
    expect(upload.request.body).toEqual({ region_ids: ['region-1'] });
    upload.flush({ job_id: 'job-1' });

    api.detect('scan-1').subscribe();
    const detect = http.expectOne('/api/scans/scan-1/detect');
    expect(detect.request.method).toBe('POST');
    detect.flush({ job_id: 'job-2' });
  });

  it('sends geometry and metadata to the region being edited', () => {
    api
      .patchRegion('scan-1', 'region-1', {
        center_x: 1,
        center_y: 2,
        width: 3,
        height: 4,
        angle_deg: 5,
      })
      .subscribe();
    const request = http.expectOne('/api/scans/scan-1/regions/region-1');
    expect(request.request.method).toBe('PATCH');
    expect(request.request.body).toEqual({
      center_x: 1,
      center_y: 2,
      width: 3,
      height: 4,
      angle_deg: 5,
    });
    request.flush({});
  });

  it('tests the Immich connection with the form values', () => {
    api.testConnection(settings).subscribe((result) => expect(result.version).toBe('3.3.5'));
    const request = http.expectOne('/api/settings/test');
    expect(request.request.body).toEqual(settings);
    request.flush({ ok: true, version: '3.3.5', album_count: 2 });
  });

  it('reads a string detail from a failed response', () => {
    const error = new HttpErrorResponse({ status: 422, error: { detail: 'region is too small' } });
    expect(httpError(error)).toBe('region is too small');
    expect(httpError(new HttpErrorResponse({ status: 0, error: null }))).toBe(
      'The server is unreachable.',
    );
  });
});
