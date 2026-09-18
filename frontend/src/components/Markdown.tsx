import ReactMarkdown from 'react-markdown';
import { tokens } from '@fluentui/react-components';

export function MarkdownBody({ children }: { children: string }) {
  return (
    <div
      className="ql-markdown"
      style={{ fontSize: tokens.fontSizeBase300, color: tokens.colorNeutralForeground1 }}
    >
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  );
}
