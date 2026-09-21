import dayjs from 'dayjs';
import type { StudentItem, TempCredential } from '../api/types';
import { fmtTimeWithSeconds } from './time';

/**
 * PW-01 / 附录 A `password.default_initial`：全站统一初始密码。
 *
 * 它只用于**拼装凭证 CSV**（PW-09 的「导出初始密码表」列值）与改密前的本地预校验，
 * 界面文案一律写「统一初始密码」，不打印明文——避免把口令散落在各处 UI 文本里。
 * 真正的判定与下发在后端（`config.DEFAULT_INITIAL_PASSWORD`）。
 */
export const UNIFIED_INITIAL_PASSWORD = '12345678';

/** CSV 单元格：统一加引号，内部引号按 RFC4180 翻倍转义（`"` → `""`）。 */
function cell(value: string | number): string {
  return `"${String(value).replace(/"/g, '""')}"`;
}

/** UTF-8 BOM：缺了它 Excel 双击打开会按本地代码页解码，中文列头变乱码。用码点写死，别用肉眼看不见的字面量。 */
const BOM = String.fromCharCode(0xfeff);

/** 有效期列：`expires_at` 为 UTC 串，展示转本地；null = 不过期（PW-05 的统一/初始密码）。 */
export function expiryLabel(expiresAt: string | null): string {
  return expiresAt ? fmtTimeWithSeconds(expiresAt) : '不过期';
}

/**
 * PW-09：把重置响应的 JSON 明细拼成 CSV 文本（学号 / 姓名 / 临时密码 / 有效期）。
 *
 * 必须是**前端用响应 JSON 拼装**：受 JWT 保护的接口不能走 `<a href>` 直链（坑 22），
 * 而这里的数据本来就是响应体里已有的 JSON，连请求都不必再发。
 */
export function buildCredentialCsv(rows: TempCredential[], passwordHeader = '临时密码'): string {
  const header = ['学号', '姓名', passwordHeader, '有效期'].map(cell).join(',');
  const lines = rows.map((row) =>
    [row.username, row.display_name, row.temp_password, expiryLabel(row.expires_at)].map(cell).join(','),
  );
  return [header, ...lines].join('\r\n');
}

/** PW-09 ②：学生列表的「导出初始密码表」——把勾选的学生伪装成凭证明细，密码列固定统一初始密码。 */
export function initialPasswordRows(students: StudentItem[]): TempCredential[] {
  return students.map((s) => ({
    student_id: s.id,
    username: s.username,
    display_name: s.display_name,
    temp_password: UNIFIED_INITIAL_PASSWORD,
    expires_at: null,
  }));
}

/**
 * 以 Blob 落盘（不是 `<a href>` 直链）。带 UTF-8 BOM，否则 Excel 打开中文列头会乱码。
 */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([BOM + csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  // 立刻 revoke 会让部分浏览器（Firefox）拿不到数据，留一个短延时（同 downloadBlob 的约定）。
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function downloadCredentialCsv(rows: TempCredential[], prefix: string, passwordHeader?: string): void {
  downloadCsv(`${prefix}-${dayjs().format('YYYYMMDD-HHmm')}.csv`, buildCredentialCsv(rows, passwordHeader));
}

/** 复制凭证文本：优先异步 Clipboard API，非安全上下文（http 局域网直连）回退 execCommand。 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // 落到下面的兜底实现
  }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}

/** 一行凭证的可读文本，用于「复制」。 */
export function formatCredential(row: TempCredential): string {
  return `${row.display_name}（${row.username}） ${row.temp_password}　有效期：${expiryLabel(row.expires_at)}`;
}

/** 把整批凭证拼成可粘贴给别人的纯文本。 */
export function formatCredentials(rows: TempCredential[]): string {
  return rows.map(formatCredential).join('\n');
}
