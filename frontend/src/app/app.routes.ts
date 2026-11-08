import { Routes } from '@angular/router';

import { EditorPage } from './editor';
import { JobsPage } from './jobs';
import { ScanListPage } from './scan-list';
import { SettingsPage } from './settings-page';
import { StatisticsPage } from './statistics';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'scans' },
  { path: 'scans', component: ScanListPage },
  { path: 'scans/:id', component: EditorPage },
  { path: 'uploaded', pathMatch: 'full', redirectTo: '/scans?status=uploaded' },
  { path: 'jobs', component: JobsPage },
  { path: 'statistics', component: StatisticsPage },
  { path: 'settings', component: SettingsPage },
];
