import { Component, input } from '@angular/core';

let nextHelpId = 0;

@Component({
  selector: 'app-help-tip',
  template: `
    <button type="button" class="help-icon" [attr.popovertarget]="id"
      [attr.aria-label]="label()" title="Show help">i</button>
    <div [id]="id" popover="auto" class="help-popover">
      <strong>{{ label() }}</strong>
      <div class="help-content"><ng-content /></div>
      <button type="button" [attr.popovertarget]="id" popovertargetaction="hide">Close</button>
    </div>
  `,
  styles: `
    :host { display: inline-block; vertical-align: middle; }
    .help-icon {
      display: inline-flex; align-items: center; justify-content: center;
      width: 1.35rem; height: 1.35rem; min-height: 0; padding: 0;
      margin-inline: .25rem; border: 1px solid currentColor; border-radius: 50%;
      background: transparent; color: inherit; font: bold .85rem Georgia, serif;
      cursor: pointer;
    }
    .help-icon:focus-visible { outline: 2px solid currentColor; outline-offset: 3px; }
    .help-popover {
      max-width: min(28rem, calc(100vw - 3rem)); max-height: 75vh;
      padding: 1.25rem; border: 1px solid #7b8390; border-radius: .75rem;
      background: Canvas; color: CanvasText; box-shadow: 0 8px 32px #0004;
      font: normal 1rem/1.6 system-ui; overflow: auto;
    }
    .help-content { margin: .5rem 0 1rem; }
  `,
})
export class HelpTip {
  readonly label = input('Help');
  readonly id = `help-tip-${nextHelpId++}`;
}
