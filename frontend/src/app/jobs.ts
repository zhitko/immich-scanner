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

  typeLabel(type: string): string {
    if (type === 'match') {
      return 'Match photos';
    }
    if (type === 'detect') {
      return 'Find photos';
    }
    if (type === 'upload') {
      return 'Upload';
    }
    if (type === 'retouch') {
      return 'Retouch';
    }
    return type;
  }

  duration(job: Job): string {
    if (!job.started_at) {
      return '';
    }
    const end = job.finished_at ? new Date(job.finished_at) : new Date();
    const seconds = Math.max(0, (end.getTime() - new Date(job.started_at).getTime()) / 1000);
    return seconds < 60 ? `${seconds.toFixed(1)} s` : `${Math.round(seconds / 60)} min`;
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
