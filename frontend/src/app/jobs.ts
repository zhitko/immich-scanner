import { DecimalPipe } from '@angular/common';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { ArchiveApi, httpError } from './api';
import { Job, JobStatistics } from './models';
import { formatStamp } from './time';

@Component({
  selector: 'app-jobs',
  imports: [DecimalPipe, RouterLink],
  templateUrl: './jobs.html',
  styleUrl: './jobs.css',
})
export class JobsPage {
  private readonly api = inject(ArchiveApi);
  private requestId = 0;

  readonly summaryStatuses = ['queued', 'running', 'finished', 'failed'] as const;
  readonly statuses = ['', ...this.summaryStatuses] as const;
  readonly statistics = signal<JobStatistics | null>(null);
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
    const requestId = ++this.requestId;
    forkJoin({
      jobs: this.api.listJobs(this.status() || undefined),
      statistics: this.api.jobStatistics(),
    }).subscribe({
      next: ({ jobs, statistics }) => {
        if (requestId !== this.requestId) return;
        this.jobs.set(jobs);
        this.statistics.set(statistics);
        this.error.set('');
      },
      error: (error: unknown) => {
        if (requestId === this.requestId) this.error.set(httpError(error));
      },
    });
  }
}
