import { Directive, ElementRef, inject, output } from '@angular/core';

@Directive({
  selector: 'input[appDateMask]',
  host: {
    '(beforeinput)': 'beforeInput($event)',
    '(input)': 'onInput($event)',
  },
})
export class DateMask {
  private readonly input = inject<ElementRef<HTMLInputElement>>(ElementRef);
  readonly dateInput = output<string>();

  beforeInput(event: InputEvent): void {
    const input = this.input.nativeElement;
    const start = input.selectionStart ?? 0;
    if (start !== input.selectionEnd) {
      return;
    }
    // Skip separators so Backspace and Delete always remove a digit.
    if (event.inputType === 'deleteContentBackward' && input.value[start - 1] === '/') {
      input.setSelectionRange(start - 1, start - 1);
    } else if (event.inputType === 'deleteContentForward' && input.value[start] === '/') {
      input.setSelectionRange(start + 1, start + 1);
    }
  }

  onInput(event: InputEvent): void {
    const input = this.input.nativeElement;
    const raw = input.value;
    const position = input.selectionStart ?? raw.length;
    const digitsBefore = raw.slice(0, position).replace(/\D/g, '').length;
    const digits = raw.replace(/\D/g, '').slice(0, 8);
    const parts = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4)];
    let value = parts.filter(Boolean).join('/');
    if (
      !event.inputType?.startsWith('delete') &&
      position === raw.length &&
      (digits.length === 2 || digits.length === 4)
    ) {
      value += '/';
    }
    const caret = Math.min(
      digitsBefore + (digitsBefore >= 2 ? 1 : 0) + (digitsBefore >= 4 ? 1 : 0),
      value.length,
    );
    input.value = value;
    input.setSelectionRange(caret, caret);
    this.dateInput.emit(value);
  }
}
