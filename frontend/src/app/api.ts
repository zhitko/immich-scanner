import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, map } from 'rxjs';

import {
  Album,
  ConnectionTest,
  Job,
  Region,
  RegionGeometry,
  RegionMetadata,
  RetouchChoice,
  RetouchModel,
  RetouchPatch,
  ScanDetail,
  ScanSummary,
  ScannerStatus,
  Settings,
  Statistics,
} from './models';

@Injectable({ providedIn: 'root' })
export class ArchiveApi {
  private readonly http = inject(HttpClient);

  getStatistics(): Observable<Statistics> {
    return this.http.get<Statistics>('/api/statistics');
  }

  listScans(state: 'open' | 'uploaded'): Observable<ScanSummary[]> {
    return this.http.get<ScanSummary[]>('/api/scans', { params: { state } });
  }

  getScan(id: string): Observable<ScanDetail> {
    return this.http.get<ScanDetail>(`/api/scans/${id}`);
  }

  deleteScan(id: string): Observable<void> {
    return this.http
      .delete(`/api/scans/${id}`, { responseType: 'text' })
      .pipe(map(() => undefined));
  }

  deleteFiles(id: string): Observable<ScanDetail> {
    return this.http.delete<ScanDetail>(`/api/scans/${id}/files`);
  }

  detect(id: string): Observable<{ job_id: string }> {
    return this.http.post<{ job_id: string }>(`/api/scans/${id}/detect`, {});
  }

  upload(id: string, regionIds?: string[]): Observable<{ job_id: string }> {
    const body = regionIds ? { region_ids: regionIds } : {};
    return this.http.post<{ job_id: string }>(`/api/scans/${id}/upload`, body);
  }

  createRegion(scanId: string, geometry: RegionGeometry): Observable<Region> {
    return this.http.post<Region>(`/api/scans/${scanId}/regions`, geometry);
  }

  patchRegion(
    scanId: string,
    regionId: string,
    body: RegionGeometry | Partial<RegionMetadata> | RetouchPatch,
  ): Observable<Region> {
    return this.http.patch<Region>(`/api/scans/${scanId}/regions/${regionId}`, body);
  }

  retouch(
    scanId: string,
    regionId: string,
    choice: RetouchChoice,
  ): Observable<{ job_id: string; region: Region }> {
    return this.http.post<{ job_id: string; region: Region }>(
      `/api/scans/${scanId}/regions/${regionId}/retouch`,
      choice,
    );
  }

  retouchModels(): Observable<RetouchModel[]> {
    return this.http.get<RetouchModel[]>('/api/retouch/models');
  }

  fetchRetouchModel(id: string, force = false): Observable<RetouchModel> {
    return this.http.post<RetouchModel>(`/api/retouch/models/${id}`, { accept: true, force });
  }

  rotateRegion(scanId: string, regionId: string, clockwise = true): Observable<Region> {
    return this.http.post<Region>(
      `/api/scans/${scanId}/regions/${regionId}/rotate`,
      {},
      { params: clockwise ? {} : { clockwise: 'false' } },
    );
  }

  deleteRegion(scanId: string, regionId: string): Observable<void> {
    return this.http
      .delete(`/api/scans/${scanId}/regions/${regionId}`, { responseType: 'text' })
      .pipe(map(() => undefined));
  }

  listJobs(status?: string): Observable<Job[]> {
    return this.http.get<Job[]>('/api/jobs', { params: status ? { status } : {} });
  }

  getJob(id: string): Observable<Job> {
    return this.http.get<Job>(`/api/jobs/${id}`);
  }

  getSettings(): Observable<Settings> {
    return this.http.get<Settings>('/api/settings');
  }

  saveSettings(settings: Settings): Observable<Settings> {
    return this.http.put<Settings>('/api/settings', settings);
  }

  testConnection(settings: Settings): Observable<ConnectionTest> {
    return this.http.post<ConnectionTest>('/api/settings/test', settings);
  }

  listAlbums(): Observable<Album[]> {
    return this.http.get<Album[]>('/api/immich/albums');
  }

  scannerStatus(): Observable<ScannerStatus> {
    return this.http.get<ScannerStatus>('/api/scanner');
  }

  startScan(): Observable<{ status: string }> {
    return this.http.post<{ status: string }>('/api/scanner/scan', {});
  }

  scanPreviewUrl(id: string): string {
    return `/api/scans/${id}/preview`;
  }

  regionPreviewUrl(scanId: string, regionId: string, version: string): string {
    return `/api/scans/${scanId}/regions/${regionId}/preview?v=${encodeURIComponent(version)}`;
  }

  retouchPreviewUrl(scanId: string, regionId: string, version: string): string {
    return `/api/scans/${scanId}/regions/${regionId}/retouch-preview?v=${encodeURIComponent(version)}`;
  }
}

export function httpError(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    const detail =
      error.error && typeof error.error === 'object' && 'detail' in error.error
        ? (error.error as { detail: unknown }).detail
        : null;
    if (typeof detail === 'string' && detail) {
      return detail;
    }
    return error.status ? `Request failed (${error.status})` : 'The server is unreachable.';
  }
  return 'Something went wrong.';
}
