import { UNIFIED_INITIAL_PASSWORD } from './credentialCsv';

/** PW-03：与后端 `config.PASSWORD_MIN_LENGTH` 一致。 */
export const PASSWORD_MIN_LENGTH = 8;

/** 与后端 `security.WEAK_PASSWORDS` 同表（比较时统一 `toLowerCase()`）。 */
const WEAK_PASSWORDS = new Set([
  'password', 'password1', 'password123', 'passw0rd', 'p@ssw0rd', 'p@ssword1',
  '12345678', '123456789', '1234567890', '1234567', '123456', '12345', '987654321',
  '11111111', '00000000', '88888888', '66666666', '11223344', '123123123',
  'qwerty', 'qwerty123', 'qwertyuiop', 'qazwsx', 'qazwsxedc', '1qaz2wsx',
  '1q2w3e4r', '1q2w3e4r5t', 'zxcvbnm', 'asdfghjkl', 'asdf1234', 'qwe123456',
  'abc123456', 'a1234567', 'a123456789', '123qweasd',
  'iloveyou', 'iloveyou123', 'woaini1314', 'woaini520', '5201314', '1314520',
  'admin123', 'admin888', 'admin123456', 'root1234', 'test1234', 'changeme',
  'letmein', 'welcome', 'welcome1', 'monkey123', 'dragon123', 'master123',
  'sunshine', 'princess', 'football', 'baseball', 'superman', 'trustno1',
  'secret123', 'shadow123', 'batman123', 'michael123', 'jordan123',
  'qinglan123', 'qinglan2026',
]);

const RULE_LETTER_AND_DIGIT = '密码必须同时包含字母和数字';
const RULE_FEW_CHARS = '密码不能只由少数几种字符重复组成';
const RULE_CONSECUTIVE = '密码不能使用连续字符';
const RULE_COMMON = '密码过于常见';

/** 连续（升/降）码点 ≥5 的串，与后端 `_has_consecutive_run` 同算法。 */
function hasConsecutiveRun(password: string, length = 5): boolean {
  let ascending = 1;
  let descending = 1;
  for (let index = 1; index < password.length; index += 1) {
    const delta = password.charCodeAt(index) - password.charCodeAt(index - 1);
    ascending = delta === 1 ? ascending + 1 : 1;
    descending = delta === -1 ? descending + 1 : 1;
    if (ascending >= length || descending >= length) return true;
  }
  return false;
}

interface PolicyContext {
  /** 登录名（学生即学号、教师即工号）。 */
  username: string;
  displayName: string;
  /** 改密时的旧密码；新建场景不传。 */
  oldPassword?: string;
}

/**
 * PW-03 的新密码规则（全角色、强制改密与自助改密同一套）：
 * ≥8 位、不含空格、不得等于用户名 / 姓名 / 旧密码 / 统一初始密码，
 * 且必须同时含字母与数字、不能只有少数几种字符、不能是连续串、不能是常见弱密码。
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
  if (!/[A-Za-z]/.test(next) || !/[0-9]/.test(next)) return RULE_LETTER_AND_DIGIT;
  if (new Set([...next]).size <= 2) return RULE_FEW_CHARS;
  if (hasConsecutiveRun(next)) return RULE_CONSECUTIVE;
  if (WEAK_PASSWORDS.has(next.toLowerCase())) return RULE_COMMON;
  return null;
}

/** 改密页/账号页共用的规则说明文案（不出现明文密码，走「统一初始密码」措辞）。 */
export const PASSWORD_RULES_TEXT = `至少 ${PASSWORD_MIN_LENGTH} 位；${RULE_LETTER_AND_DIGIT}；${RULE_FEW_CHARS}；${RULE_CONSECUTIVE}；${RULE_COMMON}；不能包含空格，也不能与学号/用户名、姓名、旧密码或统一初始密码相同。`;

