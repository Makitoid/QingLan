import { useEffect, useState } from 'react';
import {
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  MessageBar,
  MessageBarBody,
  Text,
  tokens,
} from '@fluentui/react-components';
import { Checkmark24Regular } from '@fluentui/react-icons';
import { useTheme } from '../appTheme';
import { dismissNotice, listPendingNotices } from '../api';
import type { GroupRevokedNotice, TeacherNoticeItem } from '../api/types';
import { errMessage } from './StateViews';

/**
 * 决策 1e：挂在 Layout 里（仅教师角色），登录后拉一次待确认提示并以 Dialog 说明
 * 「可教组别被撤销、多少学生离开名单」。确认时经 API 落库，之后不再出现。
 */
export function TeacherNoticeDialog() {
  const t = useTheme();
  const [notices, setNotices] = useState<TeacherNoticeItem[]>([]);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listPendingNotices()
      .then((rows) => {
        if (!cancelled) setNotices(rows);
      })
      // 提示读不到不阻塞教师使用其它页面；下次进入 Layout 会再试。
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const current = notices[index] ?? null;
  const open = Boolean(current);

  const advance = () => {
    setError(null);
    setIndex((prev) => prev + 1);
  };

  const handleConfirm = async () => {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await dismissNotice(current.id);
      advance();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!current) return null;

  const payload = (current.payload ?? null) as Partial<GroupRevokedNotice> | null;
  const revokedGroups = current.kind === 'group_revoked' && Array.isArray(payload?.groups)
    ? payload.groups
    : [];
  const totalLost = typeof payload?.total_lost === 'number' ? payload.total_lost : 0;

  return (
    <Dialog open={open} onOpenChange={(_, d) => { if (!d.open && !busy) advance(); }}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{revokedGroups.length > 0 ? '可教组别被撤销' : '系统提示'}</DialogTitle>
          <DialogContent>
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
              {revokedGroups.length === 0 ? (
                <Text>系统有一条新的提示需要你确认。</Text>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
                  {revokedGroups.map((g) => (
                    <Text key={g.id}>
                      {`管理员已撤销你的可教组别「${g.name}」，其中 ${g.lost_count} 名学生已离开你的名单（历史提交与成绩仍保留）`}
                    </Text>
                  ))}
                  {revokedGroups.length > 1 && (
                    <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                      {`本次共 ${totalLost} 名学生离开你的名单。`}
                    </Caption1>
                  )}
                </div>
              )}
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                名单里的学生由管理员分配的可教组别决定；如需重新收录这些学生，请联系管理员恢复相应组别。
              </Caption1>

              {error && (
                <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
                  <MessageBarBody>{error}</MessageBarBody>
                </MessageBar>
              )}
            </div>
          </DialogContent>
          <DialogActions>
            <Button appearance="secondary" onClick={advance} disabled={busy}>
              稍后再说
            </Button>
            <Button
              appearance="primary"
              icon={<Checkmark24Regular />}
              disabled={busy}
              onClick={() => void handleConfirm()}
            >
              {busy ? '处理中…' : '知道了'}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

export default TeacherNoticeDialog;
