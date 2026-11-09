import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';

import { ArchiveApi, httpError } from './api';
import { BulkUploadSummary } from './models';

@Component({
  selector: 'app-bulk-upload',
  imports: [RouterLink],
  templateUrl: './bulk-upload.html',
  styleUrl: './bulk-retouch.css',
})
export class BulkUploadPage {
  private readonly api = inject(ArchiveApi);
  private readonly destroyRef = inject(DestroyRef);
  private request = 0;

  readonly includeUploaded = signal(false);
  readonly summary = signal<BulkUploadSummary | null>(null);
  readonly loading = signal(false);
  readonly starting = signal(false);
  readonly error = signal('');
  readonly summaryError = signal('');
  readonly notice = signal('');
  readonly canRun = computed(
    () =>
      !this.loading() &&
      !this.starting() &&
      !this.summaryError() &&
      (this.summary()?.eligible ?? 0) > 0,
  );

  constructor() {
    this.refresh();
    const timer = window.setInterval(() => {
      if (this.summary()?.busy && !this.loading() && !this.starting()) this.refresh();
    }, 2000);
    this.destroyRef.onDestroy(() => window.clearInterval(timer));
  }

  setIncludeUploaded(value: boolean): void {
    this.includeUploaded.set(value);
    this.summary.set(null);
    this.refresh();
  }

  refresh(): void {
    const request = ++this.request;
    this.loading.set(true);
    this.api
      .bulkUploadSummary(this.includeUploaded())
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          if (request === this.request) this.loading.set(false);
        }),
      )
      .subscribe({
        next: (summary) => {
          if (request !== this.request) return;
          this.summary.set(summary);
          this.summaryError.set('');
        },
        error: (error: unknown) => {
          if (request === this.request) this.summaryError.set(httpError(error));
        },
      });
  }

  run(): void {
    if (!this.canRun()) return;
    this.starting.set(true);
    this.error.set('');
    this.notice.set('');
    this.api
      .bulkUpload(this.includeUploaded())
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => this.starting.set(false)),
      )
      .subscribe({
        next: (summary) => {
          this.notice.set(
            `${summary.queued} photo${summary.queued === 1 ? '' : 's'} queued for upload. Follow progress and any failures in Jobs.`,
          );
          this.refresh();
        },
        error: (error: unknown) => {
          this.error.set(httpError(error));
          this.refresh();
        },
      });
  }
}
