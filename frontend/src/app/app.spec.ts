import { provideRouter } from '@angular/router';
import { TestBed } from '@angular/core/testing';

import { App } from './app';
import { routes } from './app.routes';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter(routes)],
    }).compileComponents();
  });

  it('renders the review navigation', () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('h1')?.textContent).toContain('Scanner desk');
    const labels = [...compiled.querySelectorAll('nav a')].map((link) => link.textContent?.trim());
    expect(labels).toEqual(['Scans', 'Photos', 'Matching', 'Jobs', 'Statistics', 'Settings']);
  });
});
