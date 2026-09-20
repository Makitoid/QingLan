import { makeStyles, tokens } from '@fluentui/react-components';

/**
 * 危险操作按钮（删除确认等）：固定红系，不跟随品牌色。
 * 基准色用红色令牌（两主题同值 #d13438），hover/active 用 color-mix 在基准上加深，
 * 避免亮/暗主题各配一套 hover 色。
 */
export const useDangerStyles = makeStyles({
  solid: {
    backgroundColor: tokens.colorPaletteRedBackground3,
    color: tokens.colorNeutralForegroundOnBrand,
    ':hover': {
      backgroundColor: `color-mix(in srgb, ${tokens.colorPaletteRedBackground3} 88%, black)`,
    },
    ':hover:active': {
      backgroundColor: `color-mix(in srgb, ${tokens.colorPaletteRedBackground3} 76%, black)`,
    },
  },
  outline: {
    backgroundColor: tokens.colorTransparentBackground,
    borderTopColor: tokens.colorPaletteRedBorder2,
    borderRightColor: tokens.colorPaletteRedBorder2,
    borderBottomColor: tokens.colorPaletteRedBorder2,
    borderLeftColor: tokens.colorPaletteRedBorder2,
    color: tokens.colorPaletteRedForeground1,
    ':hover': {
      backgroundColor: tokens.colorPaletteRedBackground1,
    },
  },
});
