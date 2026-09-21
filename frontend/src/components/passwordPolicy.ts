import { UNIFIED_INITIAL_PASSWORD } from './credentialCsv';

/** PW-03：与后端 `config.PASSWORD_MIN_LENGTH` 一致。 */
export const PASSWORD_MIN_LENGTH = 8;

interface PolicyContext {
  /** 登录名（学生即学号、教师即工号）。 */
  username: string;
  displayName: string;
  /** 改密时的旧密码；新建场景不传。 */
  oldPassword?: string;
}

/**
 * PW-03 的新密码规则（全角色、强制改密与自助改密同一套）：
 * ≥8 位、不含空格、不得等于用户名 / 姓名 / 旧密码 / 统一初始密码。
 *
 * 这只是**前端预校验**，文案与后端 `security.validate_new_password()` 逐字对齐，
 * 真正的判定仍在后端（422 PASSWORD_POLICY 的 message 会原样显示出来）。
 *
 * @returns 第一条不满足的提示；全部通过返回 null。
 */
export function validateNewPassword(next: string, ctx: PolicyContext): string | null {
  if (next.length < PASSWORD_MIN_LENGTH) return `密码长度至少 ${PASSWORD_MIN_LENGTH} 位`;
  // 后端用 `any(ch.isspace())`，中文全角空格等也算，这里用 \s 覆盖不到全角空格，故逐字符判定。
  if ([...next].some((ch) => /\s/.test(ch))) return '密码不能包含空格';
  const forbidden = [ctx.username, ctx.displayName, UNIFIED_INITIAL_PASSWORD, ctx.oldPassword].filter(
    (x): x is string => Boolean(x),
  );
  if (forbidden.includes(next)) return '密码不能与学号/用户名、姓名、旧密码或初始密码相同';
  return null;
}

/** 改密页/账号页共用的规则说明文案（不出现明文密码，走「统一初始密码」措辞）。 */
export const PASSWORD_RULES_TEXT = `至少 ${PASSWORD_MIN_LENGTH} 位，不能包含空格，也不能与学号/用户名、姓名、旧密码或统一初始密码相同。`;
