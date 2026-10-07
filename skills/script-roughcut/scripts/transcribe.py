#!/usr/bin/env python3
"""촬영본 폴더의 모든 클립을 전사해 클립별 대사 목록을 만든다 (rough_cut/by_clip.txt).

    python3 transcribe.py <촬영본 폴더> [--lang ko] [--model large-v3-turbo]

시간은 각 클립 안에서의 초. 이미 전사한 클립은 by_clip.json 캐시에서 다시 쓴다.
"""
import argparse, json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import FF, list_clips, probe

PHANTOMS = ('다음 영상에서 만나요', '시청해 주셔서 감사', '시청해주셔서 감사', '한글자막', '자막 제공', '구독과 좋아요',
            'thanks for watching', 'subtitles by')

ap = argparse.ArgumentParser()
ap.add_argument('folder')
ap.add_argument('--lang', default='ko')
ap.add_argument('--model', default=os.environ.get('FW_MODEL', 'large-v3-turbo'))
a = ap.parse_args()

out_dir = os.path.join(a.folder, 'rough_cut')
os.makedirs(out_dir, exist_ok=True)
cache_path = os.path.join(out_dir, 'by_clip.json')
cache = json.load(open(cache_path, encoding='utf-8')) if os.path.exists(cache_path) else {}

clips = list_clips(a.folder)
todo = [c for c in clips if c not in cache]
if todo:
    from faster_whisper import WhisperModel
    model = WhisperModel(a.model, device='cpu', compute_type='int8', cpu_threads=min(8, os.cpu_count() or 4))
    for n, c in enumerate(todo, 1):
        info = probe(os.path.join(a.folder, c))
        lines = []
        if info['has_audio']:
            wav = tempfile.mktemp(suffix='.wav')
            subprocess.run([FF, '-loglevel', 'error', '-y', '-i', os.path.join(a.folder, c), '-vn', '-ac', '1',
                            '-ar', '16000', wav], check=True)
            segs, _ = model.transcribe(wav, language=a.lang, beam_size=1, condition_on_previous_text=False,
                                       word_timestamps=True, vad_filter=True,
                                       vad_parameters={'min_silence_duration_ms': 300})
            for s in segs:
                ws = s.words or []
                st, en = (ws[0].start, ws[-1].end) if ws else (s.start, s.end)
                lines.append([round(st, 2), round(en, 2), s.text.strip()])
            os.remove(wav)
        cache[c] = {'dur': round(info['dur'], 2), 'lines': lines}
        json.dump(cache, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'[{n}/{len(todo)}] {c}: {len(lines)}줄', file=sys.stderr, flush=True)

with open(os.path.join(out_dir, 'by_clip.txt'), 'w', encoding='utf-8') as f:
    for c in clips:
        f.write(f"\n## {c} ({cache[c]['dur']:.1f}s)\n")
        for st, en, text in cache[c]['lines']:
            mark = '[환각?] ' if any(p in text.lower() for p in PHANTOMS) else ''
            f.write(f'{st:7.2f}-{en:7.2f}  {mark}{text}\n')
print(os.path.join(out_dir, 'by_clip.txt'))
