import { useNavigate } from 'react-router-dom';
import { Button, Text, tokens } from '@fluentui/react-components';
import { ErrorCircle24Regular } from '@fluentui/react-icons';

export function ForbiddenPage() {
  const navigate = useNavigate();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: tokens.spacingVerticalM, paddingBlock: tokens.spacingVerticalXXL }}>
      <ErrorCircle24Regular style={{ color: tokens.colorPaletteRedForeground1 }} />
      <Text as="h2" weight="semibold">403 · 无权访问</Text>
      <Text style={{ color: tokens.colorNeutralForeground3 }}>当前账号角色没有访问该页面的权限。</Text>
      <Button appearance="primary" onClick={() => navigate(-1)}>返回上一页</Button>
    </div>
  );
}
