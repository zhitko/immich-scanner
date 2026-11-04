import { Component, DestroyRef, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ArchiveApi, httpError } from './api';
import { Job } from './models';
import { formatStamp } from './time';

@Component({
  selector: 'app-jobs',
  imports: [RouterLink],
  templateUrl: './jobs.html',
})
export class JobsPage {
  private readonly api = inject(ArchiveApi);

  readonly statuses = ['', 'queued', 'running', 'finished', 'failed'] as const;
  readonly status = signal('');
  readonly jobs = signal<Job[] | null>(null);
  readonly error = signal('');
  readonly formatStamp = formatStamp;

  constructor() {
    const destroyRef = inject(DestroyRef);
    const timer = window.setInterval(() => this.load(), 2000);
    destroyRef.onDestroy(() => window.clearInterval(timer));
    this.load();
  }

  choose(status: string): void {
    this.status.set(status);
    this.jobs.set(null);
    this.load();
  }

  label(status: string): string {
    return status || 'all';
  }

  private load(): void {
    this.api.listJobs(this.status() || undefined).subscribe({
      next: (jobs) => {
        this.jobs.set(jobs);
        this.error.set('');
      },
      error: (error: unknown) => this.error.set(httpError(error)),
    });
  }
}
