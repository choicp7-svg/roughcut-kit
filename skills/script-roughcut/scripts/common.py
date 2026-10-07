"""script-roughcut 공용 함수: ffmpeg 로 클립 정보 읽기, EDL(edl.json) 읽기."""
import json, os, re, subprocess
from fractions import Fraction

FF = os.environ.get('FFMPEG', 'ffmpeg')
VIDEO_EXT = ('.mp4', '.mov', '.mxf', '.m4v', '.avi', '.mts')


def probe(path):
    """ffprobe 없이 `ffmpeg -i` 출력에서 길이·fps·해상도·타임코드·오디오 정보를 읽는다."""
    t = subprocess.run([FF, '-hide_banner', '-i', path], capture_output=True, text=True).stderr
    m = re.search(r'Duration: (\d+):(\d+):([\d.]+)', t)
    if not m:
        raise SystemExit(f'영상 정보를 읽을 수 없음: {path}')
    info = {'dur': int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]), 'w': 1920, 'h': 1080,
            'fps': Fraction(30000, 1001), 'sr': 48000, 'ch': 2, 'tc': None, 'has_audio': False}
    v = re.search(r'Stream #[^\n]*?: Video: ([^\n]*)', t)
    if v:
        wh = re.search(r'(\d{3,5})x(\d{3,5})', v[1])
        if wh:
            info['w'], info['h'] = int(wh[1]), int(wh[2])
        r = re.search(r'([\d.]+) tbr', v[1]) or re.search(r'([\d.]+) fps', v[1])
        if r:
            x = float(r[1])
            info['fps'] = next((Fraction(n * 1000, 1001) for n in (24, 30, 48, 60, 120)
                                if abs(x - n * 1000 / 1001) < 0.02), Fraction(x).limit_denominator(1001))
    a = re.search(r'Stream #[^\n]*?: Audio: ([^\n]*)', t)
    if a:
        info['has_audio'] = True
        sr = re.search(r'(\d+) Hz', a[1])
        if sr:
            info['sr'] = int(sr[1])
        info['ch'] = 1 if ', mono' in a[1] else 2
    tc = re.search(r'timecode\s*:\s*(\d+)[:;](\d+)[:;](\d+)[:;](\d+)', t)
    if tc:
        info['tc'] = tuple(int(x) for x in tc.groups())
    return info


def list_clips(folder):
    return sorted(f for f in os.listdir(folder)
                  if f.lower().endswith(VIDEO_EXT) and not f.startswith('._'))


def load_edl(path):
    """edl.json -> (이름, 원본폴더, [항목]). 항목은 {'scene': 제목} 또는 {'clip','in','out','text'}."""
    e = json.load(open(path, encoding='utf-8'))
    here = os.path.dirname(os.path.abspath(path))
    src = e.get('source_dir') or os.path.dirname(here)
    cuts = e['cuts']
    for c in cuts:
        if 'clip' in c:
            assert os.path.exists(os.path.join(src, c['clip'])), f"클립 없음: {c['clip']}"
            assert 0 <= c['in'] < c['out'], f'in/out 이상: {c}'
    return e.get('name', 'script_cut'), src, cuts


def frames(cut, info):
    """컷의 (in프레임, out프레임) — 프리미어와 캡컷이 같은 값을 쓴다."""
    fps = float(info['fps'])
    total = round(info['dur'] * fps)
    return round(cut['in'] * fps), min(round(cut['out'] * fps), total)
