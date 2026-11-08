import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { ArchiveApi, httpError } from './api';
import { ScanSummary, ScannerStatus } from './models';
import { formatStamp } from './time';

const AUTO_OPEN_KEY = 'immich-scanner.auto-open';

@Component({
  selector: 'app-scan-list',
  imports: [RouterLink],
  templateUrl: './scan-list.html',
})
export class ScanListPage {
  private readonly api = inject(ArchiveApi);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private previousPhase = 'idle';
  private ticks = 0;
  private loadId = 0;

  readonly statuses = [
    { value: 'open', label: 'Waiting' },
    { value: 'uploaded', label: 'Uploaded' },
    { value: 'all', label: 'All' },
  ] as const;
  readonly mode = signal<'open' | 'uploaded' | 'all'>('open');
  readonly scans = signal<ScanSummary[] | null>(null);
  readonly scanner = signal<ScannerStatus | null>(null);
  readonly error = signal('');
  readonly busyId = signal('');
  readonly starting = signal(false);
  readonly now = signal(Date.now());
  readonly autoOpen = signal(localStorage.getItem(AUTO_OPEN_KEY) === '1');
  readonly formatStamp = formatStamp;

  readonly scanning = computed(() => this.starting() || this.scanner()?.phase !== 'idle');
  readonly elapsed = computed(() => {
    const started = this.scanner()?.phase_started_at;
    if (!started || this.scanner()?.phase === 'idle') {
      return '';
    }
    const seconds = Math.max(0, Math.round((this.now() - new Date(started).getTime()) / 1000));
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  });
  readonly lampState = computed(() => {
    const status = this.scanner();
    if (!status) {
      return 'unknown';
    }
    if (status.phase !== 'idle') {
      return 'busy';
    }
    return status.scanner_found ? 'ok' : 'bad';
  });

  constructor() {
    const destroyRef = inject(DestroyRef);
    const timer = window.setInterval(() => this.tick(), 1000);
    destroyRef.onDestroy(() => window.clearInterval(timer));
    this.route.queryParamMap.pipe(takeUntilDestroyed(destroyRef)).subscribe((params) => {
      const status = params.get('status');
      this.mode.set(status === 'uploaded' || status === 'all' ? status : 'open');
      this.load();
    });
    this.loadScanner();
  }

  choose(mode: 'open' | 'uploaded' | 'all'): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { status: mode === 'open' ? null : mode },
      queryParamsHandling: 'merge',
    });
  }

  toggleAutoOpen(value: boolean): void {
    this.autoOpen.set(value);
    localStorage.setItem(AUTO_OPEN_KEY, value ? '1' : '0');
  }

  scan(): void {
    this.error.set('');
    this.starting.set(true);
    this.api.startScan().subscribe({
      next: () => {
        // A fast capture can finish before this response arrives, so treat the
        // click itself as the start of the scanning phase.
        this.previousPhase = 'scanning';
        this.loadScanner();
      },
      error: (error: unknown) => {
        this.starting.set(false);
        this.error.set(httpError(error));
      },
    });
  }

  previewUrl(scan: ScanSummary): string {
    return this.api.scanPreviewUrl(scan.id);
  }

  progress(scan: ScanSummary): string {
    if (scan.detecting) {
      return 'Finding photos…';
    }
    if (scan.region_count === 0) {
      return 'No photos found';
    }
    const photos = `${scan.region_count} ${scan.region_count === 1 ? 'photo' : 'photos'}`;
    if (scan.uploaded_count === 0) {
      return `${photos} to review`;
    }
    if (scan.uploaded_count === scan.region_count) {
      return `${photos} uploaded`;
    }
    return `${scan.uploaded_count} of ${photos} uploaded`;
  }

  deleteScan(scan: ScanSummary): void {
    if (!window.confirm('Delete this scan, its photos, and the image files?')) {
      return;
    }
    this.busyId.set(scan.id);
    this.api.deleteScan(scan.id).subscribe({
      next: () => {
        this.scans.update((items) => items?.filter((item) => item.id !== scan.id) ?? []);
        this.busyId.set('');
      },
      error: (error: unknown) => {
        this.error.set(httpError(error));
        this.busyId.set('');
      },
    });
  }

  deleteFiles(scan: ScanSummary): void {
    if (!window.confirm('Delete the original scan file and keep the upload history?')) {
      return;
    }
    this.busyId.set(scan.id);
    this.api.deleteFiles(scan.id).subscribe({
      next: (updated) => {
        this.scans.update(
          (items) => items?.map((item) => (item.id === updated.id ? updated : item)) ?? [],
        );
        this.busyId.set('');
      },
      error: (error: unknown) => {
        this.error.set(httpError(error));
        this.busyId.set('');
      },
    });
  }

  private tick(): void {
    this.now.set(Date.now());
    this.ticks += 1;
    if (this.scanning() || this.ticks % 3 === 0) {
      this.loadScanner();
    }
    if (this.ticks % 2 === 0 && this.scans()?.some((scan) => scan.detecting)) {
      this.load(true);
    }
  }

  private load(quiet = false): void {
    const loadId = ++this.loadId;
    if (!quiet) {
      this.error.set('');
      this.scans.set(null);
    }
    this.api.listScans(this.mode()).subscribe({
      next: (scans) => {
        if (loadId === this.loadId) {
          this.scans.set(scans);
        }
      },
      error: (error: unknown) => {
        if (!quiet && loadId === this.loadId) {
          this.scans.set([]);
          this.error.set(httpError(error));
        }
      },
    });
  }

  private loadScanner(): void {
    this.api.scannerStatus().subscribe({
      next: (status) => {
        const finished = this.previousPhase !== 'idle' && status.phase === 'idle';
        this.previousPhase = status.phase;
        this.scanner.set(status);
        if (status.phase !== 'idle' || finished) {
          this.starting.set(false);
        }
        if (!finished) {
          return;
        }
        if (status.last_scan_ok && status.last_scan_id && this.autoOpen()) {
          void this.router.navigate(['/scans', status.last_scan_id]);
          return;
        }
        this.load(true);
      },
      error: (error: unknown) => {
        this.starting.set(false);
        this.error.set(httpError(error));
      },
    });
  }
}
