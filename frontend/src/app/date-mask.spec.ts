import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { DateMask } from './date-mask';

@Component({
  imports: [DateMask],
  template: '<input appDateMask [value]="value" (dateInput)="value = $event" />',
})
class DateField {
  value = '';
}

describe('date input mask', () => {
  function setup() {
    const fixture = TestBed.createComponent(DateField);
    fixture.detectChanges();
    const input = (fixture.nativeElement as HTMLElement).querySelector('input')!;

    function edit(text: string, inputType = 'insertText') {
      input.dispatchEvent(new InputEvent('beforeinput', { inputType, bubbles: true }));
      const start = input.selectionStart!;
      const end = input.selectionEnd!;
      if (inputType === 'deleteContentBackward' && start === end) {
        input.setRangeText('', Math.max(0, start - 1), end, 'end');
      } else if (inputType === 'deleteContentForward' && start === end) {
        input.setRangeText('', start, Math.min(input.value.length, end + 1), 'end');
      } else {
        input.setRangeText(text, start, end, 'end');
      }
      input.dispatchEvent(new InputEvent('input', { inputType, bubbles: true }));
      fixture.detectChanges();
    }

    return { fixture, input, edit };
  }

  it('inserts separators while typing only digits and updates the draft', () => {
    const { fixture, input, edit } = setup();
    for (const digit of '07112026') {
      edit(digit);
    }
    expect(input.value).toBe('07/11/2026');
    expect(fixture.componentInstance.value).toBe('07/11/2026');
    expect(input.selectionStart).toBe(10);
  });

  it.each(['07112026', '07/11/2026'])('formats pasted date %s', (text) => {
    const { input, edit } = setup();
    edit(text, 'insertFromPaste');
    expect(input.value).toBe('07/11/2026');
  });

  it('allows manually typed separators too', () => {
    const { input, edit } = setup();
    for (const character of '07/11/2026') {
      edit(character);
    }
    expect(input.value).toBe('07/11/2026');
  });

  it('backspaces across separators and clears the field', () => {
    const { fixture, input, edit } = setup();
    edit('0711');
    expect(input.value).toBe('07/11/');
    edit('', 'deleteContentBackward');
    expect(input.value).toBe('07/1');
    edit('', 'deleteContentBackward');
    expect(input.value).toBe('07');
    edit('', 'deleteContentBackward');
    expect(input.value).toBe('0');
    edit('', 'deleteContentBackward');
    expect(input.value).toBe('');
    expect(fixture.componentInstance.value).toBe('');
  });

  it('deletes forward across a separator', () => {
    const { input, edit } = setup();
    edit('07112026');
    input.setSelectionRange(2, 2);
    edit('', 'deleteContentForward');
    expect(input.value).toBe('07/12/026');
    expect(input.selectionStart).toBe(3);
  });

  it('keeps the caret beside a replaced day', () => {
    const { input, edit } = setup();
    edit('07112026');
    input.setSelectionRange(0, 2);
    edit('15');
    expect(input.value).toBe('15/11/2026');
    expect(input.selectionStart).toBe(3);
  });

  it('removes non-digits and limits input to eight digits', () => {
    const { input, edit } = setup();
    edit('abc07112026999', 'insertFromPaste');
    expect(input.value).toBe('07/11/2026');
  });
});
