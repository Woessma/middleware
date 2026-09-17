from pathlib import Path
import textwrap

from generate_management_pdf import (
    PAGE_H,
    PAGE_W,
    add_text_block,
    decode_png_rgb8_non_interlaced,
    extract_status_line,
    resolve_logo_path,
)


BASE = Path('/opt/fhir-middleware/Woess_Fhir/fhir-middleware/docs')
MD_PATH = BASE / 'kubernetes-infrastruktur-gl.md'
OUT_PATH = BASE / 'kubernetes-infrastruktur-gl.pdf'


def parse_sections(md_text: str):
    sections = []
    current_title = None
    current_lines = []

    for raw in md_text.splitlines():
        line = raw.strip()
        if not line or line.startswith('# '):
            continue
        if line.startswith('Stand:'):
            continue
        if line.startswith('## '):
            if current_title is not None:
                sections.append((current_title, current_lines))
            current_title = line[3:]
            current_lines = []
            continue
        if line.startswith('- '):
            current_lines.extend(textwrap.wrap('- ' + line[2:], width=78, subsequent_indent='  '))
            continue
        current_lines.extend(textwrap.wrap(line, width=82))

    if current_title is not None:
        sections.append((current_title, current_lines))

    return sections


def chunk_sections(sections, max_lines):
    pages = []
    current = []
    used = 0

    for title, lines in sections:
        block = [title.upper(), ''] + lines + ['']
        if current and used + len(block) > max_lines:
            pages.append(current)
            current = []
            used = 0
        current.extend(block)
        used += len(block)

    if current:
        pages.append(current)

    return pages or [[]]


def build_pdf():
    md_text = MD_PATH.read_text(encoding='utf-8')
    status_line = extract_status_line(md_text)
    sections = parse_sections(md_text)

    img_w, img_h, img_stream = decode_png_rgb8_non_interlaced(resolve_logo_path())

    logo_w = 150
    logo_h = int(logo_w * img_h / img_w)
    logo_x = PAGE_W - 50 - logo_w
    logo_y = PAGE_H - 50 - logo_h

    objects = {}
    catalog_id = 1
    pages_id = 2
    font_reg_id = 3
    font_bold_id = 4
    image_id = 5

    objects[catalog_id] = '<< /Type /Catalog /Pages 2 0 R >>'
    objects[font_reg_id] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
    objects[font_bold_id] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>'
    objects[image_id] = (
        f'<< /Type /XObject /Subtype /Image /Width {img_w} /Height {img_h} '
        f'/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(img_stream)} >>\n'
    ).encode('latin-1') + b'stream\n' + img_stream + b'\nendstream'

    page_resources = '/Resources << /Font << /F1 3 0 R /F2 4 0 R >> /XObject << /Im1 5 0 R >> >>'
    page_ids = []
    next_object_id = 6

    page_chunks = chunk_sections(sections, 45)
    for index, page_lines in enumerate(page_chunks, start=1):
        commands = []
        add_text_block(commands, 50, 785, ['Benoetigte Infrastruktur'], font='F2', size=20, leading=20)
        add_text_block(commands, 50, 760, ['Kubernetes Zielbild fuer die GL'], font='F2', size=13, leading=16)
        add_text_block(commands, 50, 742, [status_line], font='F1', size=10, leading=12)

        commands.append('q')
        commands.append(f'{logo_w} 0 0 {logo_h} {logo_x} {logo_y} cm')
        commands.append('/Im1 Do')
        commands.append('Q')

        commands.append('q')
        commands.append('0.9 w')
        commands.append('0.75 0.78 0.84 RG')
        commands.append('50 720 m 545 720 l S')
        commands.append('Q')

        subtitle = 'Infrastrukturbedarf' if index == 1 else f'Infrastrukturbedarf ({index})'
        add_text_block(commands, 50, 695, [subtitle], font='F2', size=14, leading=16)
        add_text_block(commands, 50, 668, page_lines, font='F1', size=11, leading=15)

        stream = '\n'.join(commands).encode('latin-1')
        page_id = next_object_id
        content_id = next_object_id + 1
        next_object_id += 2

        objects[page_id] = f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] {page_resources} /Contents {content_id} 0 R >>'
        objects[content_id] = f'<< /Length {len(stream)} >>\nstream\n'.encode('latin-1') + stream + b'\nendstream'
        page_ids.append(page_id)

    page_kids = ' '.join(f'{page_id} 0 R' for page_id in page_ids)
    objects[pages_id] = f'<< /Type /Pages /Kids [{page_kids}] /Count {len(page_ids)} >>'

    pdf = bytearray(b'%PDF-1.4\n')
    offsets = {0: 0}

    for obj_id in sorted(objects.keys()):
        offsets[obj_id] = len(pdf)
        pdf += f'{obj_id} 0 obj\n'.encode('latin-1')
        body = objects[obj_id]
        if isinstance(body, bytes):
            pdf += body + b'\n'
        else:
            pdf += body.encode('latin-1') + b'\n'
        pdf += b'endobj\n'

    xref_pos = len(pdf)
    max_id = max(objects.keys())
    pdf += f'xref\n0 {max_id + 1}\n'.encode('latin-1')
    pdf += b'0000000000 65535 f \n'
    for obj_id in range(1, max_id + 1):
        off = offsets.get(obj_id, 0)
        pdf += f'{off:010d} 00000 n \n'.encode('latin-1')

    pdf += (
        f'trailer\n<< /Size {max_id + 1} /Root 1 0 R >>\n'
        f'startxref\n{xref_pos}\n%%EOF\n'
    ).encode('latin-1')

    OUT_PATH.write_bytes(pdf)


if __name__ == '__main__':
    build_pdf()
    print(f'created: {OUT_PATH}')
    print(f'size: {OUT_PATH.stat().st_size} bytes')