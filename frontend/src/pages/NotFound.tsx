import { useTheme } from '../appTheme';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Text, makeStyles, tokens } from '@fluentui/react-components';
import { CompassNorthwestRegular } from '@fluentui/react-icons';
import { getStoredUser } from '../api/client';
import { roleHome } from '../components/Guard';

// 只放布局与间距；颜色一律走主题令牌（见下方 useTheme），保证暗色模式跟随。
const useStyles = makeStyles({
  stage: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    // 减去 Layout 的 header / footer / main 内边距，让卡片在可视区真正垂直居中。
    minHeight: 'calc(100vh - 15rem)',
    paddingBlock: tokens.spacingVerticalXXL,
    paddingInline: tokens.spacingHorizontalM,
  },
  card: {
    // 三段式：上下两条 1fr 轨道等分剩余空间，404 就精确落在卡片的垂直中线上。
    // 罗盘与文案分别贴到各自轨道的内侧边缘，空隙全部推到卡片上下两端。
    display: 'grid',
    gridTemplateRows: '1fr auto 1fr',
    justifyItems: 'center',
    // Card 自带 12px gap，会和下面两条 8px 外边距叠成 20px，这里显式清零由边距控制间距。
    gap: 0,
    width: '100%',
    maxWidth: '560px',
    minHeight: 'min(520px, calc(100vh - 16rem))',
    padding: `${tokens.spacingVerticalXXXL} ${tokens.spacingHorizontalXXXL}`,
    textAlign: 'center',
    boxShadow: tokens.shadow16,
    // 不要设 backgroundColor：否则会盖掉 `.ql-has-bg .fui-Card` 的毛玻璃。
  },
  above: { alignSelf: 'end', marginBottom: tokens.spacingVerticalS },
  below: {
    alignSelf: 'start',
    marginTop: tokens.spacingVerticalS,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: tokens.spacingVerticalL,
  },
  badge: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '96px',
    height: '96px',
    // 可变尺寸图标：字号即渲染尺寸，比缩放 28 号字稿更清晰。
    fontSize: '48px',
    borderRadius: tokens.borderRadiusCircular,
  },
  code: {
    margin: '0',
    fontSize: 'clamp(3.5rem, 12vw, 6rem)',
    lineHeight: 1,
    letterSpacing: '-0.04em',
  },
  copy: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: tokens.spacingVerticalS,
  },
  // Fluent Text 自带 textAlign:'start'，卡片上的 center 传不进来，必须在 Text 上显式覆盖。
  title: { margin: '0', textAlign: 'center' },
  desc: { textAlign: 'center' },
  actions: {
    display: 'flex',
    flexWrap: 'wrap',
    justifyContent: 'center',
    gap: tokens.spacingHorizontalS,
  },
});

/**
 * 404 居中式提示页：与 Forbidden / Login 同类，按文档约定不套 PageHeader。
 *
 * 毛玻璃不需要在这里写任何颜色：本页由 App.tsx 的 catch-all 路由（`path="*"`）渲染在
 * `<Layout />` 之内，Layout 解析到站点背景图时给根节点挂 `.ql-has-bg`，index.css 的
 * `.ql-has-bg .fui-Card` 用 `--ql-surface`（Layout 按当前主题写进 :root 的
 * `colorNeutralBackground1` 半透明色）+ `backdrop-filter`（半径以 index.css 为准）
 * 把这张 Card 直接变成亚克力；没有背景图时该规则不命中，Card 保持默认不透明底色。
 * 暗色模式下主题令牌与 `--ql-surface` 一起重算，两种模式都成立。
 */
export function NotFoundPage() {
  const t = useTheme();
  const styles = useStyles();
  const navigate = useNavigate();
  const user = getStoredUser();
  // 直接输入 / 刷新一个不存在的地址时没有历史记录，「返回上一页」无处可去。
  const canGoBack = window.history.length > 1;

  return (
    <div className={styles.stage}>
      <Card className={styles.card}>
        <div className={styles.above}>
          <div className={styles.badge} style={{ backgroundColor: t.colorBrandBackground2, color: t.colorBrandForeground1 }}>
            <CompassNorthwestRegular aria-hidden />
          </div>
        </div>

        <Text as="p" size={1000} weight="bold" className={styles.code} style={{ color: t.colorBrandForeground1 }}>
          404
        </Text>

        <div className={styles.below}>
          <div className={styles.copy}>
            <Text as="h2" size={600} weight="semibold" className={styles.title}>
              页面不存在
            </Text>
            <Text size={300} className={styles.desc} style={{ color: t.colorNeutralForeground3 }}>
              地址可能拼写有误，或这个页面已经下架。
            </Text>
          </div>

          <div className={styles.actions}>
            <Button appearance="primary" onClick={() => navigate(user ? roleHome(user.role) : '/')}>
              返回首页
            </Button>
            {canGoBack && (
              <Button appearance="secondary" onClick={() => navigate(-1)}>
                返回上一页
              </Button>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
