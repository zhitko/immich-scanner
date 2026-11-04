import { Component, inject, signal } from '@angular/core';

import { ArchiveApi, httpError } from './api';
import { Album, ScannerDevice, Settings } from './models';

@Component({
  selector: 'app-settings-page',
  templateUrl: './settings-page.html',
})
export class SettingsPage {
  private readonly api = inject(ArchiveApi);

  readonly settings = signal<Settings | null>(null);
  readonly albums = signal<Album[]>([]);
  readonly devices = signal<ScannerDevice[]>([]);
  readonly scannerFound = signal<boolean | null>(null);
  readonly scannerMessage = signal('');
  readonly error = signal('');
  readonly notice = signal('');
  readonly connection = signal<{ ok: boolean; message: string } | null>(null);
  readonly busy = signal(false);
  readonly dirty = signal(false);
  readonly revealKey = signal(false);
  readonly resolutions = [150, 300, 600, 1200];

  constructor() {
    this.api.getSettings().subscribe({
      next: (settings) => {
        this.settings.set(settings);
        this.loadAlbums();
      },
      error: (error: unknown) => this.error.set(httpError(error)),
    });
    this.api.scannerStatus().subscribe({
      next: (status) => {
        this.devices.set(status.devices);
        this.scannerFound.set(status.scanner_found);
        this.scannerMessage.set(status.scanner_message);
      },
      error: () => this.scannerMessage.set(''),
    });
  }

  update<K extends keyof Settings>(key: K, value: Settings[K]): void {
    const current = this.settings();
    if (!current) {
      return;
    }
    this.settings.set({ ...current, [key]: value });
    this.dirty.set(true);
    this.notice.set('');
    if (key === 'immich_base_url' || key === 'immich_api_key') {
      this.connection.set(null);
    }
  }

  knownAlbum(id: string): boolean {
    return this.albums().some((album) => album.id === id);
  }

  knownDevice(name: string): boolean {
    return this.devices().some((device) => device.name === name);
  }

  setResolution(value: string): void {
    const dpi = Number(value);
    if (Number.isFinite(dpi) && dpi > 0) {
      this.update('resolution_dpi', dpi);
    }
  }

  setMillimetres(key: 'width_mm' | 'height_mm', value: string): void {
    if (!value.trim()) {
      this.update(key, null);
      return;
    }
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      this.update(key, parsed);
    }
  }

  setQuality(value: string): void {
    const quality = Number(value);
    if (Number.isFinite(quality)) {
      this.update('jpeg_quality', quality);
    }
  }

  save(): void {
    const settings = this.settings();
    if (!settings) {
      return;
    }
    this.busy.set(true);
    this.error.set('');
    this.api.saveSettings(settings).subscribe({
      next: (saved) => {
        this.settings.set(saved);
        this.dirty.set(false);
        this.notice.set('Settings saved.');
        this.busy.set(false);
        this.loadAlbums();
      },
      error: (error: unknown) => {
        this.error.set(httpError(error));
        this.busy.set(false);
      },
    });
  }

  test(): void {
    const settings = this.settings();
    if (!settings) {
      return;
    }
    this.busy.set(true);
    this.connection.set(null);
    this.api.testConnection(settings).subscribe({
      next: (result) => {
        this.connection.set({
          ok: true,
          message: `Connected to Immich ${result.version} · ${result.album_count} albums`,
        });
        this.busy.set(false);
      },
      error: (error: unknown) => {
        this.connection.set({ ok: false, message: httpError(error) });
        this.busy.set(false);
      },
    });
  }

  private loadAlbums(): void {
    this.api.listAlbums().subscribe({
      next: (albums) => this.albums.set(albums),
      error: () => this.albums.set([]),
    });
  }
}
