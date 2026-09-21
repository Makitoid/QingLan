import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Card,
  CardHeader,
  Caption1,
  Field,
  Input,
  Label,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  Text,
  tokens,
} from '@fluentui/react-components';
import { Save24Regular } from '@fluentui/react-icons';
import { changePassword } from '../api';
import { ApiError } from '../api/client';
import { errMessage } from '../components/StateViews';
import { PageHeader } from '../components/PageHeader';
import { PASSWORD_MIN_LENGTH, PASSWORD_RULES_TEXT, validateNewPassword } from '../components/passwordPolicy';
import { CHANGE_PASSWORD_PATH, useAuthUser } from '../components/Guard';

const ROLE_LABEL: Record<string, string> = { admin: '管理员', teacher: '教师', student: '学生' };

/**
 * 账号设置：自助改密（PW-03 与强制改密同一套规则，前端预校验 + 后端 422 中文 message 都显示）。
 *
 * `must_change_password=true` 时这里会被路由守卫换成 `/change-password`（PW-02），
 * 所以本页只在「已改过密」的正常状态下可见。
 */
export function AccountPage() {
  const navigate = useNavigate();
  const user = useAuthUser();
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ intent: 'success' | 'error'; text: string } | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setMessage(null);
    if (!user) return;
    if (!oldPassword || !newPassword || !confirm) {
      setMessage({ intent: 'error', text: '请填写当前密码、新密码与确认新密码' });
      return;
    }
    const invalid = validateNewPassword(newPassword, {
      username: user.username,
      displayName: user.display_name,
      oldPassword,
    });
    if (invalid) {
      setMessage({ intent: 'error', text: invalid });
      return;
    }
    if (newPassword !== confirm) {
      setMessage({ intent: 'error', text: '两次输入的新密码不一致' });
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
      // 兜底：万一本地登录态是旧的（例如管理员刚重置过），后端会回 403 MUST_CHANGE_PASSWORD，
      // 此时直接把用户送到强制改密页，别在账号设置页显示一条看不懂的报错。
      if (err instanceof ApiError && err.code === 'MUST_CHANGE_PASSWORD') {
        navigate(CHANGE_PASSWORD_PATH, { replace: true });
        return;
      }
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
          <MessageBarActions>
            <Button size="small" appearance="subtle" onClick={() => setMessage(null)}>
              关闭
            </Button>
          </MessageBarActions>
        </MessageBar>
      )}

      <Card size="medium">
        <CardHeader header={<Text weight="semibold">修改密码</Text>} />
        <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
          <Field label={<Label htmlFor="ql-acc-old">当前密码</Label>} required>
            <Input
              id="ql-acc-old"
              type="password"
              value={oldPassword}
              onChange={(_, d) => setOldPassword(d.value)}
              autoComplete="current-password"
            />
          </Field>
          <Field label={<Label htmlFor="ql-acc-new">新密码</Label>} required hint={PASSWORD_RULES_TEXT}>
            <Input
              id="ql-acc-new"
              type="password"
              value={newPassword}
              onChange={(_, d) => setNewPassword(d.value)}
              autoComplete="new-password"
            />
          </Field>
          <Field label={<Label htmlFor="ql-acc-confirm">确认新密码</Label>} required>
            <Input
              id="ql-acc-confirm"
              type="password"
              value={confirm}
              onChange={(_, d) => setConfirm(d.value)}
              autoComplete="new-password"
            />
          </Field>
          <Caption1 style={{ color: tokens.colorNeutralForeground3 }}>
            新密码长度至少 {PASSWORD_MIN_LENGTH} 位；忘了当前密码请联系管理员重置。
          </Caption1>
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
