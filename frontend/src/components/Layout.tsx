import { useTheme } from '../appTheme';
import chroma from 'chroma-js';
import { useEffect } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Avatar,
  Button,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Tab,
  TabList,
  Text,
  tokens,

} from '@fluentui/react-components';
import { Settings24Regular, SignOut24Regular, WeatherMoon24Regular, WeatherSunny24Regular } from '@fluentui/react-icons';
import { clearAuth, getStoredUser } from '../api/client';
import type { Role } from '../api/types';
import { useSettings, useThemeMode } from '../context';
import { BackgroundLayers, resolveBgUrl } from './BackgroundLayers';
import { roleHome } from './Guard';

const NAV_LINKS: Record<Role, { to: string; label: string }[]> = {
  student: [{ to: '/student/assignments', label: '我的场次' }],
  teacher: [
    { to: '/teacher/assignments', label: '发布' },
    { to: '/teacher/problems', label: '题库' },
    { to: '/teacher/students', label: '学生' },
  ],
  admin: [
    { to: '/admin/teachers', label: '教师管理' },
    { to: '/admin/students', label: '学生管理' },
    { to: '/admin/settings', label: '主题设置' },
  ],
};

export function Layout() {
  const t = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const { isDark, setMode } = useThemeMode();
  const { effective } = useSettings();
  const user = getStoredUser();

  const acrylicBg = chroma(t.colorNeutralBackground1).alpha(0.72).css();
  const bgUrl = resolveBgUrl(effective, isDark);

  // 选区与卡片毛玻璃的半透明色写在 :root，Dialog / Menu 等 portal 内容才能一并取到。
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty('--ql-surface', acrylicBg);
    root.style.setProperty('--ql-selection', chroma(t.colorBrandBackground).alpha(0.28).css());
  }, [acrylicBg, t.colorBrandBackground]);

  const links = user ? NAV_LINKS[user.role] : [];
  const selectedTab =
    links.find((link) => location.pathname === link.to || location.pathname.startsWith(`${link.to}/`))?.to ?? '';

  const handleLogout = () => {
    clearAuth();
    navigate('/login', { replace: true });
  };

  return (
    <div className={bgUrl ? 'ql-has-bg' : undefined} style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <BackgroundLayers />
      <header
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          display: 'flex',
          alignItems: 'center',
          gap: tokens.spacingHorizontalL,
          padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalXXL}`,
          backgroundColor: acrylicBg,
          backdropFilter: 'blur(20px) saturate(150%)',
          WebkitBackdropFilter: 'blur(20px) saturate(150%)',
          borderBottom: `1px solid ${t.colorNeutralStroke3}`,
        }}
      >
        <NavLink to={user ? roleHome(user.role) : '/login'} style={{ textDecoration: 'none', color: 'inherit' }}>
          <Text as="h1" weight="bold" size={500} style={{ color: t.colorBrandForeground1 }}>
            青蓝
          </Text>
        </NavLink>

        <TabList
          selectedValue={selectedTab}
          onTabSelect={(_, data) => navigate(data.value as string)}
          style={{ marginLeft: tokens.spacingHorizontalXL }}
        >
          {links.map((link) => (
            <Tab key={link.to} value={link.to}>
              {link.label}
            </Tab>
          ))}
        </TabList>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: tokens.spacingHorizontalS }}>
          <Button
            appearance="subtle"
            icon={isDark ? <WeatherSunny24Regular /> : <WeatherMoon24Regular />}
            title={isDark ? '切换到亮色模式' : '切换到暗色模式'}
            onClick={() => setMode(isDark ? 'light' : 'dark')}
          />
          {user && (
            <Menu>
              <MenuTrigger>
                <Button
                  appearance="subtle"
                  icon={<Avatar size={28} name={user.display_name} />}
                  style={{ gap: tokens.spacingHorizontalMNudge }}
                >
                  {user.display_name}
                </Button>
              </MenuTrigger>
              <MenuPopover>
                <MenuList>
                  <Text size={200} style={{ color: t.colorNeutralForeground3, paddingInline: tokens.spacingHorizontalSNudge }}>
                    {user.username} · {user.role === 'admin' ? '管理员' : user.role === 'teacher' ? '教师' : '学生'}
                  </Text>
                  <MenuItem icon={<Settings24Regular />} onClick={() => navigate('/account')}>
                    账号设置
                  </MenuItem>
                  <MenuItem icon={<SignOut24Regular />} onClick={handleLogout}>
                    退出登录
                  </MenuItem>
                </MenuList>
              </MenuPopover>
            </Menu>
          )}
        </div>
      </header>

      <main
        style={{
          flex: 1,
          width: '100%',
          maxWidth: '1200px',
          margin: '0 auto',
          padding: `${tokens.spacingVerticalL} ${tokens.spacingHorizontalXXL} ${tokens.spacingVerticalXXL}`,
        }}
      >
        <Outlet />
      </main>

      <footer style={{ padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalXXL}`, textAlign: 'center' }}>
        <Text size={200} style={{ color: t.colorNeutralForeground4 }}>
          青蓝 QingLan · C 语言练习与测评平台
        </Text>
      </footer>
    </div>
  );
}
