import { useTheme } from '../appTheme';
import { useSettings, useThemeMode } from '../context';
import type { SiteSettings } from '../api/types';

/** 亮暗独立背景关闭、或暗色槽位为空时，回退到主背景图；透明度为 0 等同于纯色背景。 */
export function resolveBgUrl(effective: SiteSettings | null, isDark: boolean): string | null {
  if (!effective?.bg_opacity) return null;
  return (isDark && effective.bg_dual && effective.bg_image_url_dark) || effective.bg_image_url || null;
}

export function BackgroundLayers() {
  const { effective } = useSettings();
  const { isDark } = useThemeMode();
  const t = useTheme();
  const url = resolveBgUrl(effective, isDark);
  const hasImage = Boolean(url);
  return (
    <>
      {url && (
        <div
          aria-hidden
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: -2,
            backgroundImage: `url("${url}")`,
            backgroundSize: 'cover',
            backgroundPosition: 'center',
            opacity: effective?.bg_opacity,
            pointerEvents: 'none',
          }}
        />
      )}
      <div
        aria-hidden
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: -1,
          pointerEvents: 'none',
          background: `linear-gradient(135deg, ${t.colorNeutralBackground1} 0%, ${t.colorNeutralBackground3} 100%)`,
          opacity: hasImage ? 0.72 : 1,
        }}
      />
    </>
  );
}
