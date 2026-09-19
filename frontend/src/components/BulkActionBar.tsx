import type { ReactElement, ReactNode } from 'react';
import { Button, Text, tokens, type ButtonProps } from '@fluentui/react-components';
import { useTheme } from '../appTheme';

export interface BulkAction {
  /** React key，同时也是语义标识（如 'group-add' / 'cancel'） */
  key: string;
  label: ReactNode;
  onClick: () => void;
  /** 传 <PeopleTeam24Regular /> 这类图标元素 */
  icon?: ReactElement;
  appearance?: ButtonProps['appearance'];
  /** 单个按钮临时禁用（如提交中、选中状态不满足条件） */
  disabled?: boolean;
  /** 危险操作：走 danger 令牌，与品牌底色区分 */
  danger?: boolean;
}

interface Props {
  /** 选中行数；为 0 时整条不渲染 */
  selectedCount: number;
  /** 右侧按钮，全部由调用方注入：组件本身不含任何业务语义 */
  actions?: BulkAction[];
  /** 左侧文案，默认「已选 N 名学生」 */
  label?: ReactNode;
  /** 追加在按钮组右侧的自定义内容 */
  children?: ReactNode;
}

/**
 * 批量操作条：放在 PageHeader 与表格之间，仅在 selectedCount > 0 时出现。
 * 品牌浅底 + 描边，暗色模式下由 Fluent 令牌自动切换。
 */
export function BulkActionBar({ selectedCount, actions = [], label, children }: Props) {
  const t = useTheme();
  if (selectedCount <= 0) return null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: tokens.spacingHorizontalS,
        padding: `${tokens.spacingVerticalSNudge} ${tokens.spacingHorizontalM}`,
        backgroundColor: t.colorBrandBackground2,
        border: `1px solid ${t.colorBrandStroke1}`,
        borderRadius: tokens.borderRadiusMedium,
      }}
    >
      <Text size={300} weight="semibold" style={{ color: t.colorBrandForeground1 }}>
        {label ?? `已选 ${selectedCount} 名学生`}
      </Text>
      <div
        style={{
          marginLeft: 'auto',
          display: 'flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: tokens.spacingHorizontalXS,
        }}
      >
        {actions.map((action) => (
          <Button
            key={action.key}
            size="small"
            appearance={action.appearance ?? (action.danger ? 'outline' : 'secondary')}
            icon={action.icon}
            disabled={action.disabled}
            onClick={action.onClick}
            style={action.danger ? { color: t.colorPaletteRedForeground1 } : undefined}
          >
            {action.label}
          </Button>
        ))}
        {children}
      </div>
    </div>
  );
}
