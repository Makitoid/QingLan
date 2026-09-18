import { useTheme } from '../appTheme';

import { useSettings } from '../context';

export function BackgroundLayers() {
  const { effective } = useSettings();
  const t = useTheme();
  const hasImage = Boolean(effective?.bg_image_url);
  return (
    <>
      {effective?.bg_image_url && (
        <div
          aria-hidden
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: -2,
            backgroundImage: `url("${effective.bg_image_url}")`,
            backgroundSize: 'cover',
            backgroundPosition: 'center',
            opacity: effective.bg_opacity,
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
