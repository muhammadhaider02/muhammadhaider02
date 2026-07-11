"""Generate dark_mode.svg and light_mode.svg for muhammadhaider02's profile card.

Layout math (Consolas, size-adjust 109%): char width = 0.55 * 1.09 * font-size.
Right panel: 16px font, x=390, 60 chars/row -> ~575px, fits 985px card.
Left panel:  ascii-art.txt is 100 cols x 49 rows; at 6px font a char is ~3.6px
wide (360px total) and line step 7.5px keeps the same cell aspect ratio as the
16px/20px right panel, so the art keeps its intended proportions.
"""
import html
import os

REPO = os.path.dirname(os.path.abspath(__file__))
ROW_WIDTH = 55  # chars available for key + dots + value (60 - '. ' - ':' - 2 spaces)

PALETTES = {
    'dark_mode.svg': dict(key='#ffa657', value='#a5d6ff', add='#3fb950', dele='#f85149',
                          cc='#616e7f', bg='#161b22', fg='#c9d1d9'),
    'light_mode.svg': dict(key='#953800', value='#0a3069', add='#1a7f37', dele='#cf222e',
                           cc='#c2cfde', bg='#f6f8fa', fg='#24292f'),
}

DASH_LINE = '-———————————————————————————————————————————-—-'          # after 12-char user@host
CONTACT_HDR = '- Contact</tspan> -——————————————————————————————————————————————-—-'
STATS_HDR = '- GitHub Stats</tspan> -—————————————————————————————————————————-—-'


def key_html(parts):
    return '.'.join(f'<tspan class="key">{p}</tspan>' for p in parts)


def row(y, parts, value, ids=None):
    """One '. Key: .... value' line, padded to 60 chars total."""
    klen = sum(len(p) for p in parts) + len(parts) - 1
    ndots = ROW_WIDTH - klen - len(value)
    assert ndots >= 1, f'row y={y} overflows by {1 - ndots} chars: {value!r}'
    dots_id = f' id="{ids}_dots"' if ids else ''
    val_id = f' id="{ids}"' if ids else ''
    return (f'<tspan x="390" y="{y}" class="cc">. </tspan>{key_html(parts)}:'
            f'<tspan class="cc"{dots_id}> {"." * ndots} </tspan>'
            f'<tspan class="value"{val_id}>{html.escape(value)}</tspan>')


def blank(y):
    return f'<tspan x="390" y="{y}" class="cc">. </tspan>'


RAMP = ' .:-=+*#%@'  # the art's brightness ramp, dark bg -> space is darkest
ART_ROWS, ART_COLS = 65, 100  # baselines 30..510 at 7.5px step = text column extent


def resample_art():
    """Zoom the source art uniformly to fill the panel height, center-cropping
    the width overflow, by resampling ramp levels bilinearly."""
    with open(f'{REPO}/ascii-art.txt', encoding='utf-8') as f:
        lines = [l.rstrip('\n') for l in f]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    src_w = max(len(l) for l in lines)
    src = [[RAMP.index(ch) for ch in l.ljust(src_w)] for l in lines]
    src_h = len(src)

    scale = ART_ROWS / src_h
    crop = (src_w * scale - ART_COLS) / 2  # cols trimmed off each side
    assert crop >= 0, 'art is too narrow to zoom-crop; lower ART_ROWS'

    def sample(sy, sx):
        y0 = min(max(int(sy), 0), src_h - 1)
        x0 = min(max(int(sx), 0), src_w - 1)
        y1, x1 = min(y0 + 1, src_h - 1), min(x0 + 1, src_w - 1)
        fy, fx = min(max(sy - y0, 0), 1), min(max(sx - x0, 0), 1)
        top = src[y0][x0] * (1 - fx) + src[y0][x1] * fx
        bot = src[y1][x0] * (1 - fx) + src[y1][x1] * fx
        return top * (1 - fy) + bot * fy

    rows = []
    for r in range(ART_ROWS):
        sy = (r + 0.5) / scale - 0.5
        row = []
        for c in range(ART_COLS):
            sx = (c + crop + 0.5) / scale - 0.5
            row.append(RAMP[min(9, max(0, round(sample(sy, sx))))])
        rows.append(''.join(row))
    return rows


def ascii_block(fg):
    out = [f'<text x="15" y="30" fill="{fg}" class="ascii" font-size="6px">']
    y = 30.0
    for line in resample_art():
        out.append(f'<tspan x="15" y="{y:g}">{html.escape(line)}</tspan>')
        y += 7.5
    out.append('</text>')
    return '\n'.join(out)


def right_panel():
    r = ['<text x="390" y="30">']
    r.append(f'<tspan x="390" y="30">haider@akbar</tspan> {DASH_LINE}')
    r.append(row(50, ['OS'], 'Windows 11, Android 16, Ubuntu'))
    r.append(row(70, ['Uptime'], '22 years, 8 months, 20 days', ids='age_data'))
    r.append(row(90, ['Host'], 'Nysonian Inc. & FRACK Tech.'))
    r.append(row(110, ['Kernel'], 'AI Automation Engineer'))
    r.append(row(130, ['IDE'], 'Cursor, Claude Code'))
    r.append(blank(150))
    r.append(row(170, ['Languages', 'Programming'], 'Python, TypeScript, SQL'))
    r.append(row(190, ['Languages', 'Computer'], 'HTML, CSS, JSON, YAML'))
    r.append(row(210, ['Languages', 'Real'], 'English, Urdu, German'))
    r.append(blank(230))
    r.append(row(250, ['Hobbies', 'Software'], 'AI Agents, Workflow Automation'))
    r.append(row(270, ['Hobbies', 'Hardware'], 'Football, F1, Chess'))
    r.append(f'<tspan x="390" y="310">{CONTACT_HDR}')
    r.append(row(330, ['Email'], 'muhammadhaiderakbar@gmail.com'))
    r.append(row(350, ['Website'], 'haiderakbar.dev'))
    r.append(row(370, ['LinkedIn'], 'haiderakbar'))
    r.append(row(390, ['GitHub'], 'muhammadhaider02'))
    r.append(row(410, ['Location'], 'Islamabad, Pakistan'))
    r.append(f'<tspan x="390" y="450">{STATS_HDR}')
    r.append('<tspan x="390" y="470" class="cc">. </tspan><tspan class="key">Repos</tspan>:'
             '<tspan class="cc" id="repo_data_dots"> ...... </tspan>'
             '<tspan class="value" id="repo_data">0</tspan> {<tspan class="key">Contributed</tspan>: '
             '<tspan class="value" id="contrib_data">0</tspan>} | <tspan class="key">Stars</tspan>:'
             '<tspan class="cc" id="star_data_dots"> ............. </tspan>'
             '<tspan class="value" id="star_data">0</tspan>')
    r.append('<tspan x="390" y="490" class="cc">. </tspan><tspan class="key">Commits</tspan>:'
             '<tspan class="cc" id="commit_data_dots"> ...................... </tspan>'
             '<tspan class="value" id="commit_data">0</tspan> | <tspan class="key">Followers</tspan>:'
             '<tspan class="cc" id="follower_data_dots"> ......... </tspan>'
             '<tspan class="value" id="follower_data">0</tspan>')
    r.append('<tspan x="390" y="510" class="cc">. </tspan><tspan class="key">Lines of Code</tspan>:'
             '<tspan class="cc" id="loc_data_dots"> .............. </tspan>'
             '<tspan class="value" id="loc_data">0</tspan> ( <tspan class="addColor" id="loc_add">0</tspan>'
             '<tspan class="addColor">++</tspan>, <tspan id="loc_del_dots"> ...... </tspan>'
             '<tspan class="delColor" id="loc_del">0</tspan><tspan class="delColor">--</tspan> )')
    r.append('</text>')
    return '\n'.join(r)


TEMPLATE = """<?xml version='1.0' encoding='UTF-8'?>
<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" width="985px" height="530px" font-size="16px">
<style>
@font-face {{
src: local('Consolas'), local('Consolas Bold');
font-family: 'ConsolasFallback';
font-display: swap;
-webkit-size-adjust: 109%;
size-adjust: 109%;
}}
.key {{fill: {key};}}
.value {{fill: {value};}}
.addColor {{fill: {add};}}
.delColor {{fill: {dele};}}
.cc {{fill: {cc};}}
text, tspan {{white-space: pre;}}
</style>
<rect width="985px" height="530px" fill="{bg}" rx="15"/>
{art}
<text x="390" y="30" fill="{fg}">
{panel}
</svg>"""


panel = right_panel().split('\n', 1)[1]  # drop the opening <text>; template supplies it
for fname, pal in PALETTES.items():
    svg = TEMPLATE.format(art=ascii_block(pal['fg']), panel=panel, **pal)
    with open(f'{REPO}/{fname}', 'w', encoding='utf-8', newline='\n') as f:
        f.write(svg)
    print(f'wrote {fname} ({len(svg)} bytes)')
