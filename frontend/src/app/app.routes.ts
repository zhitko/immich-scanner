import { Routes } from '@angular/router';

import { BulkRetouchPage } from './bulk-retouch';
import { EditorPage } from './editor';
import { JobsPage } from './jobs';
import { MatchingPage } from './matching';
import { PhotoListPage } from './photo-list';
import { ScanListPage } from './scan-list';
import { SettingsPage } from './settings-page';
import { StatisticsPage } from './statistics';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'scans' },
  { path: 'scans', component: ScanListPage },
  { path: 'scans/:id', component: EditorPage },
  { path: 'photos', component: PhotoListPage },
  { path: 'retouch', component: BulkRetouchPage },
  { path: 'matching', component: MatchingPage },
  { path: 'photos/:id', component: EditorPage, data: { photo: true } },
  { path: 'uploaded', pathMatch: 'full', redirectTo: '/scans?status=uploaded' },
  { path: 'jobs', component: JobsPage },
  { path: 'statistics', component: StatisticsPage },
  { path: 'settings', component: SettingsPage },
];
