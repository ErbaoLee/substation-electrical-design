#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""使用md2pdf将Markdown转换为PDF"""

import sys
from pathlib import Path

def main():
    try:
        from md2pdf import md2pdf
    except ImportError:
        print("正在安装 md2pdf...")
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'md2pdf'])
        from md2pdf import md2pdf
    
    # 文件路径
    base_dir = Path(__file__).parent.parent
    md_file = base_dir / "design_report_35kv.md"
    pdf_file = base_dir / "design_report_35kv.pdf"
    
    if not md_file.exists():
        print(f"✗ 错误：找不到Markdown文件 {md_file}")
        sys.exit(1)
    
    print("=" * 80)
    print("Markdown转PDF转换器")
    print("=" * 80)
    print(f"\n输入文件：{md_file}")
    print(f"输出文件：{pdf_file}")
    print("\n正在转换...")
    
    try:
        md2pdf(
            str(pdf_file),
            md_file_path=str(md_file),
            title="35kV变电站电气设计报告",
            base_url=str(md_file.parent)
        )
        print(f"\n✓ PDF生成成功：{pdf_file}")
        print("\n" + "=" * 80)
        print("转换完成！")
        print("=" * 80)
    except Exception as e:
        print(f"\n✗ 转换失败：{str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
