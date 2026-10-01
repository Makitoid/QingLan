import { useRef } from 'react';
import {
  Button,
  Menu,
  MenuDivider,
  MenuGroup,
  MenuGroupHeader,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  Spinner,
} from '@fluentui/react-components';
import {
  ArrowBidirectionalLeftRight24Regular,
  ArrowExportUp24Regular,
  ArrowUpload24Regular,
} from '@fluentui/react-icons';

/**
 * 「导入/导出」合并入口（0.4.1 F2）：一个按钮，下拉里选导入还是导出格式。
 *
 * 文件选择框由本组件持有，父组件只拿到 `File`——导入的进度与结果提示
 * （MessageBar）留在页面上，两处不重复实现。
 */
export function ImportExportMenu(props: {
  /** 实体名，用于菜单项文案（学生 / 教师）。 */
  entity: string;
  /** 菜单顶部的模板说明，如「四列：学号｜姓名｜组别｜教师」。 */
  importHint: string;
  /** 传给文件选择框的后缀白名单。 */
  accept?: string;
  busy?: boolean;
  exporting?: boolean;
  onImportFile: (file: File) => void;
  onExport: (format: 'xlsx' | 'csv') => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const { entity, importHint, accept = '.xlsx', busy = false, exporting = false, onImportFile, onExport } = props;

  return (
    <>
      <Menu positioning="below-end">
        <MenuTrigger disableButtonEnhancement>
          <Button
            appearance="secondary"
            icon={exporting ? <Spinner size="tiny" /> : <ArrowBidirectionalLeftRight24Regular />}
            disabled={busy}
          >
            导入/导出
          </Button>
        </MenuTrigger>
        <MenuPopover>
          <MenuList>
            <MenuGroup>
              <MenuGroupHeader>导入（{importHint}）</MenuGroupHeader>
              <MenuItem icon={<ArrowUpload24Regular />} onClick={() => fileRef.current?.click()}>
                导入{entity}
              </MenuItem>
            </MenuGroup>
            <MenuDivider />
            <MenuGroup>
              <MenuGroupHeader>导出（与当前筛选同口径）</MenuGroupHeader>
              <MenuItem icon={<ArrowExportUp24Regular />} disabled={busy} onClick={() => onExport('xlsx')}>
                导出 Excel
              </MenuItem>
              <MenuItem icon={<ArrowExportUp24Regular />} disabled={busy} onClick={() => onExport('csv')}>
                导出 CSV
              </MenuItem>
            </MenuGroup>
          </MenuList>
        </MenuPopover>
      </Menu>
      <input
        ref={fileRef}
        type="file"
        accept={accept}
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          // 立刻清空：否则连续选同一个文件时 change 不再派发
          e.target.value = '';
          if (file) onImportFile(file);
        }}
      />
    </>
  );
}
