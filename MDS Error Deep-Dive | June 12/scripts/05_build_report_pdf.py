import json, os, fitz, base64
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                 Spacer, Image as RLImage, PageBreak, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from PIL import Image as PILImage
import io

results = json.load(open('/tmp/sample_25_classified.json'))

CAT_COLORS = {
    'A': colors.HexColor('#2E7D32'),   # green  — menu
    'B': colors.HexColor('#1565C0'),   # blue   — reference/instructions
    'C': colors.HexColor('#F57C00'),   # orange — logo
    'D': colors.HexColor('#6A1B9A'),   # purple — food photo
    'E': colors.HexColor('#C62828'),   # red    — irrelevant
}
CAT_BG = {
    'A': colors.HexColor('#E8F5E9'),
    'B': colors.HexColor('#E3F2FD'),
    'C': colors.HexColor('#FFF3E0'),
    'D': colors.HexColor('#F3E5F5'),
    'E': colors.HexColor('#FFEBEE'),
}

def pdf_page_to_pil(path, dpi=100):
    doc = fitz.open(path)
    page = doc[0]
    pix = page.get_pixmap(dpi=dpi)
    img = PILImage.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    return img

def file_to_thumbnail(local_file, max_w=160, max_h=130):
    ext = local_file.rsplit('.', 1)[-1].lower()
    try:
        if ext == 'pdf':
            img = pdf_page_to_pil(local_file, dpi=90)
        else:
            img = PILImage.open(local_file).convert('RGB')
        img.thumbnail((max_w * 4, max_h * 4), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85)
        buf.seek(0)
        return buf
    except Exception as e:
        return None

OUT = '/Users/rithesh.nanda/Documents/mds-error-deep-dive-june12/output/MDS_Error_Image_Review_June12.pdf'

doc = SimpleDocTemplate(OUT, pagesize=A4,
                         leftMargin=12*mm, rightMargin=12*mm,
                         topMargin=14*mm, bottomMargin=12*mm)

styles = getSampleStyleSheet()
title_style = ParagraphStyle('Title', fontSize=16, fontName='Helvetica-Bold',
                              textColor=colors.HexColor('#1A237E'), spaceAfter=4)
sub_style   = ParagraphStyle('Sub',   fontSize=8,  fontName='Helvetica',
                              textColor=colors.grey, spaceAfter=10)
h_style     = ParagraphStyle('H',     fontSize=8,  fontName='Helvetica-Bold',
                              textColor=colors.HexColor('#212121'))
p_style     = ParagraphStyle('P',     fontSize=7.5,fontName='Helvetica',
                              textColor=colors.HexColor('#424242'), leading=10)
tag_style   = ParagraphStyle('Tag',   fontSize=9,  fontName='Helvetica-Bold',
                              alignment=TA_CENTER)

story = []

# ── Cover page header ──────────────────────────────────────────────────────
story.append(Paragraph("MDS Error Image Review — June 12 2026", title_style))
story.append(Paragraph(
    "25 sampled cases from status 3015 / 3017 DLQ failures, classified by Claude Haiku 4.5",
    sub_style))
story.append(HRFlowable(width='100%', thickness=1, color=colors.HexColor('#1A237E'),
                          spaceAfter=8))

# category summary
from collections import Counter
cat_counts = Counter(r['ai_result'].get('category_code','?') for r in results)
cat_labels = {
    'A': 'Restaurant Menu', 'B': 'Menu Reference / Instructions',
    'C': 'Logo / Branding', 'D': 'Food Photo', 'E': 'Irrelevant Image'
}
summary_data = [['Category', 'Count', 'Status codes']]
for code in ['A','B','C','D','E']:
    cnt = cat_counts.get(code, 0)
    codes_in = [r['status_code'] for r in results if r['ai_result'].get('category_code') == code]
    code_dist = ', '.join(f"{k}:{v}" for k,v in Counter(codes_in).items())
    summary_data.append([f"{code}. {cat_labels.get(code, code)}", str(cnt), code_dist or '—'])

summary_table = Table(summary_data, colWidths=[95*mm, 20*mm, 65*mm])
summary_table.setStyle(TableStyle([
    ('BACKGROUND',  (0,0), (-1,0), colors.HexColor('#1A237E')),
    ('TEXTCOLOR',   (0,0), (-1,0), colors.white),
    ('FONTNAME',    (0,0), (-1,0), 'Helvetica-Bold'),
    ('FONTSIZE',    (0,0), (-1,-1), 8),
    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#F5F5F5'), colors.white]),
    ('GRID',        (0,0), (-1,-1), 0.5, colors.HexColor('#BDBDBD')),
    ('TOPPADDING',  (0,0), (-1,-1), 4),
    ('BOTTOMPADDING',(0,0),(-1,-1), 4),
    ('LEFTPADDING', (0,0), (-1,-1), 6),
]))
story.append(summary_table)
story.append(Spacer(1, 8*mm))

# ── Results: 10 per page ───────────────────────────────────────────────────
PER_PAGE = 10
for page_i, chunk_start in enumerate(range(0, len(results), PER_PAGE)):
    chunk = results[chunk_start:chunk_start + PER_PAGE]
    if page_i > 0:
        story.append(PageBreak())

    story.append(Paragraph(
        f"Cases {chunk_start+1}–{chunk_start+len(chunk)} of {len(results)}",
        ParagraphStyle('PageHdr', fontSize=8, fontName='Helvetica',
                       textColor=colors.grey, spaceAfter=4)))

    for r in chunk:
        ai     = r.get('ai_result', {})
        code   = ai.get('category_code', '?')
        label  = ai.get('category_label', 'Unknown')
        obs    = ai.get('brief_observation', '')
        conf   = ai.get('confidence', '?')
        has_dp = ai.get('has_dish_and_price', False)
        has_ci = ai.get('has_copy_instructions_or_grid', False)
        bg     = CAT_BG.get(code, colors.white)
        fc     = CAT_COLORS.get(code, colors.grey)
        ent    = r['global_entity_id']
        grid   = r['grid_id']
        sc     = r['status_code']

        # thumbnail
        thumb_buf = file_to_thumbnail(r.get('local_file','')) if r.get('local_file') else None
        thumb_cell = RLImage(thumb_buf, width=45*mm, height=36*mm) if thumb_buf else \
                     Paragraph("[image unavailable]", p_style)

        # flags row
        flags = []
        if has_dp:  flags.append("✓ Dish + Price")
        if has_ci:  flags.append("⚠ Copy Instructions / GRID Ref")
        flags_txt = "  |  ".join(flags) if flags else "—"

        info_cell = [
            Paragraph(f"<b>{grid}</b> &nbsp; <font color='grey'>{ent} · {sc}</font>", h_style),
            Spacer(1, 2),
            Paragraph(label, ParagraphStyle('Cat', fontSize=9, fontName='Helvetica-Bold',
                                             textColor=fc)),
            Spacer(1, 2),
            Paragraph(obs, p_style),
            Spacer(1, 2),
            Paragraph(f"Flags: {flags_txt}", p_style),
            Paragraph(f"Confidence: <b>{conf}</b>", p_style),
        ]

        row_table = Table([[thumb_cell, info_cell]],
                           colWidths=[48*mm, 132*mm])
        row_table.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), bg),
            ('BOX',           (0,0), (-1,-1), 0.8, fc),
            ('LEFTPADDING',   (0,0), (-1,-1), 4),
            ('RIGHTPADDING',  (0,0), (-1,-1), 6),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('VALIGN',        (0,0), (-1,-1), 'TOP'),
        ]))
        story.append(row_table)
        story.append(Spacer(1, 2.5*mm))

doc.build(story)
print(f"PDF saved: {OUT}")
size_mb = os.path.getsize(OUT) / 1024 / 1024
print(f"Size: {size_mb:.2f} MB")
