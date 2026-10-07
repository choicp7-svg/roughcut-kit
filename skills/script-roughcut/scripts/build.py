#!/usr/bin/env python3
"""edl.json 의 컷 목록으로 프리미어용 XML(+SRT)과 캡컷 프로젝트를 만든다.

    python3 build.py <edl.json>                 # 프리미어 XML + SRT (edl.json 옆에 생성)
    python3 build.py <edl.json> --capcut        # 캡컷 프로젝트도 생성 (캡컷을 종료한 상태에서)

프리미어와 캡컷은 같은 프레임 번호에서 잘린다 (원본 클립의 fps 기준).
"""
import argparse, copy, glob, json, os, shutil, subprocess, sys, time, uuid
from urllib.parse import quote
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import FF, frames, load_edl, probe

ap = argparse.ArgumentParser()
ap.add_argument('edl')
ap.add_argument('--capcut', action='store_true', help='캡컷 프로젝트도 만든다')
ap.add_argument('--capcut-root', help='캡컷 프로젝트 저장 위치 (기본: CAPCUT_DRAFT_ROOT 환경변수 또는 자동 탐지)')
ap.add_argument('--capcut-template', help='형식을 본뜰 기존 캡컷 프로젝트 이름 (기본: 가장 최근 프로젝트)')
ap.add_argument('--overwrite', action='store_true', help='같은 이름의 캡컷 프로젝트가 있어도 다시 쓴다')
args = ap.parse_args()

NAME, SRC, CUTS = load_edl(args.edl)
HERE = os.path.dirname(os.path.abspath(args.edl))
INFO = {}
for c in CUTS:
    if 'clip' in c and c['clip'] not in INFO:
        INFO[c['clip']] = probe(os.path.join(SRC, c['clip']))
first = INFO[next(c['clip'] for c in CUTS if 'clip' in c)]
FPSQ = first['fps']
FPS = float(FPSQ)
TB, NTSC = round(FPS), FPSQ.denominator != 1
W, H, SR = first['w'], first['h'], first['sr']
for name, i in INFO.items():
    if i['fps'] != FPSQ:
        print(f'! {name} 의 fps({float(i["fps"]):.3f})가 첫 클립({FPS:.3f})과 다릅니다. 컷 위치를 확인하세요.', file=sys.stderr)


def srt_time(t):
    ms = int(round(t * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


# ---------------------------------------------------------------- 프리미어 XML (Final Cut 7 XML)
def build_premiere():
    rate = f'<rate><timebase>{TB}</timebase><ntsc>{"TRUE" if NTSC else "FALSE"}</ntsc></rate>'

    def timecode(tc=None):
        s, f = '00:00:00:00', 0
        if tc:
            h, m, sec, fr = tc
            s, f = f'{h:02d}:{m:02d}:{sec:02d}:{fr:02d}', ((h * 60 + m) * 60 + sec) * TB + fr
        return f'<timecode>{rate}<string>{s}</string><frame>{f}</frame><displayformat>NDF</displayformat></timecode>'

    achar = f'<samplecharacteristics><depth>16</depth><samplerate>{SR}</samplerate></samplecharacteristics>'

    def vchar(w, h):
        return (f'<samplecharacteristics>{rate}<width>{w}</width><height>{h}</height><anamorphic>FALSE</anamorphic>'
                f'<pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance></samplecharacteristics>')

    order, seen = list(INFO), set()

    def file_xml(c):
        k = order.index(c) + 1
        if c in seen:
            return f'<file id="file-{k}"/>'
        seen.add(c)
        i = INFO[c]
        return (f'<file id="file-{k}"><name>{escape(c)}</name><pathurl>file://localhost{quote(os.path.join(SRC, c))}</pathurl>'
                f'{rate}<duration>{round(i["dur"] * FPS)}</duration>{timecode(i["tc"])}<media><video>{vchar(i["w"], i["h"])}</video>'
                f'<audio>{achar}<channelcount>2</channelcount></audio></media></file>')

    v, a, markers, cues, pos, n = [], [[], []], [], [], 0, 0
    for c in CUTS:
        if 'scene' in c:
            markers.append(f'<marker><comment></comment><name>{escape(c["scene"])}</name><in>{pos}</in><out>-1</out></marker>')
            continue
        clip = c['clip']
        fi, fo = frames(c, INFO[clip])
        d, total = fo - fi, round(INFO[clip]['dur'] * FPS)
        n += 1
        ids = [f'clipitem-{3 * n - 2}', f'clipitem-{3 * n - 1}', f'clipitem-{3 * n}']
        links = ''.join(
            f'<link><linkclipref>{i}</linkclipref><mediatype>{"video" if k == 0 else "audio"}</mediatype>'
            f'<trackindex>{max(k, 1)}</trackindex><clipindex>{n}</clipindex>{"<groupindex>1</groupindex>" if k else ""}</link>'
            for k, i in enumerate(ids))
        common = (f'<masterclipid>masterclip-{order.index(clip) + 1}</masterclipid><name>{escape(clip)}</name>'
                  f'<enabled>TRUE</enabled><duration>{total}</duration>{rate}<start>{pos}</start><end>{pos + d}</end>'
                  f'<in>{fi}</in><out>{fo}</out>')
        v.append(f'<clipitem id="{ids[0]}">{common}<alphatype>none</alphatype>{file_xml(clip)}{links}</clipitem>')
        for k in (0, 1):
            a[k].append(f'<clipitem id="{ids[k + 1]}" premiereChannelType="stereo">{common}{file_xml(clip)}'
                        f'<sourcetrack><mediatype>audio</mediatype><trackindex>{k + 1}</trackindex></sourcetrack>{links}</clipitem>')
        if c.get('text'):
            cues.append((pos / FPS + 0.15, (pos + d) / FPS - 0.1, c['text']))
        pos += d

    trk = '<enabled>TRUE</enabled><locked>FALSE</locked>'
    outs = ''.join(f'<group><index>{k}</index><numchannels>1</numchannels><downmix>0</downmix><channel><index>{k}</index>'
                   f'</channel></group>' for k in (1, 2))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">\n<sequence id="sequence-1">'
           f'<duration>{pos}</duration>{rate}<name>{escape(NAME)}</name><media>'
           f'<video><format>{vchar(W, H)}</format><track>{"".join(v)}{trk}</track></video>'
           f'<audio><numOutputChannels>2</numOutputChannels><format>{achar}</format><outputs>{outs}</outputs>'
           + ''.join(f'<track PannerCurrentValue="0.5" PannerName="Balance" currentExplodedTrackIndex="{k}" '
                     f'totalExplodedTrackCount="2" premiereTrackType="Stereo">{"".join(a[k])}{trk}'
                     f'<outputchannelindex>{k + 1}</outputchannelindex></track>' for k in (0, 1))
           + f'</audio></media>{timecode()}{"".join(markers)}</sequence>\n</xmeml>\n')
    out = os.path.join(HERE, NAME)
    open(out + '.xml', 'w', encoding='utf-8').write(xml)
    with open(out + '.srt', 'w', encoding='utf-8') as f:
        for i, (s, e, t) in enumerate(cues, 1):
            f.write(f'{i}\n{srt_time(s)} --> {srt_time(e)}\n{t}\n\n')
    print(f'프리미어: {n}컷, {pos / FPS:.1f}초 -> {out}.xml + .srt')


# ---------------------------------------------------------------- 캡컷 프로젝트
def build_capcut():
    import capcut_kit as ck
    US = 1_000_000
    import env
    root = args.capcut_root or env.find_draft_root()
    if not root:
        raise SystemExit('캡컷 프로젝트 폴더를 못 찾았습니다. --capcut-root 또는 환경변수 CAPCUT_DRAFT_ROOT 로 지정하세요.')
    running = subprocess.run(['pgrep', '-f', 'CapCut.app/Contents/MacOS'], capture_output=True).stdout.strip()
    if running and not os.environ.get('SCRIPT_ROUGHCUT_TEST'):      # 테스트용 임시 폴더에 쓸 때만 건너뛴다
        raise SystemExit('캡컷이 실행 중입니다. 완전히 종료한 뒤 다시 실행하세요.')
    dst = os.path.join(root, NAME)
    if os.path.exists(dst) and not args.overwrite:
        raise SystemExit(f'캡컷 프로젝트가 이미 있습니다: {dst}\n  edl.json 의 name 을 바꾸거나 --overwrite 를 붙이세요.')

    def f2us(n):
        return round(n * US / FPS)

    def nid():
        return str(uuid.uuid4()).upper()

    # 형식을 본뜰 실제 캡컷 프로젝트: 메인 비디오 트랙(flag 0)에 영상 세그먼트가 있는 가장 최근 것
    cands = ([os.path.join(root, args.capcut_template, 'draft_content.json')] if args.capcut_template else
             sorted(glob.glob(os.path.join(root, '*', 'draft_content.json')), key=os.path.getmtime, reverse=True))
    tpl = None
    for path in cands[:30]:
        try:
            d0 = ck.load(path)
            by_id = {m['id']: (k, m) for k, l in d0['materials'].items() if isinstance(l, list)
                     for m in l if isinstance(m, dict) and 'id' in m}
            seg = next(t for t in d0['tracks'] if t['type'] == 'video' and t.get('flag') == 0)['segments'][0]
            if by_id[seg['material_id']][1].get('type') == 'video':
                tpl, proto_seg, proto_mat, tpl_dir = d0, seg, by_id[seg['material_id']][1], os.path.dirname(path)
                break
        except Exception:
            continue
    if tpl is None:
        raise SystemExit(f'본뜰 캡컷 프로젝트를 찾지 못했습니다: {root}\n  캡컷에서 영상 하나를 올린 프로젝트를 만든 뒤 다시 실행하세요.')
    keep = ('speeds', 'placeholder_infos', 'canvases', 'sound_channel_mappings', 'material_colors', 'vocal_separations')
    proto_refs = [by_id[r] for r in proto_seg['extra_material_refs'] if r in by_id and by_id[r][0] in keep]

    d = copy.deepcopy(tpl)
    d['id'], d['name'], d['tracks'] = nid(), NAME, []
    d['materials'] = {k: ([] if isinstance(v, list) else v) for k, v in d['materials'].items()}
    if isinstance(d.get('keyframes'), dict):
        d['keyframes'] = {k: [] for k in d['keyframes']}
    for k in ('time_marks', 'cover', 'retouch_cover', 'extra_info', 'group_container'):
        if k in d:
            d[k] = None
    if 'relationships' in d:
        d['relationships'] = []
    ratio = {(16, 9): '16:9', (9, 16): '9:16', (1, 1): '1:1', (4, 3): '4:3'}.get(
        (W // __import__('math').gcd(W, H), H // __import__('math').gcd(W, H)), 'original')
    d['canvas_config'] = {'ratio': ratio, 'width': W, 'height': H, 'background': None}
    d['fps'] = round(FPS, 2) if NTSC else float(TB)
    d['create_time'] = d['update_time'] = int(time.time())

    mats, segs, cues, pos = {}, [], [], 0
    for c in CUTS:
        if 'scene' in c:
            continue
        clip, i = c['clip'], INFO[c['clip']]
        if clip not in mats:
            m = copy.deepcopy(proto_mat)
            m.update(id=nid(), path=os.path.join(SRC, clip), material_name=clip, duration=int(round(i['dur'] * US)),
                     width=i['w'], height=i['h'], type='video', has_audio=i['has_audio'],
                     local_material_id=str(uuid.uuid4()))
            m['crop'] = {'lower_left_x': 0.0, 'lower_left_y': 1.0, 'lower_right_x': 1.0, 'lower_right_y': 1.0,
                         'upper_left_x': 0.0, 'upper_left_y': 0.0, 'upper_right_x': 1.0, 'upper_right_y': 0.0}
            mats[clip] = m
            d['materials']['videos'].append(m)
        fi, fo = frames(c, i)
        s0, dur = f2us(fi), f2us(fo) - f2us(fi)
        t0, tdur = f2us(pos), f2us(pos + fo - fi) - f2us(pos)          # pos = 타임라인 누적 프레임
        refs = []
        for kind, rm in proto_refs:                                    # 세그먼트마다 보조 material 을 따로 둔다
            r = copy.deepcopy(rm)
            r['id'] = nid()
            if kind == 'speeds':
                r['speed'] = 1.0
            d['materials'][kind].append(r)
            refs.append(r['id'])
        s = copy.deepcopy(proto_seg)
        s.update(id=nid(), material_id=mats[clip]['id'], extra_material_refs=refs, speed=1.0, volume=1.0,
                 last_nonzero_volume=1.0, visible=True, reverse=False, common_keyframes=[], keyframe_refs=[],
                 source_timerange={'start': s0, 'duration': dur}, target_timerange={'start': t0, 'duration': tdur},
                 render_index=0, track_render_index=0, enable_hsl=False, enable_lut=False, enable_adjust=True)
        s['clip'] = {'scale': {'x': 1.0, 'y': 1.0}, 'rotation': 0.0, 'transform': {'x': 0.0, 'y': 0.0},
                     'flip': {'vertical': False, 'horizontal': False}, 'alpha': 1.0}
        segs.append(s)
        if c.get('text'):
            cues.append({'start': t0 / US + 0.15, 'end': (t0 + tdur) / US - 0.1, 'text': c['text']})
        pos += fo - fi
    d['tracks'].append({'id': nid(), 'type': 'video', 'flag': 0, 'attribute': 0, 'name': '', 'is_default_name': True,
                        'segments': segs})
    d['duration'] = total = f2us(pos)

    if cues:
        font_root = os.path.expanduser('~/Movies/CapCut/User Data/Projects/com.lveditor.draft')
        if H > W:                                                       # 세로: 릴스 기본 자막
            preset = ck.resolve_preset('치상_그림자', font_root)
        else:                                                           # 가로: 하단, 조금 작게
            preset = ck.resolve_preset('치상_외곽선', font_root)
            preset.update(y=-0.78, scale=1.0, size=7.0, font_size=7.0)
        ck.set_captions(d, cues, preset)

    os.makedirs(dst, exist_ok=True)
    for f in ('draft_settings', 'draft_agency_config.json', 'draft_biz_config.json', 'performance_opt_info.json',
              'attachment_pc_common.json'):
        if os.path.exists(os.path.join(tpl_dir, f)):
            shutil.copy(os.path.join(tpl_dir, f), os.path.join(dst, f))
    open(os.path.join(dst, 'key_value.json'), 'w').write('{}')
    d['path'] = dst
    ck.save(d, os.path.join(dst, 'draft_content.json'))
    ck.clear_timeline_cache(dst, root)                                  # 캡컷이 옛 타임라인 사본을 다시 쓰지 않게
    first_cut = next(c for c in CUTS if 'clip' in c)
    subprocess.run([FF, '-loglevel', 'error', '-y', '-ss', str((first_cut['in'] + first_cut['out']) / 2), '-i',
                    os.path.join(SRC, first_cut['clip']), '-frames:v', '1', '-vf', 'scale=640:-2',
                    os.path.join(dst, 'draft_cover.jpg')])
    meta = json.load(open(os.path.join(tpl_dir, 'draft_meta_info.json'), encoding='utf-8'))
    now = int(time.time() * US)
    meta.update(draft_name=NAME, draft_id=nid(), draft_fold_path=dst, draft_root_path=root,
                draft_json_file=os.path.join(dst, 'draft_content.json'), draft_cover='draft_cover.jpg',
                tm_duration=total, tm_draft_create=now, tm_draft_modified=now, draft_timeline_materials_size=0)
    for g in meta.get('draft_materials', []):
        g['value'] = []
    json.dump(meta, open(os.path.join(dst, 'draft_meta_info.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'캡컷: {len(segs)}컷, {total / US:.1f}초, 자막 {len(cues)}줄 -> {dst}  (본뜬 프로젝트: {os.path.basename(tpl_dir)})')


build_premiere()
if args.capcut:
    build_capcut()
