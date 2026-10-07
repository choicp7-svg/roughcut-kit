# -*- coding: utf-8 -*-
"""
효과음 자동 삽입 — 사용자가 자기 캡컷 프로젝트에서 실제로 써온 효과음을 학습해서 러프컷에 얹는다.

  python3 sfx.py profile [--limit 60] [--out sfx_profile.json]
      이 PC의 캡컷 프로젝트를 전부 훑어서, 효과음마다 (몇 번 썼는지 / 자막 시작·컷·강조자막과 얼마나 맞춰 넣는지 /
      어떤 자막에서 썼는지 예시 / 볼륨) 를 뽑아 sfx_profile.json 에 저장하고 요약을 출력한다.
      material·세그먼트 템플릿도 같이 저장하므로 apply 는 이 파일만 있으면 된다.

  python3 sfx.py apply --project 0904_러프컷 --plan sfx_plan.json [--profile sfx_profile.json]
      sfx_plan.json = [[초, "효과음 이름", 볼륨, 최대길이초 또는 null], ...]
      효과음 트랙(SFX_auto)을 새로 만들어 얹는다. 겹치는 소리는 트랙을 나눈다. 재실행하면 이전 SFX_auto 를 걷어내고 다시 넣는다.
      캡컷 캐시(Timelines/)를 치워서 캡컷이 바뀐 draft_content.json 을 다시 읽게 한다.

  python3 sfx.py captions --project 0904_러프컷
      계획 세울 때 볼 것: 결과 프로젝트의 자막 목록(시각·텍스트)과 컷 경계.
"""
import os, sys, json, glob, copy, uuid, shutil, argparse, statistics as st, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env, capcut_kit as ck

US = 1_000_000
TRACK_NAME = "SFX_auto"
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SET = os.path.join(SKILL_DIR, "references", "sfx_default_set.json")   # 치상 세트 (이름·역할·볼륨·템플릿)
ASSETS_DIR = os.path.join(SKILL_DIR, "assets", "sfx")                          # 치상 세트 소리 파일 (있으면 씀)

def load_default_set():
    try: return json.load(open(DEFAULT_SET, encoding='utf-8'))['entries']
    except Exception: return []

def nid(): return str(uuid.uuid4()).upper()

def _txt(m):
    try: return (json.loads(m.get('content') or '{}').get('text') or '').strip()
    except Exception: return ''

def _native(p):
    return (p or '').replace('\\', '/')

def _mount_path(native_path, root):
    """네이티브 경로(C:/Users/.../CapCut/...)를 지금 실행 환경에서 열 수 있는 경로로."""
    p = _native(native_path)
    if not env.is_mounted(root): return p
    base = env.app_base(root) or ''
    mnt_base = _native(root).split("/User Data/")[0]
    return p.replace(base, mnt_base) if base and p.startswith(base) else p

# ---------------------------------------------------------------- profile
def cmd_profile(a):
    root = env.find_draft_root(); assert root, "캡컷 폴더를 못 찾음"
    files = sorted(glob.glob(root + "/*/draft_content.json"), key=os.path.getmtime, reverse=True)[:a.limit]
    events = []; lib = {}; n_proj = 0; proj_with = 0
    for f in files:
        pdir = os.path.dirname(f); pname = os.path.basename(pdir)
        try: d = json.load(open(f, encoding='utf-8'))
        except Exception: continue
        n_proj += 1
        idx = ck.index(d)
        tracks = d.get('tracks', [])
        vt = ck.main_video_track(d)
        cuts = sorted(s['target_timerange']['start'] / US for s in vt['segments']) if vt else []
        caps = []; emph = []
        for t in tracks:
            if t['type'] != 'text': continue
            for s in t['segments']:
                m = idx.get(s['material_id'], (None, {}))[1]
                x = s['target_timerange']['start'] / US; y = x + s['target_timerange']['duration'] / US
                (caps if t.get('flag') == 1 else emph).append((x, y, _txt(m)))
        caps.sort(); emph.sort()
        total = d.get('duration', 0) / US
        got = 0
        for t in tracks:
            if t['type'] != 'audio' or t.get('name') == TRACK_NAME: continue   # 이 스크립트가 넣은 건 학습 대상에서 제외
            for s in t['segments']:
                m = idx.get(s['material_id'], (None, {}))[1]
                if m.get('type') != 'sound': continue
                got += 1
                x = s['target_timerange']['start'] / US
                cap_i = min(range(len(caps)), key=lambda i: abs(caps[i][0] - x)) if caps else None
                cap_d = (caps[cap_i][0] - x) if cap_i is not None else None
                cut_d = min((c - x for c in cuts), key=abs) if cuts else None
                em = min(emph, key=lambda r: abs(r[0] - x)) if emph else None
                sent_start = False
                if cap_i is not None:
                    prev_end = caps[cap_i - 1][1] if cap_i > 0 else -9
                    sent_start = cap_i == 0 or (caps[cap_i][0] - prev_end) > 0.25
                events.append(dict(project=pname, sfx=m.get('name'), t=round(x, 2),
                    dur=round(s['target_timerange']['duration'] / US, 2), vol=round(s.get('volume', 1.0), 2),
                    pos=round(x / total, 2) if total else None,
                    cap_delta=round(cap_d, 2) if cap_d is not None else None,
                    cap=caps[cap_i][2] if cap_i is not None else None,
                    cap_next=caps[cap_i + 1][2] if cap_i is not None and cap_i + 1 < len(caps) else None,
                    cut_delta=round(cut_d, 2) if cut_d is not None else None,
                    emph_delta=round(em[0] - x, 2) if em else None, emph=em[2] if em else None,
                    sent_start=sent_start))
                if m['name'] not in lib:
                    refs = [(idx[r][0], idx[r][1]) for r in s.get('extra_material_refs', []) if r in idx]
                    lib[m['name']] = dict(material=m, segment=s, refs=refs, project=pname, pdir=pdir)
        if got: proj_with += 1
    # 요약
    by = collections.defaultdict(list)
    for e in events: by[e['sfx']].append(e)
    def near(v, th): return v is not None and abs(v) <= th
    summary = []
    for name, ev in sorted(by.items(), key=lambda x: -len(x[1])):
        n = len(ev)
        summary.append(dict(name=name, count=n, projects=len(set(e['project'] for e in ev)),
            cap_align=round(100 * sum(near(e['cap_delta'], 0.12) for e in ev) / n),
            cut_align=round(100 * sum(near(e['cut_delta'], 0.12) for e in ev) / n),
            emph_align=round(100 * sum(near(e['emph_delta'], 0.15) for e in ev) / n),
            sentence_start=round(100 * sum(e['sent_start'] for e in ev) / n),
            pos_median=round(st.median([e['pos'] for e in ev if e['pos'] is not None] or [0]), 2),
            dur=round(st.median([e['dur'] for e in ev]), 2), vol=round(st.median([e['vol'] for e in ev]), 2),
            examples=[(e['cap'] or e['emph'] or '') for e in ev if (e['cap'] or e['emph'])][:6]))
    # 밀도: 효과음 쓴 프로젝트에서 초당 개수
    dens = []
    for p in set(e['project'] for e in events):
        pe = [e for e in events if e['project'] == p]
        tot = max([e['t'] for e in pe] + [1])
        dens.append(len(pe) / tot)
    profile = dict(draft_root=root, projects_scanned=n_proj, projects_with_sfx=proj_with, events=len(events),
                   sec_per_sfx=round(1 / st.median(dens), 1) if dens else None,
                   summary=summary, events_list=events,
                   lib={k: dict(material=v['material'], segment=v['segment'], refs=v['refs'],
                                project=v['project'], pdir=v['pdir']) for k, v in lib.items()})
    default = load_default_set(); roles = {e['name']: e['role'] for e in default}
    for x in summary: x['role_hint'] = roles.get(x['name'], '')
    profile['mode'] = 'default' if (a.set == '치상' or (a.set == 'auto' and not events)) else 'own'
    if profile['mode'] == 'default':
        # 효과음을 써본 적이 없는 사람(또는 --set 치상) → 치상 세트. 파일은 assets/캐시 중 있는 곳에서.
        profile['lib'] = {}; have = []; need = []
        for e in default:
            src = os.path.join(ASSETS_DIR, e['asset'])
            cached = _mount_path(e['material']['path'], root)
            ok = os.path.exists(src) or ('##_draftpath' not in e['material']['path'] and os.path.exists(cached))
            (have if ok else need).append(e['name'])
            profile['lib'][e['name']] = dict(material=e['material'], segment=e['segment'], refs=e['refs'],
                                             project='치상 세트', pdir='', asset=e['asset'])
        profile['sec_per_sfx'] = 3.0
        profile['summary'] = [dict(name=e['name'], count=0, projects=0, cap_align=100, cut_align=80, emph_align=0,
                                   sentence_start=0, pos_median=0.5, dur=round(e['duration'] / US, 2), vol=e['vol'],
                                   examples=[], role_hint=e['role'], available=(e['name'] in have)) for e in default]
        profile['default_missing'] = need
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "sfx_profile.json")
    json.dump(profile, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print("프로젝트 %d개 중 효과음 쓴 것 %d개 / 효과음 %d개 / 평소 밀도: %s초에 1개"
          % (n_proj, proj_with, len(events), profile['sec_per_sfx']))
    print("저장:", out)
    if profile['mode'] == 'default':
        print("\n! '치상 세트'(아워프로젝트 릴스 효과음 15개)로 간다%s. 밀도는 3초에 1개로 본다."
              % ("" if events else " — 효과음을 쓴 프로젝트가 없음"))
        print("%-4s %-52s %5s %-24s %s" % ("파일", "이름", "볼륨", "역할", ""))
        for x in profile['summary']:
            print("%-4s %-52s %5.2f %-24s" % ("있음" if x["available"] else "받음", x['name'][:52], x['vol'], x['role_hint']))
        if need:
            print("\n· 이 PC에 파일이 없는 소리 %d개는 캡컷이 effect_id 로 라이브러리에서 받아오게 두고 그냥 넣는다." % len(need))
            print("  혹시 캡컷에서 그 소리만 안 나면: [오디오 → 효과음] 검색창에 이름을 검색해서 아무 프로젝트에 한 번 넣어두면 된다.")
        return
    print("\n%-4s %-52s %5s %5s %5s %5s %5s %s" % ("횟수", "이름", "자막맞춤", "컷맞춤", "강조맞춤", "문장앞", "볼륨", "예시 자막 / 역할힌트"))
    for s in summary:
        print("%-4d %-52s %4d%% %4d%% %4d%% %4d%% %5.2f  %s%s" % (s['count'], s['name'][:52], s['cap_align'], s['cut_align'],
              s['emph_align'], s['sentence_start'], s['vol'], " | ".join(x[:14] for x in s['examples'][:4]),
              ("  [치상세트: %s]" % s['role_hint']) if s['role_hint'] else ""))

# ---------------------------------------------------------------- captions (계획용)
def cmd_captions(a):
    root = env.find_draft_root(); assert root
    d = ck.load(os.path.join(root, a.project, "draft_content.json"))
    idx = ck.index(d)
    vt = ck.main_video_track(d)
    cuts = sorted(s['target_timerange']['start'] / US for s in vt['segments']) if vt else []
    print("길이 %.2fs / 컷 경계: %s" % (d['duration'] / US, " ".join("%.2f" % c for c in cuts)))
    tr = ck.caption_track(d)
    for s in sorted(tr['segments'], key=lambda s: s['target_timerange']['start']):
        x = s['target_timerange']['start'] / US
        mark = "▌" if any(abs(c - x) < 0.1 for c in cuts) else " "
        print("%s %6.2f  %s" % (mark, x, _txt(idx[s['material_id']][1])))

# ---------------------------------------------------------------- apply
def cmd_apply(a):
    root = env.find_draft_root(); assert root
    prof_path = a.profile or os.path.join(os.path.dirname(os.path.abspath(__file__)), "sfx_profile.json")
    prof = json.load(open(prof_path, encoding='utf-8')); lib = prof['lib']
    plan = json.load(open(a.plan, encoding='utf-8'))
    missing = sorted(set(p[1] for p in plan if p[1] not in lib))
    assert not missing, "프로필에 없는 효과음: %s" % missing
    pdir = os.path.join(root, a.project); tpath = os.path.join(pdir, "draft_content.json")
    d = ck.load(tpath)
    mats = d['materials']
    for k in ["audios", "speeds", "placeholder_infos", "beats", "sound_channel_mappings", "vocal_separations"]:
        mats.setdefault(k, [])
    # 이전 SFX_auto 걷어내기 (트랙 + 그 트랙만 쓰던 material)
    old = [t for t in d['tracks'] if t['type'] == 'audio' and t.get('name') == TRACK_NAME]
    drop = set()
    for t in old:
        for s in t['segments']:
            drop.add(s['material_id']); drop.update(s.get('extra_material_refs', []))
    if drop:
        for k, v in mats.items():
            if isinstance(v, list): mats[k] = [m for m in v if not (isinstance(m, dict) and m.get('id') in drop)]
    d['tracks'] = [t for t in d['tracks'] if t not in old]

    def copy_in(src, fname):
        rel = "materials/audio/" + fname
        dst = os.path.join(pdir, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
        if not os.path.exists(dst): shutil.copy(src, dst)
        return env.project_native_path(root, a.project) + "/" + rel

    def resolve_path(m, entry):
        p = _native(m['path'])
        if entry.get('asset'):                                    # 치상 세트
            src = os.path.join(ASSETS_DIR, entry['asset'])
            if os.path.exists(src): return copy_in(src, entry['asset'])          # 스킬에 파일이 있으면 그걸 복사
            # 없으면 이 PC의 캡컷 캐시 경로를 적어둔다. 캡컷은 라이브러리 소리를 effect_id 로 알아보고
            # 경로를 자기 캐시로 다시 잡는다 (파일이 없으면 라이브러리에서 받아온다). 치상 PC에서 확인됨.
            base = env.app_base(root) or ''
            return (base + "/User Data/Cache/music/" + entry['asset']) if base else p
        if '##_draftpath_placeholder' in p:                       # 소스 프로젝트 안에 든 파일 → 복사
            rel = p.split('_##/')[-1]
            return copy_in(os.path.join(entry['pdir'], rel), os.path.basename(rel))
        if not os.path.exists(_mount_path(p, root)):
            raise SystemExit("효과음 파일이 없음: %s (%s)" % (m['name'], p))
        return p

    tracks = []
    def alloc(x, y):
        for tr in tracks:
            if all(not (x < e and s < y) for s, e in tr['_spans']): return tr
        tr = {"id": nid(), "type": "audio", "flag": 0, "attribute": 0, "name": TRACK_NAME,
              "is_default_name": False, "segments": [], "_spans": []}
        tracks.append(tr); return tr
    base_ri = max([s.get('track_render_index', 0) for t in d['tracks'] for s in t['segments']] or [0]) + 1
    end_limit = d['duration'] / US
    added = []
    for item in sorted(plan, key=lambda p: p[0]):
        t0, name, vol = item[0], item[1], item[2]; maxdur = item[3] if len(item) > 3 else None
        e = lib[name]; m = copy.deepcopy(e['material']); m['id'] = nid(); m['path'] = resolve_path(e['material'], e)
        mats['audios'].append(m)
        ref_ids = []
        for kind, r in e['refs']:
            r2 = copy.deepcopy(r); r2['id'] = nid(); mats.setdefault(kind, []).append(r2); ref_ids.append(r2['id'])
        dur = m['duration'] / US
        if maxdur: dur = min(dur, maxdur)
        if t0 + dur > end_limit: dur = max(0.1, end_limit - t0)
        s = copy.deepcopy(e['segment'])
        s.update({"id": nid(), "material_id": m['id'], "extra_material_refs": ref_ids,
                  "source_timerange": {"start": 0, "duration": int(round(dur * US))},
                  "target_timerange": {"start": int(round(t0 * US)), "duration": int(round(dur * US))},
                  "volume": vol, "last_nonzero_volume": vol, "render_index": 0,
                  "keyframe_refs": [], "common_keyframes": []})
        tr = alloc(t0, t0 + dur)
        s['track_render_index'] = base_ri + tracks.index(tr)
        tr['segments'].append(s); tr['_spans'].append((t0, t0 + dur))
        added.append((t0, name, round(dur, 2), vol))
    for tr in tracks:
        tr['segments'].sort(key=lambda s: s['target_timerange']['start']); del tr['_spans']
        d['tracks'].append(tr)
    ck.save(d, tpath)
    moved = ck.clear_timeline_cache(pdir, root)
    print("효과음 %d개 / 트랙 %d개 → %s  (캐시 정리: %s)" % (len(added), len(tracks), a.project, ", ".join(moved) or "없음"))
    for x in added: print("  %6.2fs  %-50s %.2fs vol %.2f" % x)

ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest="cmd", required=True)
p = sub.add_parser("profile"); p.set_defaults(func=cmd_profile)
p.add_argument("--limit", type=int, default=60); p.add_argument("--out")
p.add_argument("--set", choices=["auto", "own", "치상"], default="auto",
               help="auto=이력 있으면 본인 것, 없으면 치상 세트 / own=본인 것만 / 치상=무조건 치상 세트")
p = sub.add_parser("captions"); p.set_defaults(func=cmd_captions); p.add_argument("--project", required=True)
p = sub.add_parser("apply"); p.set_defaults(func=cmd_apply)
p.add_argument("--project", required=True); p.add_argument("--plan", required=True); p.add_argument("--profile")
a = ap.parse_args(); a.func(a)
