#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""使用纯Python生成PDF格式的设计报告"""

import sys
import re
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import markdown

def register_chinese_font():
    """注册中文字体"""
    # 尝试使用Windows系统自带的中文字体
    font_paths = [
        (r"C:\Windows\Fonts\msyh.ttc", "Microsoft YaHei"),  # 微软雅黑
        (r"C:\Windows\Fonts\simhei.ttf", "SimHei"),  # 黑体
        (r"C:\Windows\Fonts\simsun.ttc", "SimSun"),  # 宋体
    ]
    
    for font_path, font_name in font_paths:
        if Path(font_path).exists():
            try:
                # 对于TTC文件，需要指定字体索引
                if font_path.endswith('.ttc'):
                    pdfmetrics.registerFont(TTFont('ChineseFont', font_path, subfontIndex=0))
                else:
                    pdfmetrics.registerFont(TTFont('ChineseFont', font_path))
                print(f"✓ 已加载字体：{font_path} ({font_name})")
                return 'ChineseFont'
            except Exception as e:
                print(f"  尝试 {font_name} 失败: {e}")
                continue
    
    print("⚠ 未找到中文字体，将使用默认字体")
    return 'Helvetica'

def parse_markdown_table(md_text):
    """从Markdown中提取表格"""
    tables = []
    lines = md_text.split('\n')
    current_table = []
    in_table = False
    
    for line in lines:
        if line.strip().startswith('|'):
            current_table.append(line.strip())
            in_table = True
        else:
            if current_table and in_table:
                tables.append(current_table)
                current_table = []
                in_table = False
    
    if current_table:
        tables.append(current_table)
    
    return tables

def markdown_to_flowables(md_content, font_name='Helvetica'):
    """将Markdown内容转换为reportlab流对象"""
    flowables = []
    
    # 设置样式
    styles = getSampleStyleSheet()
    
    # 自定义样式
    styles.add(ParagraphStyle(
        name='CustomH1',
        parent=styles['Title'],
        fontName=font_name,
        fontSize=22,
        textColor=HexColor('#1a5276'),
        spaceAfter=20,
        spaceBefore=30,
        alignment=TA_LEFT,
        borderWidth=2,
        borderColor=HexColor('#1a5276'),
        borderPadding=5
    ))
    
    styles.add(ParagraphStyle(
        name='CustomH2',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=16,
        textColor=HexColor('#2874a6'),
        spaceAfter=12,
        spaceBefore=20,
        borderWidth=1,
        borderColor=HexColor('#2874a6'),
        borderPadding=3
    ))
    
    styles.add(ParagraphStyle(
        name='CustomH3',
        parent=styles['Heading3'],
        fontName=font_name,
        fontSize=13,
        textColor=HexColor('#2e86c1'),
        spaceAfter=10,
        spaceBefore=15
    ))
    
    styles.add(ParagraphStyle(
        name='CustomBody',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=11,
        leading=18,
        alignment=TA_JUSTIFY,
        spaceAfter=8
    ))
    
    styles.add(ParagraphStyle(
        name='CustomBullet',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=11,
        leading=16,
        leftIndent=20,
        spaceAfter=4
    ))
    
    styles.add(ParagraphStyle(
        name='CustomCode',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=9,
        leading=14,
        leftIndent=20,
        rightIndent=10,
        spaceAfter=8,
        textColor=HexColor('#333333'),
        backColor=HexColor('#f8f9fa')
    ))
    
    # 按行处理
    lines = md_content.split('\n')
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        # H1标题
        if line.startswith('# ') and not line.startswith('##'):
            text = line[2:].strip()
            flowables.append(Paragraph(text, styles['CustomH1']))
            flowables.append(Spacer(1, 6))
            # 添加横线
            flowables.append(HRFlowable(width="100%", thickness=2, color=HexColor('#1a5276')))
        
        # H2标题
        elif line.startswith('## ') and not line.startswith('###'):
            text = line[3:].strip()
            flowables.append(Paragraph(text, styles['CustomH2']))
            flowables.append(Spacer(1, 4))
        
        # H3标题
        elif line.startswith('### '):
            text = line[4:].strip()
            flowables.append(Paragraph(text, styles['CustomH3']))
        
        # 分隔线
        elif line.startswith('---') or line.startswith('***'):
            flowables.append(HRFlowable(width="100%", thickness=1, color=HexColor('#cccccc')))
        
        # 表格
        elif line.startswith('|'):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            
            # 解析表格
            data = []
            for row_line in table_lines:
                if '---' in row_line:  # 跳过分隔行
                    continue
                cells = [cell.strip() for cell in row_line.split('|')[1:-1]]
                if cells:
                    data.append(cells)
            
            if data:
                # 创建表格
                t = Table(data, colWidths=[200, 200, 150])
                
                # 构建表格样式列表
                table_styles = [
                    ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2874a6')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), white),
                    ('FONTNAME', (0, 0), (-1, -1), font_name),  # 所有单元格都使用中文字体
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('FONTSIZE', (0, 1), (-1, -1), 9),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
                    ('BACKGROUND', (0, 1), (-1, -1), white),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')]),
                    ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#dddddd')),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 6),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ]
                
                t.setStyle(TableStyle(table_styles))
                flowables.append(t)
                flowables.append(Spacer(1, 8))
            continue  # 已经在while循环中处理了
        
        # 代码块
        elif line.startswith('```'):
            code_lines = []
            i += 1  # 跳过开始的```
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            
            code_text = '\n'.join(code_lines)
            # 简化代码块显示
            for code_line in code_lines:
                flowables.append(Paragraph(code_line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'), styles['CustomCode']))
        
        # 列表项
        elif line.startswith('- ') or line.startswith('* '):
            text = line[2:].strip()
            bullet_text = "• " + text
            flowables.append(Paragraph(bullet_text, styles['CustomBullet']))
        
        # 普通段落
        elif line and len(line) > 10:
            # 处理粗体
            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', line)
            # 处理斜体
            text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
            # 处理行内代码
            text = re.sub(r'`(.+?)`', r'<font face="Courier" size="9">\1</font>', text)
            
            flowables.append(Paragraph(text, styles['CustomBody']))
        
        # 空行
        elif not line:
            flowables.append(Spacer(1, 4))
        
        i += 1
    
    return flowables

def create_pdf(md_path: str, pdf_path: str):
    """创建PDF文件"""
    
    # 注册中文字体
    font_name = register_chinese_font()
    
    # 读取Markdown
    with open(md_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    # 创建PDF文档
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2.5*cm,
        bottomMargin=2*cm
    )
    
    # 转换Markdown为流对象
    flowables = markdown_to_flowables(md_content, font_name)
    
    # 页脚
    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont(font_name, 9)
        canvas.drawRightString(A4[0] - 2*cm, 1.5*cm, f"第 {doc.page} 页")
        canvas.restoreState()
    
    # 构建PDF
    doc.build(flowables, onFirstPage=add_page_number, onLaterPages=add_page_number)
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
    print("35kV变电站设计报告 - PDF生成器")
    print("=" * 80)
    print(f"\n输入文件：{md_file}")
    print(f"输出文件：{pdf_file}")
    print("\n正在生成PDF...")
    
    try:
        create_pdf(str(md_file), str(pdf_file))
        print("\n" + "=" * 80)
        print("PDF生成完成！")
        print("=" * 80)
    except Exception as e:
        print(f"\n✗ 生成失败：{str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
