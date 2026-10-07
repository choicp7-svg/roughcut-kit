# -*- coding: utf-8 -*-
"""
캡컷 러프컷 + 자막 파이프라인 실행기

  python3 run.py check
      환경 확인 (캡컷 폴더, 폰트, 최근 프로젝트)

  python3 run.py analyze --project 0814 [--video /경로/원본.mp4]
      자동자막 읽고 → 발화구간 분석 → 리싱크 → 반복테이크/슬레이트/조각 제거
      → review.json 저장 + 결과 출력.  ※ 텍스트 교정은 이 단계 다음에 Claude가 한다.

  python3 run.py build --project 0814 --cues final.json --preset 치상_그림자
      교정된 자막으로 러프컷 + 자막 트랙을 얹은 새 프로젝트 생성
"""
import os, sys, json, uuid, shutil, glob, argparse, statistics as st, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env, capcut_kit as ck, pipeline as pl

def load_cues(draft):
    idx = ck.index(draft); tr = ck.caption_track(draft)
    if not tr: return []
    out = []
    for s in sorted(tr['segments'], key=lambda x: x['target_timerange']['start']):
        m = idx[s['material_id']][1]
        t = (json.loads(m.get('content') or '{}').get('text') or '').strip()
        if not t: continue
        a = s['target_timerange']['start']/1e6
        out.append([round(a,3), round(a + s['target_timerange']['duration']/1e6, 3), t])
    return out

def source_video(draft, root):
    """프로젝트가 참조하는 원본 영상을 찾는다.
    직접 실행이면 프로젝트에 적힌 경로를 그대로 쓰고, Cowork면 연결된 폴더 안에서 파일명으로 찾는다."""
    cands = [v.get('path') for v in draft['materials'].get('videos', []) if v.get('path')]
    for p in cands:
        p = p.replace('\\', '/')
        if os.path.exists(p): return p
    if not env.is_mounted(root): return None
    for p in cands:
        base = os.path.basename(p.replace('\\','/'))
        for d in glob.glob(os.path.expanduser("~/mnt/*")):
            if os.path.basename(d).lower() == "capcut": continue   # 캡컷 캐시 폴더는 건너뜀 (느림)
            for hit in glob.glob(d + "/**/" + base, recursive=True):
                return hit
    return None

def cmd_check(a):
    print(json.dumps(env.describe(), ensure_ascii=False, indent=1))

def cmd_analyze(a):
    root = env.find_draft_root(); assert root, "캡컷 폴더를 못 찾음 — 폴더 접근 권한 필요"
    P = os.path.join(root, a.project)
    d = ck.load(P + "/draft_content.json")
    cues = load_cues(d)
    assert cues, "자막 트랙이 없음 — 캡컷에서 [자동 자막] 먼저 실행해줘"
    vid = a.video or source_video(d, root)
    print("프로젝트 %s | 자동자막 %d줄 | 원본 %s" % (a.project, len(cues), vid or "못 찾음"))
    if not vid:
        print("  ! 원본 영상을 못 찾아서 발화 분석 없이 자막 시간만으로 진행한다. --video 로 경로를 넘기면 정확해진다.")

    segs = []; fine = []
    if vid:
        wav = pl.extract_wav(vid)
        e, hop, total = pl.envelope(wav)
        segs_src = pl.speech_segments2(e, hop, sens=a.sens)
        vt = ck.main_video_track(d)
        tm = pl.TimeMap(vt['segments'])
        segs = tm.map_segments(segs_src) if len(vt['segments']) > 1 else segs_src
        fine_src = pl.speech_segments(e, hop, min_dur=0.08, merge_gap=0.06)
        fine = tm.map_segments(fine_src) if len(vt['segments']) > 1 else fine_src
        on = [s for s, _ in segs]
        def rate(cs):
            er = [min(on, key=lambda o: abs(o-c[0]))-c[0] for c in cs]
            er = [x for x in er if abs(x) < 1.2]
            return 100*sum(1 for x in er if abs(x) > 0.1)/max(1, len(er))
        before = rate(cues)
        cues = pl.snap_cues(cues, segs, max_shift=a.max_shift)
        print("발화 %d구간 / 리싱크: 어긋남 %.0f%% → %.0f%%" % (len(segs), before, rate(cues)))

    cues, d0 = pl.drop_slate(cues)
    cues, d1 = pl.drop_false_starts(cues)
    cues, d2, _ = pl.drop_retakes(cues)
    cues, d3 = pl.drop_false_starts(cues)
    cues, d4, _ = pl.drop_retakes(cues)
    if a.fillers != "off":
        cues, d5 = pl.strip_fillers(cues, aggressive=(a.fillers == "hard"))
    else: d5 = []
    print("제거: 슬레이트 %d / 조각 %d / 반복테이크 %d / 필러 %d  →  %d줄"
          % (len(d0), len(d1)+len(d3), len(d2)+len(d4), len(d5), len(cues)))
    out = {"project": a.project, "video": vid, "segs": [[round(x,2), round(y,2)] for x,y in segs],
           "fine": [[round(x,2), round(y,2)] for x,y in (fine if vid else [])],
           "cues": [[round(x,3), round(y,3), t] for x,y,t in cues]}
    p = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "review.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("저장:", p)
    for i,(x,y,t) in enumerate(cues): print("[%03d] %7.2f-%7.2f  %s" % (i,x,y,t))

def cmd_build(a):
    root = env.find_draft_root(); assert root
    P = os.path.join(root, a.project)
    cues = json.load(open(a.cues, encoding="utf-8"))
    if isinstance(cues, dict): cues = cues["cues"]
    cues = [[float(x), float(y), t] for x, y, t in cues]

    segs = json.load(open(a.segs, encoding="utf-8"))["segs"] if a.segs else []
    segs = [(float(x), float(y)) for x, y in segs]
    total = max([y for _, y in segs] + [c[1] for c in cues]) + 5
    keep = pl.rough_cut_from_speech(cues, segs, total, a.pad_in, a.pad_out, a.max_gap)
    fine = json.load(open(a.segs, encoding="utf-8")).get("fine") if a.segs else None
    if fine:
        fine = [(float(x), float(y)) for x, y in fine]
        keep = pl.tighten(keep, fine, a.pad_in/2, a.pad_out*0.7, a.min_pause)
        d0, runs = pl.dead_air(keep, fine)
        print("  컷 내부 무음 %.1fs (%.0f%%), 0.2초 초과 구간 %d곳"
              % (d0, 100*d0/max(1e-9, sum(e-s for s, e in keep)), sum(1 for x in runs if x > 0.2)))

    d = ck.load(P + "/draft_content.json")
    if a.cut:
        new_len = ck.apply_cuts(d, keep)
        cues = pl.remap(cues, keep)
        d['duration'] = int(round(new_len*1e6))
    if not a.no_resplit: cues = pl.resplit(cues, gap_frames=a.gap_frames)
    if a.gap_frames == 0: pl.butt_join(cues)

    name = a.name or (a.project + "_러프컷")
    DST = os.path.join(root, name)
    os.makedirs(DST, exist_ok=True)
    for f in ["draft_meta_info.json","draft_settings","draft_virtual_store.json",
              "draft_agency_config.json","draft_biz_config.json","key_value.json",
              "timeline_layout.json","performance_opt_info.json",
              "attachment_pc_common.json","draft_cover.jpg"]:
        if os.path.exists(P+"/"+f): shutil.copy(P+"/"+f, DST+"/"+f)

    ck.set_captions(d, [{"start":x,"end":y,"text":t} for x,y,t in cues],
                    ck.resolve_preset(a.preset, root))
    fold = env.project_win_path(root, name)
    d["id"] = str(uuid.uuid4()).upper(); d["path"] = fold
    ck.save(d, DST + "/draft_content.json")
    moved = ck.clear_timeline_cache(DST, root)     # 같은 이름으로 다시 만들 때 캡컷 캐시가 옛 타임라인을 물고 있지 않게
    if moved: print("  캡컷 캐시 정리: %s" % ", ".join(moved))
    m = json.load(open(DST+"/draft_meta_info.json", encoding="utf-8"))
    m["draft_name"] = name; m["draft_id"] = str(uuid.uuid4()).upper(); m["draft_fold_path"] = fold
    json.dump(m, open(DST+"/draft_meta_info.json","w",encoding="utf-8"), ensure_ascii=False)

    gaps = [round(cues[i+1][0]-cues[i][1],4) for i in range(len(cues)-1)]
    print("생성: %s" % name)
    if env.MISSING_FONTS:
        print("  ! 이 PC에 없는 폰트라 캡컷 기본 폰트로 대체함: %s  (캡컷에서 자막 전체 선택 → 폰트만 바꾸면 됨)"
              % ", ".join(env.MISSING_FONTS))
    print("  컷 %d개 / 길이 %.1fs / 자막 %d줄 / 길이중앙 %.2fs / 간격 %s"
          % (len(keep), sum(e-s for s,e in keep), len(cues),
             st.median([y-x for x,y,_ in cues]),
             collections.Counter([g for g in gaps if g<0.3]).most_common(1)))

ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("check").set_defaults(func=cmd_check)
p = sub.add_parser("analyze"); p.set_defaults(func=cmd_analyze)
p.add_argument("--project", required=True); p.add_argument("--video")
p.add_argument("--out"); p.add_argument("--sens", type=float, default=0.12)
p.add_argument("--max-shift", dest="max_shift", type=float, default=0.45)
p.add_argument("--fillers", choices=["off","safe","hard"], default="safe")
p = sub.add_parser("build"); p.set_defaults(func=cmd_build)
p.add_argument("--project", required=True); p.add_argument("--cues", required=True)
p.add_argument("--preset", default="치상_그림자"); p.add_argument("--name")
p.add_argument("--max-gap", dest="max_gap", type=float, default=0.25)
p.add_argument("--pad-in", dest="pad_in", type=float, default=0.06)
p.add_argument("--pad-out", dest="pad_out", type=float, default=0.10)
p.add_argument("--gap-frames", dest="gap_frames", type=int, default=0)
p.add_argument("--segs")
p.add_argument("--min-pause", dest="min_pause", type=float, default=0.10)
p.add_argument("--no-resplit", dest="no_resplit", action="store_true", default=False)
p.add_argument("--no-cut", dest="cut", action="store_false", default=True)
a = ap.parse_args(); a.func(a)
