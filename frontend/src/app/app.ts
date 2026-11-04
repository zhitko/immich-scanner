import { Component, effect, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

type Theme = 'system' | 'light' | 'dark';

const THEME_KEY = 'immich-scanner.theme';
const THEME_ORDER: Theme[] = ['system', 'light', 'dark'];

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
})
export class App {
  readonly theme = signal<Theme>(storedTheme());

  constructor() {
    effect(() => {
      const theme = this.theme();
      const root = document.documentElement;
      if (theme === 'system') {
        delete root.dataset['theme'];
      } else {
        root.dataset['theme'] = theme;
      }
      localStorage.setItem(THEME_KEY, theme);
    });
  }

  cycleTheme(): void {
    const next = (THEME_ORDER.indexOf(this.theme()) + 1) % THEME_ORDER.length;
    this.theme.set(THEME_ORDER[next]);
  }
}

function storedTheme(): Theme {
  const value = localStorage.getItem(THEME_KEY);
  return value === 'light' || value === 'dark' ? value : 'system';
}
