import { useState } from 'react';
import {
  Badge,
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Input,
  MessageBar,
  MessageBarBody,
  Spinner,
  Text,
  tokens,
} from '@fluentui/react-components';
import { Add24Regular, Checkmark24Regular, Delete24Regular, Dismiss24Regular, Edit24Regular } from '@fluentui/react-icons';
import { useTheme } from '../appTheme';
import { createGroup, deleteGroup, listGroups, renameGroup } from '../api';
import type { GroupItem } from '../api/types';
import { useAsync } from './useAsync';
import { EmptyView, ErrorView, LoadingView, errCode, errMessage } from './StateViews';

const MAX_NAME_LENGTH = 50;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 分组有新增 / 重命名 / 删除时回调，父组件用它刷新分组下拉与学生列表 */
  onChanged?: () => void;
}

/**
 * 管理员「分组管理」对话框：列表 + 行内重命名 + 删除前确认 + 新建。
 * 数据在本组件内自取（对话框每次打开重新挂载，拿到最新成员数）。
 */
export function GroupsManageDialog({ open, onOpenChange, onChanged }: Props) {
  return (
    <Dialog open={open} onOpenChange={(_, d) => onOpenChange(d.open)}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>分组管理</DialogTitle>
          {/* 每次打开重新挂载面板，保证成员数是最新的 */}
          {open && <GroupsPanel onChanged={onChanged} onClose={() => onOpenChange(false)} />}
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

function GroupsPanel({ onChanged, onClose }: { onChanged?: () => void; onClose: () => void }) {
  const t = useTheme();
  const { data, error, loading, reload } = useAsync(listGroups, []);
  const [newName, setNewName] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingName, setEditingName] = useState('');
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const groups = data ?? [];

  /** 重名（409 GROUP_NAME_EXISTS）给出比后端原文更友好的提示。 */
  const friendlyError = (e: unknown, name: string) =>
    errCode(e) === 'GROUP_NAME_EXISTS' ? `已存在同名分组「${name}」，请换一个名称。` : errMessage(e);

  const checkName = (raw: string): string | null => {
    const name = raw.trim();
    if (!name) return '分组名称不能为空';
    if (name.length > MAX_NAME_LENGTH) return `分组名称不能超过 ${MAX_NAME_LENGTH} 个字`;
    return null;
  };

  const handleCreate = async () => {
    const name = newName.trim();
    const invalid = checkName(name);
    if (invalid) {
      setFormError(invalid);
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      await createGroup(name);
      setNewName('');
      reload();
      onChanged?.();
    } catch (e) {
      setFormError(friendlyError(e, name));
    } finally {
      setBusy(false);
    }
  };

  const startRename = (group: GroupItem) => {
    setEditingId(group.id);
    setEditingName(group.name);
    setFormError(null);
  };

  const handleRename = async (group: GroupItem) => {
    const name = editingName.trim();
    const invalid = checkName(name);
    if (invalid) {
      setFormError(invalid);
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      await renameGroup(group.id, name);
      setEditingId(null);
      setEditingName('');
      reload();
      onChanged?.();
    } catch (e) {
      setFormError(friendlyError(e, name));
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (group: GroupItem) => {
    const detail =
      group.member_count > 0
        ? `该分组下有 ${group.member_count} 名学生，删除后这些成员关系一并移除（学生账号本身不受影响）。`
        : '该分组暂无成员。';
    if (!window.confirm(`确定删除分组「${group.name}」？${detail}`)) return;
    setBusy(true);
    setFormError(null);
    try {
      await deleteGroup(group.id);
      if (editingId === group.id) {
        setEditingId(null);
        setEditingName('');
      }
      reload();
      onChanged?.();
    } catch (e) {
      setFormError(friendlyError(e, group.name));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <DialogContent>
        <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
          <Caption1 style={{ color: t.colorNeutralForeground3 }}>
            分组为全站共享，教师可在自己的学生页调整成员；名称唯一，不超过 {MAX_NAME_LENGTH} 个字。
          </Caption1>

          <div style={{ display: 'flex', gap: tokens.spacingHorizontalS, alignItems: 'flex-end' }}>
            <Input
              value={newName}
              onChange={(_, d) => setNewName(d.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  void handleCreate();
                }
              }}
              placeholder="新分组名称，如：高一（1）班"
              maxLength={MAX_NAME_LENGTH}
              disabled={busy}
              style={{ flex: 1 }}
            />
            <Button appearance="primary" icon={<Add24Regular />} disabled={busy || !newName.trim()} onClick={() => void handleCreate()}>
              新建
            </Button>
          </div>

          {formError && (
            <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
              <MessageBarBody>{formError}</MessageBarBody>
            </MessageBar>
          )}

          {loading ? (
            <LoadingView />
          ) : error ? (
            <ErrorView error={error} onRetry={reload} />
          ) : groups.length === 0 ? (
            <EmptyView title="还没有分组" description="在上方输入名称即可创建第一个分组。" />
          ) : (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: tokens.spacingVerticalSNudge,
                border: `1px solid ${t.colorNeutralStroke2}`,
                borderRadius: tokens.borderRadiusMedium,
                padding: tokens.spacingVerticalS,
                maxHeight: '360px',
                overflowY: 'auto',
              }}
            >
              {groups.map((group) => (
                <div
                  key={group.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: tokens.spacingHorizontalS,
                    paddingInline: tokens.spacingHorizontalSNudge,
                  }}
                >
                  {editingId === group.id ? (
                    <>
                      <Input
                        value={editingName}
                        onChange={(_, d) => setEditingName(d.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            void handleRename(group);
                          } else if (e.key === 'Escape') {
                            setEditingId(null);
                          }
                        }}
                        maxLength={MAX_NAME_LENGTH}
                        disabled={busy}
                        autoFocus
                        style={{ flex: 1 }}
                      />
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<Checkmark24Regular />}
                        disabled={busy || !editingName.trim()}
                        onClick={() => void handleRename(group)}
                      >
                        保存
                      </Button>
                      <Button
                        size="small"
                        appearance="subtle"
                        icon={<Dismiss24Regular />}
                        disabled={busy}
                        onClick={() => setEditingId(null)}
                      >
                        取消
                      </Button>
                    </>
                  ) : (
                    <>
                      <Text weight="semibold">{group.name}</Text>
                      <Badge appearance="outline" size="large">
                        {group.member_count} 人
                      </Badge>
                      <div style={{ marginLeft: 'auto', display: 'flex', gap: tokens.spacingHorizontalXS }}>
                        <Button
                          size="small"
                          appearance="subtle"
                          icon={<Edit24Regular />}
                          disabled={busy}
                          onClick={() => startRename(group)}
                        >
                          重命名
                        </Button>
                        <Button
                          size="small"
                          appearance="subtle"
                          icon={<Delete24Regular />}
                          disabled={busy}
                          style={{ color: t.colorPaletteRedForeground1 }}
                          onClick={() => void handleDelete(group)}
                        >
                          删除
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              ))}
              {busy && (
                <div style={{ display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalXS }}>
                  <Spinner size="tiny" />
                  <Text size={200} style={{ color: t.colorNeutralForeground3 }}>
                    处理中…
                  </Text>
                </div>
              )}
            </div>
          )}
        </div>
      </DialogContent>
      <DialogActions>
        <Button appearance="primary" onClick={onClose}>
          完成
        </Button>
      </DialogActions>
    </>
  );
}
