import { useSearchParams } from 'react-router-dom';

/**
 * 来源感知返回：读当前 URL 上的 `?from=` 作为返回目标。
 *
 * HashRouter 下查询串位于 `#` 之内（`/#/teacher/problems/5/view?from=…`），
 * `useSearchParams` 解析的正是这一段，所以能正常取值。
 *
 * 只接受以 `/` 开头的站内路径，其余值（外链、脏数据）一律丢弃并回退到 fallback。
 */
export function useRouteFrom(fallback: string): { from: string | null; backTo: string } {
  const [params] = useSearchParams();
  const raw = params.get('from');
  const from = raw !== null && raw.startsWith('/') ? raw : null;
  return { from, backTo: from ?? fallback };
}
