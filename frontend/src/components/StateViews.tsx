import type { ReactNode } from 'react';
import { Button, MessageBar, MessageBarActions, MessageBarBody, Spinner, Text, tokens } from '@fluentui/react-components';
import { ApiError } from '../api/client';

export function errMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error && e.message) return e.message;
  return '发生未知错误';
}

export function errCode(e: unknown): string | null {
  return e instanceof ApiError ? e.code : null;
}

export function LoadingView({ label = '加载中…' }: { label?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', padding: tokens.spacingVerticalXXL }}>
      <Spinner label={label} />
    </div>
  );
}

export function ErrorView({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const code = errCode(error);
  return (
    <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium, marginBlock: tokens.spacingVerticalM }}>
      <MessageBarBody>
        {errMessage(error)}
        {code ? <Text size={200} style={{ color: tokens.colorNeutralForeground4 }}>（{code}）</Text> : null}
      </MessageBarBody>
      {onRetry && (
        <MessageBarActions>
          <Button size="small" onClick={onRetry}>重试</Button>
        </MessageBarActions>
      )}
    </MessageBar>
  );
}

export function EmptyView({ title, description, action }: { title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: tokens.spacingVerticalS,
        padding: `${tokens.spacingVerticalXXL} ${tokens.spacingHorizontalL}`,
        border: `1px dashed ${tokens.colorNeutralStroke2}`,
        borderRadius: tokens.borderRadiusLarge,
        marginBlock: tokens.spacingVerticalM,
      }}
    >
      <Text weight="semibold">{title}</Text>
      {description && <Text size={200} style={{ color: tokens.colorNeutralForeground3 }}>{description}</Text>}
      {action}
    </div>
  );
}
