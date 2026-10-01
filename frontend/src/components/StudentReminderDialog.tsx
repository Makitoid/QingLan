import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
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
import { ArrowRight24Regular, Checkmark24Regular } from '@fluentui/react-icons';
import { useTheme } from '../appTheme';
import { dismissStudentReminder, listStudentReminders } from '../api';
import type { StudentReminderItem } from '../api/types';
import { errMessage } from './StateViews';
import { fmtTime } from './time';

/**
 * 0.4.1 F6：教师「提醒交作业」的学生侧呈现——登录后逐条弹窗。
 *
 * 挂在 Layout 里（仅学生角色），进页面拉一次未读。确认走 API 落库后不再出现；
 * 「稍后再说」只翻到下一条、不落库，下次登录仍会提醒。
 */
export function StudentReminderDialog() {
  const t = useTheme();
  const navigate = useNavigate();
  const [items, setItems] = useState<StudentReminderItem[]>([]);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listStudentReminders()
      .then((rows) => {
        if (!cancelled) setItems(rows);
      })
      // 提醒读不到不该挡住学生正常做题；下次进入 Layout 会再试。
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const current = items[index] ?? null;
  const advance = () => {
    setError(null);
    setIndex((prev) => prev + 1);
  };

  const handleAcknowledge = async () => {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await dismissStudentReminder(current.id);
      advance();
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const goToAssignment = async () => {
    if (!current) return;
    await handleAcknowledge();
    navigate(`/student/assignments/${current.assignment_id}`);
  };

  if (!current) return null;

  const modeLabel = current.assignment_mode === 'test' ? '测评' : '作业';

  return (
    <Dialog open onOpenChange={(_, d) => { if (!d.open && !busy) advance(); }}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>老师提醒：还有{modeLabel}没交</DialogTitle>
          <DialogContent>
            <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalS }}>
              <Text weight="semibold">{current.assignment_title}</Text>
              <Caption1 style={{ color: t.colorNeutralForeground3 }}>
                {`${current.teacher_name} 提醒你尽快提交。截止时间 ${fmtTime(current.end_time)}。`}
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
            <Button appearance="outline" icon={<Checkmark24Regular />} disabled={busy} onClick={() => void handleAcknowledge()}>
              知道了
            </Button>
            <Button appearance="primary" icon={<ArrowRight24Regular />} disabled={busy} onClick={() => void goToAssignment()}>
              {items.length > 1 ? `去看这条（${index + 1}/${items.length}）` : '去作答'}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

export default StudentReminderDialog;
