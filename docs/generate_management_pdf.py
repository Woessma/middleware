from pathlib import Path
import struct
import textwrap
import zlib

BASE = Path('/opt/fhir-middleware/Woess_Fhir/fhir-middleware/docs')
MD_PATH = BASE / 'management-summary-kubernetes-poc.md'
OUT_PATH = BASE / 'management-summary-kubernetes-poc.pdf'

PAGE_W = 595
PAGE_H = 842


def resolve_logo_path() -> Path:
    candidates = [
        BASE / 'Designer.png',
        BASE / 'decisions' / 'Designer.png',
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f'No supported logo file found in: {candidates}')


def pdf_escape(text: str) -> str:
    return text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def decode_png_rgb8_non_interlaced(path: Path):
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise RuntimeError('Not a PNG file')

    pos = 8
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()

    while pos < len(data):
        chunk_len = struct.unpack('>I', data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_data = data[pos + 8:pos + 8 + chunk_len]
        pos += 12 + chunk_len

        if chunk_type == b'IHDR':
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack('>IIBBBBB', chunk_data)
        elif chunk_type == b'IDAT':
            idat.extend(chunk_data)
        elif chunk_type == b'IEND':
            break

    if bit_depth != 8 or color_type != 2 or interlace != 0:
        raise RuntimeError('Unsupported PNG format: need RGB, 8-bit, non-interlaced')

    scan = zlib.decompress(bytes(idat))
    bpp = 3
    stride = width * bpp
    out = bytearray(height * stride)

    def paeth(a, b, c):
        p = a + b - c
        pa = abs(p - a)
        pb = abs(p - b)
        pc = abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        if pb <= pc:
            return b
        return c

    src = 0
    for y in range(height):
        filt = scan[src]
        src += 1
        row = scan[src:src + stride]
        src += stride
        dst = y * stride
        prev = (y - 1) * stride

        for x in range(stride):
            left = out[dst + x - bpp] if x >= bpp else 0
            up = out[prev + x] if y > 0 else 0
            up_left = out[prev + x - bpp] if (y > 0 and x >= bpp) else 0
            rv = row[x]

            if filt == 0:
                v = rv
            elif filt == 1:
                v = (rv + left) & 0xFF
            elif filt == 2:
                v = (rv + up) & 0xFF
            elif filt == 3:
                v = (rv + ((left + up) // 2)) & 0xFF
            elif filt == 4:
                v = (rv + paeth(left, up, up_left)) & 0xFF
            else:
                raise RuntimeError('Unknown PNG filter type')

            out[dst + x] = v

    return width, height, zlib.compress(bytes(out), level=9)


def add_text_block(cmds, x, y, lines, font='F1', size=11, leading=14):
    cmds.append('BT')
    cmds.append(f'/{font} {size} Tf')
    cmds.append(f'{x} {y} Td')
    first = True
    for line in lines:
        line = line.encode('latin-1', 'replace').decode('latin-1')
        if first:
            cmds.append(f'({pdf_escape(line)}) Tj')
            first = False
        else:
            cmds.append(f'0 -{leading} Td ({pdf_escape(line)}) Tj')
    cmds.append('ET')


def box(cmds, x, y, w, h, fill_rgb, stroke_rgb=(0.2, 0.2, 0.2), line_w=1.0):
    fr, fg, fb = fill_rgb
    sr, sg, sb = stroke_rgb
    cmds.append('q')
    cmds.append(f'{line_w} w')
    cmds.append(f'{fr:.3f} {fg:.3f} {fb:.3f} rg')
    cmds.append(f'{sr:.3f} {sg:.3f} {sb:.3f} RG')
    cmds.append(f'{x} {y} {w} {h} re B')
    cmds.append('Q')


def arrow(cmds, x1, y1, x2, y2, rgb=(0.18, 0.24, 0.35)):
    r, g, b = rgb
    cmds.append('q')
    cmds.append('1.6 w')
    cmds.append(f'{r:.3f} {g:.3f} {b:.3f} RG')
    cmds.append(f'{x1} {y1} m {x2} {y2} l S')

    # Arrow head
    if x2 >= x1:
        pts = [(x2, y2), (x2 - 8, y2 + 4), (x2 - 8, y2 - 4)]
    else:
        pts = [(x2, y2), (x2 + 8, y2 + 4), (x2 + 8, y2 - 4)]

    cmds.append(f'{r:.3f} {g:.3f} {b:.3f} rg')
    cmds.append(f'{pts[0][0]} {pts[0][1]} m {pts[1][0]} {pts[1][1]} l {pts[2][0]} {pts[2][1]} l h f')
    cmds.append('Q')


def parse_detail_lines(md_text: str):
    lines = []
    for raw in md_text.splitlines():
        ln = raw.strip()
        if not ln:
            lines.append('')
            continue
        if ln.startswith('#'):
            continue
        if 'Architekturzeichnung inkl. BridgeLink' in ln:
            continue
        if ln.startswith('+') or ln.startswith('|'):
            continue

        if ln.startswith('## '):
            lines.append(ln[3:].upper())
            continue

        if ln.startswith('- '):
            lines.extend(textwrap.wrap('- ' + ln[2:], width=96, subsequent_indent='  '))
            continue

        lines.extend(textwrap.wrap(ln, width=98))
    return lines


def extract_status_line(md_text: str) -> str:
    for raw in md_text.splitlines():
        line = raw.strip()
        if line.startswith('Stand:'):
            return line
    return 'Stand: n/a'


def chunk_lines(lines, max_lines):
    return [lines[i:i + max_lines] for i in range(0, len(lines), max_lines)] or [[]]


def build_pdf():
    md_text = MD_PATH.read_text(encoding='utf-8')
    details = parse_detail_lines(md_text)
    status_line = extract_status_line(md_text)

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
    page1_id = 6
    page1_content_id = 7

    # Page 1: Visual summary
    c1 = []

    add_text_block(c1, 50, 785, ['Management Summary'], font='F2', size=20, leading=20)
    add_text_block(c1, 50, 760, ['Kubernetes Zielbild fuer den FHIR POC'], font='F2', size=13, leading=16)
    add_text_block(c1, 50, 742, [status_line], font='F1', size=10, leading=12)

    c1.append('q')
    c1.append(f'{logo_w} 0 0 {logo_h} {logo_x} {logo_y} cm')
    c1.append('/Im1 Do')
    c1.append('Q')

    c1.append('q')
    c1.append('0.9 w')
    c1.append('0.75 0.78 0.84 RG')
    c1.append('50 720 m 545 720 l S')
    c1.append('Q')

    add_text_block(c1, 50, 700, ['Zielarchitektur'], font='F2', size=13, leading=14)

    # Architecture boxes
    box(c1, 55, 590, 120, 56, (0.85, 0.93, 1.00))
    add_text_block(c1, 66, 623, ['Quellsysteme'], font='F2', size=10, leading=12)
    add_text_block(c1, 66, 609, ['CDA, eMediplan,'], font='F1', size=9, leading=11)
    add_text_block(c1, 66, 597, ['klinische Systeme'], font='F1', size=9, leading=11)

    box(c1, 210, 590, 110, 56, (0.86, 0.97, 0.88))
    add_text_block(c1, 228, 623, ['BridgeLink'], font='F2', size=10, leading=12)
    add_text_block(c1, 222, 608, ['Orchestrierung'], font='F1', size=9, leading=11)
    add_text_block(c1, 228, 596, ['Routing'], font='F1', size=9, leading=11)

    box(c1, 350, 590, 125, 56, (1.00, 0.94, 0.84))
    add_text_block(c1, 360, 623, ['Python Middleware'], font='F2', size=10, leading=12)
    add_text_block(c1, 364, 608, ['Parser, Mapper,'], font='F1', size=9, leading=11)
    add_text_block(c1, 364, 596, ['FHIR APIs'], font='F1', size=9, leading=11)

    box(c1, 210, 500, 130, 56, (0.93, 0.90, 1.00))
    add_text_block(c1, 228, 533, ['HAPI FHIR'], font='F2', size=10, leading=12)
    add_text_block(c1, 220, 518, ['Repository / SoT'], font='F1', size=9, leading=11)
    add_text_block(c1, 220, 506, ['FHIR Resources'], font='F1', size=9, leading=11)

    box(c1, 380, 500, 120, 56, (0.90, 0.96, 0.98))
    add_text_block(c1, 398, 533, ['Zielsysteme'], font='F2', size=10, leading=12)
    add_text_block(c1, 398, 518, ['EPIC / UMZH'], font='F1', size=9, leading=11)
    add_text_block(c1, 404, 506, ['Connect'], font='F1', size=9, leading=11)

    arrow(c1, 175, 618, 210, 618)
    arrow(c1, 320, 618, 350, 618)
    arrow(c1, 412, 590, 285, 556)
    arrow(c1, 340, 528, 380, 528)

    add_text_block(c1, 50, 470, ['Managed-Service Betriebsrahmen'], font='F2', size=12, leading=14)

    # Kubernetes frame + lanes
    c1.append('q')
    c1.append('1 w')
    c1.append('0.27 0.47 0.63 RG')
    c1.append('0.96 0.98 1.00 rg')
    c1.append('50 300 495 155 re B')
    c1.append('Q')

    add_text_block(c1, 65, 440, ['Kubernetes Plattform (Managed Cluster, Ingress, Security, Observability)'], font='F2', size=10, leading=12)

    box(c1, 70, 332, 145, 85, (0.86, 0.95, 0.86), stroke_rgb=(0.28, 0.52, 0.28))
    add_text_block(c1, 84, 398, ['DEV'], font='F2', size=12, leading=14)
    add_text_block(c1, 84, 382, ['Auto Deploy'], font='F1', size=9, leading=11)
    add_text_block(c1, 84, 370, ['schnelle Iteration'], font='F1', size=9, leading=11)

    box(c1, 225, 332, 145, 85, (1.00, 0.96, 0.86), stroke_rgb=(0.61, 0.45, 0.17))
    add_text_block(c1, 240, 398, ['TEST'], font='F2', size=12, leading=14)
    add_text_block(c1, 240, 382, ['Integration'], font='F1', size=9, leading=11)
    add_text_block(c1, 240, 370, ['Abnahme Gates'], font='F1', size=9, leading=11)

    box(c1, 380, 332, 145, 85, (0.91, 0.93, 1.00), stroke_rgb=(0.27, 0.36, 0.64))
    add_text_block(c1, 396, 398, ['PROD'], font='F2', size=12, leading=14)
    add_text_block(c1, 396, 382, ['kontrollierte'], font='F1', size=9, leading=11)
    add_text_block(c1, 396, 370, ['Releases / SLO'], font='F1', size=9, leading=11)

    arrow(c1, 215, 374, 225, 374)
    arrow(c1, 370, 374, 380, 374)

    add_text_block(c1, 50, 275, ['Management-Kernaussagen'], font='F2', size=12, leading=14)
    key_points = [
        '- Managed-Service-First reduziert Betriebsrisiko und beschleunigt Delivery.',
        '- CI/CD mit Quality Gates schafft sichere Promotion von DEV nach TEST nach PROD.',
        '- Kerninfrastruktur: Cluster, Datenbank, Registry, Ingress, Secrets und Monitoring.',
        '- Skalierung erfolgt horizontal in Middleware und resilient fuer PROD mit HA-Pattern.',
    ]
    add_text_block(c1, 60, 255, key_points, font='F1', size=10, leading=14)

    stream1 = '\n'.join(c1).encode('latin-1')

    objects[catalog_id] = '<< /Type /Catalog /Pages 2 0 R >>'
    objects[font_reg_id] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'
    objects[font_bold_id] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>'
    objects[image_id] = (
        f'<< /Type /XObject /Subtype /Image /Width {img_w} /Height {img_h} '
        f'/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(img_stream)} >>\n'
    ).encode('latin-1') + b'stream\n' + img_stream + b'\nendstream'

    page_resources = '/Resources << /Font << /F1 3 0 R /F2 4 0 R >> /XObject << /Im1 5 0 R >> >>'
    objects[page1_id] = f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] {page_resources} /Contents 7 0 R >>'
    objects[page1_content_id] = f'<< /Length {len(stream1)} >>\nstream\n'.encode('latin-1') + stream1 + b'\nendstream'

    page_ids = [page1_id]
    next_object_id = 8
    for index, page_lines in enumerate(chunk_lines(details, 47), start=1):
        commands = []
        title = 'Detailuebersicht' if index == 1 else f'Detailuebersicht ({index})'
        add_text_block(commands, 50, 790, [title], font='F2', size=14, leading=16)
        add_text_block(commands, 50, 764, page_lines, font='F1', size=10, leading=13)
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
