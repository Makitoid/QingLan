import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../appTheme';
import {
  Button,
  Card,
  CardHeader,
  Caption1,
  Field,
  Input,
  Label,
  MessageBar,
  MessageBarBody,
  Text,
  tokens,
} from '@fluentui/react-components';
import { LockClosed24Regular } from '@fluentui/react-icons';
import { changePassword, getMe } from '../api';
import { updateStoredUser } from '../api/client';
import { errMessage } from '../components/StateViews';
import { PageHeader } from '../components/PageHeader';
import { PASSWORD_MIN_LENGTH, PASSWORD_RULES_TEXT, validateNewPassword } from '../components/passwordPolicy';
import { roleHome, useAuthUser } from '../components/Guard';

const ROLE_LABEL: Record<string, string> = { admin: '管理员', teacher: '教师', student: '学生' };

/**
 * PW-02 / PW-03：改密页，同时服务两种进入方式——
 * ① `must_change_password=true` 时被全站路由守卫强制送到这里（无「跳过」入口，
 *    后端业务接口此时一律 403 MUST_CHANGE_PASSWORD，只有 `/auth/password`、`/auth/me`、
 *    `/api/settings*` 在白名单里）；② 用户主动从「账号设置」/头像菜单进来自助改密。
 *
 * 新密码规则前后端各校验一遍：这里先给即时反馈，后端的 422 PASSWORD_POLICY
 * 中文 message 原样显示（两边文案见 `components/passwordPolicy.ts`）。
 */
export function ChangePasswordPage() {
  const t = useTheme();
  const navigate = useNavigate();
  const user = useAuthUser();
  const forced = Boolean(user?.must_change_password);

  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!user) return;
    if (!oldPassword || !newPassword || !confirm) {
      setError('请填写当前密码、新密码与确认新密码');
      return;
    }
    const invalid = validateNewPassword(newPassword, {
      username: user.username,
      displayName: user.display_name,
      oldPassword,
    });
    if (invalid) {
      setError(invalid);
      return;
    }
    if (newPassword !== confirm) {
      setError('两次输入的新密码不一致');
      return;
    }
    setBusy(true);
    try {
      await changePassword(oldPassword, newPassword);
      // 清拦截态以服务端为准（PW-02）：`/auth/me` 是唯一能确认 must_change 已落地的只读接口。
      try {
        const me = await getMe();
        updateStoredUser({ must_change_password: me.must_change_password });
      } catch {
        updateStoredUser({ must_change_password: false });
      }
      navigate(roleHome(user.role), { replace: true });
    } catch (err) {
      // 400 BAD_OLD_PASSWORD / 422 PASSWORD_POLICY 的中文 message 直接透出。
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL, maxWidth: '560px' }}>
      <PageHeader
        title="修改密码"
        subtitle={
          user
            ? `${user.display_name} · ${user.username} · ${ROLE_LABEL[user.role] ?? user.role}`
            : undefined
        }
      />

      {forced ? (
        <MessageBar intent="warning" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>
            <Text weight="semibold">必须先修改密码才能继续使用。</Text>
            <Caption1 style={{ display: 'block', color: t.colorNeutralForeground3 }}>
              你正在使用统一初始密码或管理员重置的临时密码。改密前其他页面均不可访问，也没有「跳过」入口；
              修改完成后其他账号功能不受影响。
            </Caption1>
          </MessageBarBody>
        </MessageBar>
      ) : (
        <MessageBar intent="info" style={{ borderRadius: tokens.borderRadiusMedium }}>
          <MessageBarBody>自助修改密码：修改成功后当前登录仍然有效，下次登录请使用新密码。</MessageBarBody>
        </MessageBar>
      )}

      <Card size="medium">
        <CardHeader
          header={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: tokens.spacingHorizontalS }}>
              <LockClosed24Regular style={{ color: t.colorBrandForeground1 }} />
              <Text weight="semibold">设置新密码</Text>
            </span>
          }
        />
        <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM }}>
          {error && (
            <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
              <MessageBarBody>{error}</MessageBarBody>
            </MessageBar>
          )}
          <Field label={<Label htmlFor="ql-cp-old">当前密码</Label>} required>
            <Input
              id="ql-cp-old"
              type="password"
              value={oldPassword}
              onChange={(_, d) => setOldPassword(d.value)}
              autoComplete="current-password"
              autoFocus
            />
          </Field>
          <Field label={<Label htmlFor="ql-cp-new">新密码</Label>} required hint={PASSWORD_RULES_TEXT}>
            <Input
              id="ql-cp-new"
              type="password"
              value={newPassword}
              onChange={(_, d) => setNewPassword(d.value)}
              autoComplete="new-password"
            />
          </Field>
          <Field label={<Label htmlFor="ql-cp-confirm">确认新密码</Label>} required>
            <Input
              id="ql-cp-confirm"
              type="password"
              value={confirm}
              onChange={(_, d) => setConfirm(d.value)}
              autoComplete="new-password"
            />
          </Field>
          <Caption1 style={{ color: t.colorNeutralForeground3 }}>
            新密码长度至少 {PASSWORD_MIN_LENGTH} 位，且不能包含空格。
          </Caption1>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <Button appearance="primary" type="submit" disabled={busy || !user}>
              {busy ? '提交中…' : forced ? '确认修改并继续' : '保存新密码'}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
