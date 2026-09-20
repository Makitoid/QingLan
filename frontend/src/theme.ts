import chroma from 'chroma-js';
import {
  createLightTheme,
  createDarkTheme,
  webLightTheme,
  webDarkTheme,
  type Theme,
  type BrandVariants,
} from '@fluentui/react-components';
import { getSettings } from './api';
import type { SiteSettings } from './api/types';

const BRAND_STEPS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160] as const;

export function createBrandRamp(brandColor: string): BrandVariants {
  const base = chroma(brandColor);
  const lightEnd = chroma.mix(base, 'white', 0.94, 'lab');
  const darkEnd = chroma.mix(base, 'black', 0.78, 'lab');
  // Fluent 约定 step 10 最深、step 160 最浅，因此插值必须从暗端走向亮端。
  const brandPos = 70 / 150;
  const scale = chroma
    .scale([darkEnd.hex(), base.hex(), lightEnd.hex()])
    .domain([0, brandPos, 1])
    .mode('lab');
  const ramp = {} as BrandVariants;
  for (const step of BRAND_STEPS) {
    const t = (step - 10) / 150;
    ramp[String(step) as unknown as keyof BrandVariants] = scale(t).hex();
  }
  return ramp;
}

function buildTheme(kind: 'light' | 'dark', brandColor: string | null): Theme {
  const fallback = kind === 'light' ? webLightTheme : webDarkTheme;
  if (!brandColor) return fallback;
  try {
    const ramp = createBrandRamp(brandColor);
    return kind === 'light' ? createLightTheme(ramp) : createDarkTheme(ramp);
  } catch {
    return fallback;
  }
}

export function buildThemes(brandColor: string | null, darkBrandColor?: string | null): { light: Theme; dark: Theme } {
  return {
    light: buildTheme('light', brandColor),
    dark: buildTheme('dark', darkBrandColor ?? brandColor),
  };
}

/**
 * 亮 / 暗各自用哪张品牌色。暗色专属色只在「开启亮暗分图且暗图已上传」时生效，
 * 与 BackgroundLayers 的 resolveBgUrl 选图规则保持一致，否则回退到亮色品牌色。
 */
export function resolveBrandColors(effective: SiteSettings | null): { light: string | null; dark: string | null } {
  const darkApplies = Boolean(effective?.bg_dual && effective.bg_image_url_dark);
  return {
    light: effective?.brand_color ?? null,
    dark: darkApplies ? (effective?.brand_color_dark ?? null) : null,
  };
}

export async function fetchSiteSettings(): Promise<SiteSettings | null> {
  try {
    return await getSettings();
  } catch {
    return null;
  }
}

/* ---------- dark mode preference ---------- */

export type ThemeMode = 'light' | 'dark' | 'system';

const MODE_KEY = 'qinglan-theme-mode';

export function getStoredThemeMode(): ThemeMode {
  const v = localStorage.getItem(MODE_KEY);
  return v === 'light' || v === 'dark' ? v : 'system';
}

export function storeThemeMode(mode: ThemeMode): void {
  localStorage.setItem(MODE_KEY, mode);
}

export function systemPrefersDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

export function resolveIsDark(mode: ThemeMode): boolean {
  return mode === 'system' ? systemPrefersDark() : mode === 'dark';
}
