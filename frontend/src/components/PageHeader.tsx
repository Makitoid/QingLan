import type { ReactNode } from 'react';
import { Caption1, Text, tokens } from '@fluentui/react-components';
import { useTheme } from '../appTheme';

/**
 * 页面级标题区。副标题固定在大标题下方独占一行；操作按钮靠右，窄屏自动换行。
 */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  const t = useTheme();
  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: tokens.spacingHorizontalM,
          flexWrap: 'wrap',
        }}
      >
        <Text as="h2" size={600} weight="semibold">
          {title}
        </Text>
        {actions && (
          <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS }}>{actions}</div>
        )}
      </div>
      {subtitle && (
        <Caption1
          style={{
            color: t.colorNeutralForeground3,
            display: 'block',
            marginTop: tokens.spacingVerticalSNudge,
          }}
        >
          {subtitle}
        </Caption1>
      )}
    </div>
  );
}
