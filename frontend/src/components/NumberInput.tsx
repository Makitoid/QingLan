import { SpinButton } from '@fluentui/react-components';

interface Props {
  value: number | null | undefined;
  onValue: (value: number) => void;
  min?: number;
  step?: number;
  disabled?: boolean;
  width?: string;
}

export function NumberInput({ value, onValue, min, step, disabled, width = '100%' }: Props) {
  return (
    <SpinButton
      value={value ?? null}
      min={min}
      step={step}
      disabled={disabled}
      onChange={(_, d) => {
        if (typeof d.value === 'number' && !Number.isNaN(d.value)) {
          onValue(d.value);
          return;
        }
        const parsed = Number.parseFloat(String(d.displayValue ?? '').trim());
        if (!Number.isNaN(parsed)) onValue(parsed);
      }}
      style={{ width }}
    />
  );
}
