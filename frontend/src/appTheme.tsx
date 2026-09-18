import { createContext, useContext } from 'react';
import type { Theme } from '@fluentui/react-components';

const AppThemeContext = createContext<Theme | null>(null);

export const AppThemeProvider = AppThemeContext.Provider;

export function useTheme(): Theme {
  const t = useContext(AppThemeContext);
  if (!t) throw new Error('useTheme must be used within AppThemeProvider');
  return t;
}
