import { Component, DestroyRef, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { ArchiveApi, httpError } from './api';
import { ScanSummary, ScannerStatus } from './models';
import { formatStamp } from './time';

@Component({
  selector: 'app-scan-list',
  imports: [RouterLink],
  templateUrl: './scan-list.html',
})
export class ScanListPage {
  private readonly api = inject(ArchiveApi);
  private readonly route = inject(ActivatedRoute);
  private previousPhase = 'idle';

  readonly mode = signal<'open' | 'uploaded'>('open');
  readonly scans = signal<ScanSummary[] | null>(null);
  readonly scanner = signal<ScannerStatus | null>(null);
  readonly error = signal('');
  readonly busyId = signal('');
  readonly formatStamp = formatStamp;

  constructor() {
    const destroyRef = inject(DestroyRef);
    const timer = window.setInterval(() => {
      if (this.mode() === 'open') {
        this.loadScanner();
      }
    }, 2000);
    destroyRef.onDestroy(() => window.clearInterval(timer));
    this.route.data.subscribe((data) => {
      this.mode.set(data['mode'] === 'uploaded' ? 'uploaded' : 'open');
      this.previousPhase = 'idle';
      this.load();
      if (this.mode() === 'open') {
        this.loadScanner();
      }
    });
  }

  scanning(): boolean {
    return this.scanner()?.phase === 'scanning';
  }

  scan(): void {
    this.error.set('');
    this.api.startScan().subscribe({
      next: () => {
        // A fast capture can finish before this response arrives, so treat the
        // click itself as the start of the scanning phase.
        this.previousPhase = 'scanning';
        this.loadScanner();
      },
      error: (error: unknown) => this.error.set(httpError(error)),
    });
  }

  previewUrl(scan: ScanSummary): string {
    return this.api.scanPreviewUrl(scan.id);
  }

  deleteScan(scan: ScanSummary): void {
    if (!window.confirm('Delete this scan, its regions, and the image files?')) {
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

  private load(quiet = false): void {
    if (!quiet) {
      this.error.set('');
      this.scans.set(null);
    }
    this.api.listScans(this.mode()).subscribe({
      next: (scans) => this.scans.set(scans),
      error: (error: unknown) => {
        this.scans.set([]);
        this.error.set(httpError(error));
      },
    });
  }

  private loadScanner(): void {
    this.api.scannerStatus().subscribe({
      next: (status) => {
        const finished = this.previousPhase === 'scanning' && status.phase === 'idle';
        this.previousPhase = status.phase;
        this.scanner.set(status);
        if (finished) {
          this.load(true);
        }
      },
      error: (error: unknown) => this.error.set(httpError(error)),
    });
  }
}
