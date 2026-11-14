import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';

import { ArchiveApi, httpError } from './api';
import { HelpTip } from './help-tip';
import { BulkRetouchSummary, RetouchChoice } from './models';

@Component({
  selector: 'app-bulk-retouch',
  imports: [RouterLink, HelpTip],
  templateUrl: './bulk-retouch.html',
  styleUrl: './bulk-retouch.css',
})
export class BulkRetouchPage {
  private readonly api = inject(ArchiveApi);
  private readonly destroyRef = inject(DestroyRef);
  private request = 0;

  readonly state = signal<'open' | 'uploaded' | 'all'>('all');
  readonly includeRetouched = signal(false);
  readonly summary = signal<BulkRetouchSummary | null>(null);
  readonly loading = signal(false);
  readonly starting = signal(false);
  readonly error = signal('');
  readonly summaryError = signal('');
  readonly notice = signal('');
  readonly choice = signal<RetouchChoice>({
    upscale: false,
    denoise: false,
    faces: false,
    colorize: false,
    scratches: false,
    color_balance: false,
    contrast: false,
    dust: false,
    deblur: false,
    gentle_denoise: false,
    paper_mesh: false,
    paper_embossed: false,
    light_corners: false,
    output_scale: 4,
  });
  readonly stages: {
    key: Exclude<keyof RetouchChoice, 'output_scale' | 'upscale'>;
    label: string;
  }[] = [
    { key: 'dust', label: 'Remove dust and small spots' },
    { key: 'paper_mesh', label: 'Reduce repeating paper texture' },
    { key: 'paper_embossed', label: 'Reduce embossed paper texture (medium)' },
    { key: 'gentle_denoise', label: 'Gentle denoise (native resolution)' },
    { key: 'deblur', label: 'Deblur mild softness' },
    { key: 'scratches', label: 'Fill scratches' },
    { key: 'light_corners', label: 'Repair light corners' },
    { key: 'color_balance', label: 'Correct color cast' },
    { key: 'contrast', label: 'Restore contrast' },
    { key: 'colorize', label: 'Colorize' },
    { key: 'denoise', label: 'Strong AI denoise' },
    { key: 'faces', label: 'Restore faces' },
  ];
  readonly hasStage = computed(
    () => this.choice().upscale || this.stages.some((stage) => this.choice()[stage.key]),
  );
  readonly canRun = computed(
    () =>
      !this.loading() &&
      !this.starting() &&
      !this.summaryError() &&
      this.hasStage() &&
      (this.summary()?.eligible ?? 0) > 0,
  );

  constructor() {
    this.refresh();
    const timer = window.setInterval(() => {
      if (this.summary()?.busy && !this.loading() && !this.starting()) this.refresh();
    }, 2000);
    this.destroyRef.onDestroy(() => window.clearInterval(timer));
  }

  chooseState(value: string): void {
    if (value !== 'open' && value !== 'uploaded' && value !== 'all') return;
    this.state.set(value);
    this.summary.set(null);
    this.refresh();
  }

  setIncludeRetouched(value: boolean): void {
    this.includeRetouched.set(value);
    this.summary.set(null);
    this.refresh();
  }

  setStage(key: Exclude<keyof RetouchChoice, 'output_scale' | 'upscale'>, enabled: boolean): void {
    this.choice.update((choice) => ({ ...choice, [key]: enabled }));
  }

  setOutputScale(value: string): void {
    this.choice.update((choice) => ({
      ...choice,
      upscale: value !== '1',
      output_scale: value === '2' ? 2 : 4,
    }));
  }

  refresh(): void {
    const request = ++this.request;
    this.loading.set(true);
    this.api
      .bulkRetouchSummary(this.state(), this.includeRetouched())
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
      .bulkRetouch(this.choice(), this.state(), this.includeRetouched())
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => this.starting.set(false)),
      )
      .subscribe({
        next: (summary) => {
          this.notice.set(
            `${summary.queued} photo${summary.queued === 1 ? '' : 's'} queued for retouch. Follow progress and any failures in Jobs.`,
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
