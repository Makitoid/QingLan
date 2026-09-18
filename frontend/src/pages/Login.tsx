import { useTheme } from '../appTheme';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Card,
  CardHeader,
  Field,
  Input,
  Label,
  MessageBar,
  MessageBarBody,
  Text,
  tokens,

} from '@fluentui/react-components';
import { setAuth } from '../api/client';
import { login } from '../api';
import { errMessage } from '../components/StateViews';
import { BackgroundLayers } from '../components/BackgroundLayers';
import { roleHome } from '../components/Guard';

export function LoginPage() {
  const t = useTheme();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError('请输入用户名和密码');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const resp = await login(username.trim(), password);
      setAuth(resp.token, resp.user);
      navigate(roleHome(resp.user.role), { replace: true });
    } catch (err) {
      setError(errMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <BackgroundLayers />
      <Card size="large" style={{ width: '400px', boxShadow: tokens.shadow16, padding: tokens.spacingHorizontalXXL }}>
        <CardHeader
          image={
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%' }}>
              <Text as="h1" size={800} weight="bold" style={{ color: t.colorBrandForeground1 }}>
                青蓝
              </Text>
              <Text size={200} style={{ color: t.colorNeutralForeground3 }}>
                QingLan · C 语言练习与测评平台
              </Text>
            </div>
          }
        />
        <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM, marginTop: tokens.spacingVerticalL }}>
          {error && (
            <MessageBar intent="error" style={{ borderRadius: tokens.borderRadiusMedium }}>
              <MessageBarBody>{error}</MessageBarBody>
            </MessageBar>
          )}
          <Field label={<Label htmlFor="ql-login-username">用户名</Label>}>
            <Input
              id="ql-login-username"
              value={username}
              onChange={(_, data) => setUsername(data.value)}
              placeholder="学生输入学号 / 教师输入工号"
              autoFocus
            />
          </Field>
          <Field label={<Label htmlFor="ql-login-password">密码</Label>}>
            <Input
              id="ql-login-password"
              type="password"
              value={password}
              onChange={(_, data) => setPassword(data.value)}
              placeholder="密码"
            />
          </Field>
          <Button appearance="primary" type="submit" disabled={busy} size="large">
            {busy ? '登录中…' : '登录'}
          </Button>
        </form>
      </Card>
    </div>
  );
}
