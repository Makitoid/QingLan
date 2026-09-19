import chroma from 'chroma-js';
import { useTheme } from '../appTheme';
import { useThemeMode } from '../context';

// 登录页专属背景，与站点背景图/透明度无关，只跟随品牌色与亮暗模式。
// 三颗光斑都从品牌色推导：只做 ±12° 色相微调与明度微调，保证主体色仍是站点品牌色。
const BLOBS = [
  { cls: 'ql-blob-1', weight: 1, tweak: (c: chroma.Color) => c },
  { cls: 'ql-blob-2', weight: 0.8, tweak: (c: chroma.Color) => c.set('hsl.h', '+12') },
  { cls: 'ql-blob-3', weight: 0.65, tweak: (c: chroma.Color) => c.set('hsl.h', '-12').brighten(0.5) },
];

export function LoginBackdrop() {
  const t = useTheme();
  const { isDark } = useThemeMode();

  // 暗色下同品牌色的明度更高，正好当黑底上的辉光；底色用中性背景与品牌色的混色，保证不透明
  const brand = t.colorBrandBackground;
  const wash = chroma.mix(t.colorNeutralBackground1, brand, isDark ? 0.24 : 0.16, 'lab').css();
  const opacity = isDark ? 0.42 : 0.4;

  return (
    <div
      aria-hidden
      className="ql-login-bg"
      style={{ background: `linear-gradient(160deg, ${t.colorNeutralBackground1} 0%, ${wash} 100%)` }}
    >
      <div className="ql-aurora">
        {BLOBS.map((blob) => (
          <div
            key={blob.cls}
            className={`ql-blob ${blob.cls}`}
            style={{
              opacity: opacity * blob.weight,
              backgroundImage: `radial-gradient(circle at 50% 50%, ${blob.tweak(chroma(brand)).css()} 0%, transparent 68%)`,
            }}
          />
        ))}
      </div>
    </div>
  );
}
