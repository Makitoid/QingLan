import { Link } from 'react-router-dom';
import { Text, tokens } from '@fluentui/react-components';

export function NotFoundPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: tokens.spacingVerticalM, paddingBlock: tokens.spacingVerticalXXL }}>
      <Text as="h2" weight="semibold">404 · 页面不存在</Text>
      <Link to="/" style={{ color: tokens.colorBrandForeground1 }}>返回首页</Link>
    </div>
  );
}
