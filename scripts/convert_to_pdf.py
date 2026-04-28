#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将Markdown设计报告转换为PDF格式"""

import sys
from pathlib import Path
import markdown
from weasyprint import HTML, CSS

def convert_md_to_pdf(md_path: str, pdf_path: str):
    """转换Markdown到PDF"""
    
    # 读取Markdown文件
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    # 将Markdown转换为HTML
    html_content = markdown.markdown(
        md_content,
        extensions=['tables', 'fenced_code', 'toc']
    )
    
    # 添加完整的HTML结构和样式
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: A4;
                margin: 2.5cm 2cm;
                @bottom-center {{
                    content: "page " counter(page) " / " counter(pages);
                    font-size: 10pt;
                    color: #666;
                }}
            }}
            
            body {{
                font-family: "Microsoft YaHei", "SimSun", Arial, sans-serif;
                font-size: 11pt;
                line-height: 1.6;
                color: #333;
            }}
            
            h1 {{
                font-size: 22pt;
                color: #1a5276;
                border-bottom: 3px solid #1a5276;
                padding-bottom: 8px;
                margin-top: 30px;
                margin-bottom: 20px;
                page-break-after: avoid;
            }}
            
            h2 {{
                font-size: 16pt;
                color: #2874a6;
                border-bottom: 2px solid #2874a6;
                padding-bottom: 6px;
                margin-top: 25px;
                margin-bottom: 15px;
                page-break-after: avoid;
            }}
            
            h3 {{
                font-size: 13pt;
                color: #2e86c1;
                margin-top: 20px;
                margin-bottom: 10px;
                page-break-after: avoid;
            }}
            
            h4 {{
                font-size: 12pt;
                color: #3498db;
                margin-top: 15px;
                margin-bottom: 8px;
            }}
            
            p {{
                margin: 8px 0;
                text-align: justify;
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 15px 0;
                page-break-inside: avoid;
            }}
            
            th {{
                background-color: #2874a6;
                color: white;
                padding: 8px;
                text-align: left;
                font-weight: bold;
                border: 1px solid #ddd;
            }}
            
            td {{
                padding: 6px 8px;
                border: 1px solid #ddd;
            }}
            
            tr:nth-child(even) {{
                background-color: #f8f9fa;
            }}
            
            tr:hover {{
                background-color: #e8f4f8;
            }}
            
            code {{
                background-color: #f4f4f4;
                padding: 2px 6px;
                border-radius: 3px;
                font-family: "Courier New", monospace;
                font-size: 10pt;
            }}
            
            pre {{
                background-color: #f8f9fa;
                padding: 12px;
                border-left: 4px solid #2874a6;
                overflow-x: auto;
                font-size: 9pt;
                page-break-inside: avoid;
            }}
            
            pre code {{
                background: none;
                padding: 0;
            }}
            
            ul, ol {{
                margin: 8px 0;
                padding-left: 25px;
            }}
            
            li {{
                margin: 4px 0;
            }}
            
            strong {{
                color: #1a5276;
            }}
            
            .warning {{
                background-color: #fff3cd;
                border-left: 4px solid #ffc107;
                padding: 10px;
                margin: 10px 0;
            }}
            
            hr {{
                border: none;
                border-top: 2px solid #ddd;
                margin: 20px 0;
            }}
            
            @media print {{
                h1, h2, h3 {{
                    page-break-after: avoid;
                }}
                table, pre {{
                    page-break-inside: avoid;
                }}
            }}
        </style>
    </head>
    <body>
        {html_content}
    </body>
    </html>
    """
    
    # 转换为PDF
    css = CSS(string="""
        @page {
            size: A4;
            margin: 2.5cm 2cm;
        }
    """)
    
    HTML(string=full_html).write_pdf(
        pdf_path,
        stylesheets=[css]
    )
    
    print(f"✓ PDF生成成功：{pdf_path}")

def main():
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
        convert_md_to_pdf(str(md_file), str(pdf_file))
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
