import CodeMirror from '@uiw/react-codemirror';
import { cpp } from '@codemirror/lang-cpp';
import { tokens } from '@fluentui/react-components';
import { useThemeMode } from '../context';

interface Props {
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  height?: string;
}

export function CodeEditor({ value, onChange, readOnly, height = '420px' }: Props) {
  const { isDark } = useThemeMode();
  return (
    <div style={{ border: `1px solid ${tokens.colorNeutralStroke1}`, borderRadius: tokens.borderRadiusMedium, overflow: 'hidden' }}>
      <CodeMirror
        value={value}
        height={height}
        theme={isDark ? 'dark' : 'light'}
        editable={!readOnly}
        readOnly={readOnly}
        extensions={[cpp()]}
        onChange={onChange}
        basicSetup={{ lineNumbers: true, foldGutter: false, highlightActiveLine: !readOnly }}
      />
    </div>
  );
}
