import { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Caption1,
  Combobox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Listbox,
  MessageBar,
  MessageBarBody,
  Option,
  Spinner,
  Text,
  tokens,
} from '@fluentui/react-components';
import { ArrowExit24Regular, Group24Regular } from '@fluentui/react-icons';
import { useTheme } from '../appTheme';
import type { GroupItem, GroupMembershipAction } from '../api/types';
import { errMessage } from './StateViews';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** add = 加入分组，remove = 移出分组 */
  action: GroupPickerAction;
  /** 候选分组（含人数）；教师端为只读的组定义 */
  groups: GroupItem[];
  /** 本次操作涉及的学生数，仅用于文案 */
  studentCount: number;
  /** 提交回调：由调用方决定走管理员还是教师端接口，抛错即视为失败 */
  onSubmit: (groupIds: number[]) => Promise<unknown>;
  /** 提交成功后回调（父组件用于 reload / 清空选择）；对话框由本组件关闭 */
  onSubmitted?: (groupIds: number[]) => void;
}

/** 加入 / 移出方向，与后端批量接口的 action 字段同义。 */
export type GroupPickerAction = GroupMembershipAction;

/**
 * 批量加入 / 移出分组对话框。
 * 管理员页与教师页共用：差异只在 onSubmit 里换成各自的接口。
 */
export function GroupPickerDialog({ open, onOpenChange, action, groups, studentCount, onSubmit, onSubmitted }: Props) {
  const t = useTheme();
  const [pickedIds, setPickedIds] = useState<string[]>([]);
  const [text, setText] = useState('');
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 每次打开都回到干净状态
  useEffect(() => {
    if (!open) return;
    setPickedIds([]);
    setText('');
    setQuery('');
    setError(null);
    setBusy(false);
  }, [open, action]);

  const nameById = useMemo(() => new Map(groups.map((g) => [String(g.id), g] as const)), [groups]);
  const picked = pickedIds.map((id) => nameById.get(id)).filter((g): g is GroupItem => Boolean(g));
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? groups.filter((g) => g.name.toLowerCase().includes(q)) : groups;
  }, [groups, query]);

  const isAdd = action === 'add';

  const handleSubmit = async () => {
    const ids = pickedIds.map(Number).filter((n) => !Number.isNaN(n));
    if (ids.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(ids);
      onOpenChange(false);
      onSubmitted?.(ids);
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(_, d) => onOpenChange(d.open)}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{isAdd ? '加入分组' : '移出分组'}</DialogTitle>
          <DialogContent>
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                {isAdd
                  ? `将把选中的 ${studentCount} 名学生加入下列分组（已在组内的学生自动跳过）。`
                  : `将把选中的 ${studentCount} 名学生移出下列分组（未加入的分组不受影响）。`}
              </Caption1>

              {error && (
                <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                  <MessageBarBody>{error}</MessageBarBody>
                </MessageBar>
              )}

              {groups.length === 0 ? (
                <Text size={200} style={{ color: t.colorNeutralForeground3 }}>
                  还没有任何分组，请先由管理员在「学生管理 → 分组管理」中创建。
                </Text>
              ) : (
                <>
                  <Combobox
                    multiselect
                    appearance="outline"
                    placeholder={isAdd ? '选择一个或多个分组' : '选择要移出的分组'}
                    value={text}
                    selectedOptions={pickedIds}
                    disabled={busy}
                    style={{ width: '100%' }}
                    onChange={(e) => {
                      const v = e.target instanceof HTMLInputElement ? e.target.value : '';
                      setText(v);
                      setQuery(v);
                    }}
                    onOptionSelect={(_, d) => {
                      const ids = d.selectedOptions ?? [];
                      setPickedIds(ids);
                      setQuery('');
                      setText(ids.map((id) => nameById.get(id)?.name ?? id).join('、'));
                    }}
                  >
                    <Listbox>
                      {visible.map((g) => (
                        <Option key={g.id} value={String(g.id)}>
                          {`${g.name}（${g.member_count} 人）`}
                        </Option>
                      ))}
                      {visible.length === 0 && (
                        <Option value="__none__" disabled>
                          没有匹配的分组
                        </Option>
                      )}
                    </Listbox>
                  </Combobox>

                  {picked.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalXS }}>
                      <Text size={200} style={{ color: t.colorNeutralForeground3 }}>
                        已选 {picked.length} 个分组：
                      </Text>
                      {picked.map((g) => (
                        <Badge key={g.id} appearance="tint" size="small">
                          {g.name}
                        </Badge>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
              取消
            </Button>
            <Button
              appearance="primary"
              icon={busy ? <Spinner size="tiny" /> : isAdd ? <Group24Regular /> : <ArrowExit24Regular />}
              disabled={busy || pickedIds.length === 0 || groups.length === 0}
              onClick={() => void handleSubmit()}
            >
              {busy ? '处理中…' : isAdd ? '确认加入' : '确认移出'}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
