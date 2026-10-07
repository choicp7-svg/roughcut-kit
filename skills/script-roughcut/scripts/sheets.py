#!/usr/bin/env python3
"""화면 확인용 썸네일 시트를 만든다 (rough_cut/_sheets/).

    python3 sheets.py clips <촬영본 폴더>     # 클립마다 5프레임 — 어떤 앵글/장면인지 파악
    python3 sheets.py cuts  <edl.json>        # 컷마다 시작·중간·끝 프레임 — 컷이 의도대로인지 확인
"""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import FF, list_clips, load_edl, probe
from PIL import Image, ImageDraw


def grab(path, t, width):
    o = tempfile.mktemp(suffix='.jpg')
    subprocess.run([FF, '-loglevel', 'error', '-y', '-ss', f'{max(0, t):.3f}', '-i', path, '-frames:v', '1',
                    '-vf', f'scale={width}:-2', '-q:v', '6', o])
    im = Image.open(o).convert('RGB') if os.path.exists(o) else Image.new('RGB', (width, width * 9 // 16))
    if os.path.exists(o):
        os.remove(o)
    return im


def strip(label, frames):
    w, h = frames[0].size
    im = Image.new('RGB', (w * len(frames), h + 18), 'black')
    for k, f in enumerate(frames):
        im.paste(f.resize((w, h)), (w * k, 18))
    ImageDraw.Draw(im).text((4, 3), label, fill='yellow')
    return im


def save(strips, out_dir, prefix, per_sheet, cols=1):
    os.makedirs(out_dir, exist_ok=True)
    for old in os.listdir(out_dir):
        if old.startswith(prefix):
            os.remove(os.path.join(out_dir, old))
    paths = []
    for s in range(0, len(strips), per_sheet):
        part = strips[s:s + per_sheet]
        w, h = part[0].size
        rows = -(-len(part) // cols)
        sh = Image.new('RGB', (w * cols, h * rows), 'black')
        for j, im in enumerate(part):
            sh.paste(im, (w * (j // rows), h * (j % rows)))
        p = os.path.join(out_dir, f'{prefix}{s // per_sheet}.jpg')
        sh.save(p, quality=80)
        paths.append(p)
    return paths


mode, target = sys.argv[1], sys.argv[2]
if mode == 'clips':
    strips = []
    for c in list_clips(target):
        p = os.path.join(target, c)
        d = probe(p)['dur']
        strips.append(strip(f'{c}  {d:.1f}s', [grab(p, d * (k + 0.5) / 5, 384) for k in range(5)]))
    out = save(strips, os.path.join(target, 'rough_cut', '_sheets'), 'clips_', 7)
else:
    name, src, cuts = load_edl(target)
    strips = []
    for i, c in enumerate(x for x in cuts if 'clip' in x):
        p = os.path.join(src, c['clip'])
        ts = (c['in'] + 0.1, (c['in'] + c['out']) / 2, c['out'] - 0.1)
        strips.append(strip(f"{i + 1:02d} {c['clip']} {c['in']}-{c['out']}  {c.get('text', '')[:40]}",
                            [grab(p, t, 256) for t in ts]))
    out = save(strips, os.path.join(os.path.dirname(os.path.abspath(target)), '_sheets'), 'cuts_', 22, cols=2)
print('\n'.join(out))
