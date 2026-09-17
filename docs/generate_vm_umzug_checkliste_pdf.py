from pathlib import Path
import textwrap

from generate_management_pdf import PAGE_H, PAGE_W, add_text_block


BASE = Path('/opt/fhir-middleware/Woess_Fhir/fhir-middleware/docs')
MD_PATH = BASE / 'vm-umzug-checkliste.md'
OUT_PATH = BASE / 'vm-umzug-checkliste.pdf'


def parse_sections(markdown: str):
    sections = []
    title = None
    lines = []

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('# ') or line.startswith('Stand:'):
            continue
        if line.startswith('## '):
            if title:
                sections.append((title, lines))
            title = line[3:]
            lines = []
        elif line.startswith('[ ] '):
            lines.extend(textwrap.wrap(line, width=87, subsequent_indent='    '))
        elif line.startswith('Erklaerung:'):
            lines.extend(textwrap.wrap(line, width=87, subsequent_indent='    '))

    if title:
        sections.append((title, lines))
    return sections


def paginate(sections, max_lines=42):
    pages = []
    page = []
    used = 0
    for title, lines in sections:
        block = [title.upper(), ''] + lines + ['']
        if page and used + len(block) > max_lines:
            pages.append(page)
            page = []
            used = 0
        page.extend(block)
        used += len(block)
    if page:
        pages.append(page)
    return pages


def build_pdf():
    pages = paginate(parse_sections(MD_PATH.read_text(encoding='utf-8')))
    objects = {
        1: '<< /Type /Catalog /Pages 2 0 R >>',
        3: '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        4: '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>',
    }
    page_ids = []
    next_id = 5

    for number, lines in enumerate(pages, start=1):
        commands = []
        add_text_block(commands, 48, 792, ['TODO: Neuaufbau FHIR-Plattform'], font='F2', size=18, leading=20)
        add_text_block(commands, 48, 770, ['Ohne Datenuebernahme | Python-Middleware neu deployen'], font='F1', size=11, leading=13)
        commands.extend(['q', '0.25 0.42 0.58 RG', '1 w', '48 755 m 547 755 l S', 'Q'])
        add_text_block(commands, 48, 735, lines, font='F1', size=9, leading=13)
        add_text_block(commands, 48, 35, [f'Stand: 2026-09-09 | Seite {number}/{len(pages)}'], font='F1', size=8, leading=10)
        stream = '\n'.join(commands).encode('latin-1')
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        objects[page_id] = (
            f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] '
            f'/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>'
        )
        objects[content_id] = f'<< /Length {len(stream)} >>\nstream\n'.encode('latin-1') + stream + b'\nendstream'
        page_ids.append(page_id)

    objects[2] = f'<< /Type /Pages /Kids [{" ".join(f"{page_id} 0 R" for page_id in page_ids)}] /Count {len(page_ids)} >>'
    pdf = bytearray(b'%PDF-1.4\n')
    offsets = {0: 0}
    for object_id in sorted(objects):
        offsets[object_id] = len(pdf)
        pdf += f'{object_id} 0 obj\n'.encode('latin-1')
        body = objects[object_id]
        pdf += body if isinstance(body, bytes) else body.encode('latin-1')
        pdf += b'\nendobj\n'

    startxref = len(pdf)
    pdf += f'xref\n0 {max(objects) + 1}\n'.encode('latin-1')
    pdf += b'0000000000 65535 f\n'
    for object_id in range(1, max(objects) + 1):
        pdf += f'{offsets[object_id]:010d} 00000 n\n'.encode('latin-1')
    pdf += f'trailer\n<< /Size {max(objects) + 1} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF\n'.encode('latin-1')
    OUT_PATH.write_bytes(pdf)


if __name__ == '__main__':
    build_pdf()
    print(f'created: {OUT_PATH}')
    print(f'pages: {len(paginate(parse_sections(MD_PATH.read_text(encoding="utf-8"))))}')
    print(f'size: {OUT_PATH.stat().st_size} bytes')