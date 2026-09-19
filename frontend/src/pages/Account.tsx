import { useState, type FormEvent } from 'react';
import { Button, Card, CardHeader, Field, Input, Label, MessageBar, MessageBarBody, Text, tokens } from '@fluentui/react-components';
import { Save24Regular } from '@fluentui/react-icons';
import { changePassword } from '../api';
import { getStoredUser } from '../api/client';
import { errMessage } from '../components/StateViews';
import { PageHeader } from '../components/PageHeader';

const ROLE_LABEL: Record<string, string> = { admin: '管理员', teacher: '教师', student: '学生' };

export function AccountPage() {
  const user = getStoredUser();
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ intent: 'success' | 'error'; text: string } | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setMessage(null);
    if (!oldPassword || !newPassword) {
      setMessage({ intent: 'error', text: '请填写当前密码与新密码' });
      return;
    }
    if (newPassword.length < 6) {
      setMessage({ intent: 'error', text: '新密码至少 6 位' });
      return;
    }
    if (newPassword !== confirm) {
      setMessage({ intent: 'error', text: '两次输入的新密码不一致' });
      return;
    }
    if (newPassword === oldPassword) {
      setMessage({ intent: 'error', text: '新密码不能与当前密码相同' });
      return;
    }
    setBusy(true);
    try {
      await changePassword(oldPassword, newPassword);
      setOldPassword('');
      setNewPassword('');
      setConfirm('');
      setMessage({ intent: 'success', text: '密码已修改，下次登录请使用新密码' });
    } catch (err) {
      setMessage({ intent: 'error', text: errMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL, maxWidth: '520px' }}>
      <PageHeader
        title="账号设置"
        subtitle={
          <>
            {user?.display_name ?? ''}
            {user ? ` · ${user.username} · ${ROLE_LABEL[user.role] ?? user.role}` : ''}
          </>
        }
      />

      {message && (
        <MessageBar intent={message.intent} style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>{message.text}</MessageBarBody>
        </MessageBar>
      )}

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">修改密码</Text>} />
        <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
          <Field label={<Label htmlFor="ql-acc-old">当前密码</Label>}>
            <Input
              id="ql-acc-old"
              type="password"
              value={oldPassword}
              onChange={(_, d) => setOldPassword(d.value)}
              autoComplete="current-password"
            />
          </Field>
          <Field label={<Label htmlFor="ql-acc-new">新密码</Label>} hint="至少 6 位">
            <Input
              id="ql-acc-new"
              type="password"
              value={newPassword}
              onChange={(_, d) => setNewPassword(d.value)}
              autoComplete="new-password"
            />
          </Field>
          <Field label={<Label htmlFor="ql-acc-confirm">确认新密码</Label>}>
            <Input
              id="ql-acc-confirm"
              type="password"
              value={confirm}
              onChange={(_, d) => setConfirm(d.value)}
              autoComplete="new-password"
            />
          </Field>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button appearance="primary" type="submit" icon={<Save24Regular />} disabled={busy}>
              {busy ? '提交中…' : '保存新密码'}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
