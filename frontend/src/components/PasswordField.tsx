import { useState } from 'react';
import { Button, Field, Input, Label, type FieldProps } from '@fluentui/react-components';
import { Eye24Regular, EyeOff24Regular } from '@fluentui/react-icons';

interface PasswordFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoComplete?: string;
  required?: boolean;
  hint?: FieldProps['hint'];
  autoFocus?: boolean;
}

export function PasswordField({
  id,
  label,
  value,
  onChange,
  placeholder,
  autoComplete,
  required,
  hint,
  autoFocus,
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);

  return (
    <Field label={<Label htmlFor={id}>{label}</Label>} required={required} hint={hint}>
      <Input
        id={id}
        type={visible ? 'text' : 'password'}
        value={value}
        onChange={(_, data) => onChange(data.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        contentAfter={
          <Button
            type="button"
            appearance="subtle"
            icon={visible ? <EyeOff24Regular /> : <Eye24Regular />}
            aria-label={visible ? '隐藏密码' : '显示密码'}
            onClick={() => setVisible((prev) => !prev)}
          />
        }
      />
    </Field>
  );
}
