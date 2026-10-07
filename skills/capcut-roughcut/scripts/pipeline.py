# -*- coding: utf-8 -*-
"""
캡컷 자동자막 후처리 파이프라인 v2 — 표준 라이브러리만 사용
리싱크 / 필러 제거 / 반복테이크 정리 / 리듬 재분할 / 러프컷
"""
import wave, array, math, re, subprocess, tempfile, difflib

FPS = 30.0
FR  = 1.0/FPS

def q(t):                      # 프레임 그리드에 스냅
    return round(round(t*FPS)/FPS, 9)

# ---------------------------------------------------------------- 오디오/VAD
def extract_wav(video, out=None, sr=16000):
    out = out or tempfile.mktemp(suffix=".wav")
    subprocess.run(["ffmpeg","-y","-v","error","-i",video,"-vn","-ac","1",
                    "-ar",str(sr),out], check=True)
    return out

def envelope(wav_path, hop_s=0.02):
    w = wave.open(wav_path); sr = w.getframerate()
    pcm = array.array('h'); pcm.frombytes(w.readframes(w.getnframes()))
    hop = int(sr*hop_s); env=[]
    for i in range(0, len(pcm)-hop, hop):
        s=0
        for v in pcm[i:i+hop]: s += v*v
        env.append(math.sqrt(s/hop))
    return env, hop_s, len(pcm)/sr

def speech_segments(env, hop_s, sens=0.12, min_dur=0.12, merge_gap=0.20):
    srt=sorted(env)
    noise=srt[int(len(srt)*0.10)]; peak=srt[int(len(srt)*0.95)]
    th=noise+(peak-noise)*sens
    segs=[]; on=False; st=0
    for i,v in enumerate(env):
        if not on and v>th: on=True; st=i
        elif on and v<=th:
            if (i-st)*hop_s>=min_dur: segs.append([st*hop_s, i*hop_s])
            on=False
    if on: segs.append([st*hop_s, len(env)*hop_s])
    out=[]
    for s,e in segs:
        if out and s-out[-1][1] < merge_gap: out[-1][1]=e
        else: out.append([s,e])
    return [(a,b) for a,b in out]

# ---------------------------------------------------------------- 시간축 매핑
class TimeMap:
    """타임라인 시간 <-> 원본 영상 시간. 이미 컷이 들어간 프로젝트 대응."""
    def __init__(self, video_track_segments):
        self.sp=[]
        for s in sorted(video_track_segments, key=lambda x:x['target_timerange']['start']):
            src=s.get('source_timerange') or {"start":0,"duration":s['target_timerange']['duration']}
            self.sp.append((s['target_timerange']['start']/1e6,
                            (s['target_timerange']['start']+s['target_timerange']['duration'])/1e6,
                            src['start']/1e6))
    def to_source(self, t):
        for a,b,s0 in self.sp:
            if a-1e-6 <= t <= b+1e-6: return s0 + (t-a)
        return None
    def to_timeline(self, ts):
        for a,b,s0 in self.sp:
            if s0-1e-6 <= ts <= s0+(b-a)+1e-6: return a + (ts-s0)
        return None
    def map_segments(self, segs):
        """원본 시간축 발화구간 → 타임라인 시간축"""
        out=[]
        for a,b,s0 in self.sp:
            for (ss,se) in segs:
                x,y = max(ss,s0), min(se, s0+(b-a))
                if y-x > 0.05: out.append((a+(x-s0), a+(y-s0)))
        out.sort()
        mg=[]
        for s,e in out:
            if mg and s-mg[-1][1] < 0.05: mg[-1][1]=e
            else: mg.append([s,e])
        return [(a,b) for a,b in mg]

# ---------------------------------------------------------------- 리싱크
def snap_cues(cues, segs, max_shift=0.45):
    """자막 줄의 시작/끝을 실제 발화 경계로 스냅. 단조 증가 보장."""
    bounds=sorted({round(x,3) for s,e in segs for x in (s,e)})
    out=[]; last=-1e9
    for (a,b,t) in cues:
        cand=[x for x in bounds if abs(x-a)<=max_shift and x>=last]
        na = min(cand, key=lambda x: abs(x-a)) if cand else max(a,last)
        nb = b + (na-a)
        if nb <= na+0.15: nb = na+0.15
        out.append([q(na), q(nb), t]); last=na
    return out

# ---------------------------------------------------------------- 반복 테이크
def _norm(s):
    return re.sub(r'[^0-9A-Za-z가-힣]', '', s)

SLATE_RE = re.compile(r'^(카메라\s*롤(링|리)?|롤링|롤리|액션|하나\s*둘(\s*셋)?|한\s*번\s*더|다시(\s*(할게|갈게|한번))?'
                      r'|컷(\s*오케이(요)?)?|오케이(요)?|오케|좋아요?|됐어요?|잠깐만요?|아니다|아\s*잠깐)$')

def drop_slate(cues, max_len=8):
    """슬레이트·디렉션 제거: '카메라 롤리', '하나 둘', '한 번 더', '컷 오케이' 같은 짧은 진행 멘트."""
    kept=[]; cut=[]
    for a,b,t in cues:
        n=_norm(t)
        if len(n) <= max_len and SLATE_RE.match(re.sub(r'\s+','',t.strip())) :
            cut.append((a,b)); continue
        kept.append([a,b,t])
    return kept, cut

def drop_false_starts(cues, look=3, sim=0.8):
    """말하다 만 조각 제거: 짧은 줄이 바로 뒤 줄(들)의 앞부분과 같으면 앞의 조각을 버린다."""
    n=len(cues); drop=set()
    for i in range(n):
        a=_norm(cues[i][2])
        if len(a) < 2: continue
        for j in range(i+1, min(i+1+look, n)):
            b=_norm(cues[j][2])
            if len(b) <= len(a): continue
            head=b[:len(a)+1]
            if difflib.SequenceMatcher(None, a, head).ratio() >= sim:
                drop.add(i); break
    kept=[c for i,c in enumerate(cues) if i not in drop]
    cut=[(cues[i][0], cues[i][1]) for i in sorted(drop)]
    return kept, cut

def drop_retakes(cues, sim=0.82, window=8, min_len=6, span=3):
    """같은 말을 여러 번 한 구간 → 마지막 테이크만 남김.
    한 줄씩만이 아니라 연속 1~span줄을 묶어서도 비교한다 (한 문장이 여러 줄로 쪼개진 테이크 대응)."""
    n=len(cues); drop=set()
    i=0
    while i < n:
        if i in drop: i+=1; continue
        hit=False
        for k in range(span, 0, -1):
            if i+k > n: continue
            a="".join(_norm(c[2]) for c in cues[i:i+k])
            if len(a) < min_len: continue
            for j in range(i+k, min(i+k+window, n)):
                if j in drop: continue
                # 같은 줄 수(k) 또는 그 ±1 로 묶어 비교
                for kk in (k, k+1, max(1,k-1)):
                    if j+kk > n: continue
                    b="".join(_norm(c[2]) for c in cues[j:j+kk])
                    if len(b) < min_len: continue
                    if difflib.SequenceMatcher(None,a,b).ratio() >= sim:
                        for x in range(i, j): drop.add(x)      # 앞엣것 버림
                        hit=True; break
                if hit: break
            if hit: break
        i+=1
    kept=[c for i,c in enumerate(cues) if i not in drop]
    cutr=[(cues[i][0], cues[i][1]) for i in sorted(drop)]
    return kept, cutr, len(drop)

# ---------------------------------------------------------------- 필러
FILLER_SAFE = {"어","음","으","엄","어어","음음","흠","아"}
FILLER_HARD = FILLER_SAFE | {"그","저","뭐","이제","약간","그니까","그러니까"}

def strip_fillers(cues, aggressive=False):
    pool = FILLER_HARD if aggressive else FILLER_SAFE
    out=[]; cut=[]
    for a,b,t in cues:
        toks=[w for w in t.split() if _norm(w) not in pool]
        if not toks:
            cut.append((a,b)); continue
        out.append([a,b," ".join(toks)])
    return out, cut

# ---------------------------------------------------------------- 재분할
END_RE = re.compile(r'(요|다|까|죠|네|잖아|는데|니까|세요|습니다)[.?!]?$')

def resplit(cues, max_chars=16, soft_chars=11, max_dur=1.9, min_dur=0.45,
            gap_frames=2, pause_break=0.35):
    """릴스 자막 리듬으로 재구성: 10자 내외 / 1.2초 / 줄 사이 딱 붙임(기본 0프레임)"""
    gap = gap_frames*FR
    # 1) 짧은 줄 병합
    merged=[]
    for a,b,t in cues:
        if merged:
            pa,pb,pt = merged[-1]
            newlen = len(pt)+1+len(t)
            short_prev = (pb-pa) < min_dur
            if (a-pb) <= pause_break and (b-pa) <= max_dur \
               and (newlen <= soft_chars or (short_prev and newlen <= max_chars)) \
               and not (END_RE.search(pt) and not short_prev):
                merged[-1]=[pa,b,pt+" "+t]; continue
        merged.append([a,b,t])
    # 2) 긴 줄 분할 (어절 경계, 글자수 비례 시간 배분)
    out=[]
    for a,b,t in merged:
        if len(t) <= max_chars and (b-a) <= max_dur:
            out.append([a,b,t]); continue
        toks=t.split(); chunks=[]; cur=""
        for w in toks:
            if cur and len(cur)+1+len(w) > max_chars: chunks.append(cur); cur=w
            else: cur = (cur+" "+w) if cur else w
        if cur: chunks.append(cur)
        if len(chunks)>1 and len(chunks[-1])<4:
            chunks[-2]+=" "+chunks[-1]; chunks.pop()
        tot=sum(len(c) for c in chunks) or 1
        cursor=a
        for i,c in enumerate(chunks):
            d=(b-a)*len(c)/tot
            e=b if i==len(chunks)-1 else cursor+d
            out.append([q(cursor), q(e), c]); cursor=e
    # 3) 간격 정규화: 2프레임, 단 원래 크게 벌어진 곳(무음)은 유지
    for i in range(len(out)-1):
        space = out[i+1][0]-out[i][1]
        if space < 0.30:
            out[i][1] = q(max(out[i][0]+0.2, out[i+1][0]-gap))
    # 4) 너무 짧은 줄은 앞줄에 흡수
    fin=[]
    for a,b,t in out:
        if fin and (b-a) < min_dur and len(fin[-1][2])+1+len(t) <= max_chars \
           and (b-fin[-1][0]) <= max_dur+0.3:
            fin[-1][1]=b; fin[-1][2]=fin[-1][2]+" "+t; continue
        fin.append([a,b,t])
    for i in range(len(fin)-1):
        space = fin[i+1][0]-fin[i][1]
        if space < 0.30:
            fin[i][1] = q(max(fin[i][0]+0.2, fin[i+1][0]-gap))
    return [[q(a),q(b),t] for a,b,t in fin if b-a >= 0.25]

# ---------------------------------------------------------------- 러프컷
def rough_cut_ranges(segs, total, pad_in=0.12, pad_out=0.20,
                     max_gap=0.45, extra_cuts=None):
    keep=[]
    for s,e in segs:
        a=max(0,s-pad_in); b=min(total,e+pad_out)
        if keep and a-keep[-1][1] <= max_gap: keep[-1][1]=b
        else: keep.append([a,b])
    for (cs,ce) in (extra_cuts or []):
        nk=[]
        for a,b in keep:
            if ce<=a or cs>=b: nk.append([a,b]); continue
            if cs>a: nk.append([a,min(cs,b)])
            if ce<b: nk.append([max(ce,a),b])
        keep=nk
    return [(q(a),q(b)) for a,b in keep if b-a>0.15]

def remap(cues, keep, gap_frames=2):
    out=[]; cur=0.0
    for (a,b) in keep:
        for s,e,t in cues:
            x,y = max(s,a), min(e,b)
            if y-x < 0.12: continue
            out.append([q(cur+(x-a)), q(cur+(y-a)), t])
        cur += (b-a)
    mg=[]
    for c in out:
        if mg and mg[-1][2]==c[2] and c[0]-mg[-1][1] < 0.1: mg[-1][1]=c[1]
        else: mg.append(c)
    return mg


# ---------------------------------------------------------------- 음량 (테이크 선택·무음 검증)
def loud_fn(wav_path):
    """구간(초) -> 평균 RMS dB."""
    import wave, array, math
    w=wave.open(wav_path); sr=w.getframerate()
    pcm=array.array('h'); pcm.frombytes(w.readframes(w.getnframes()))
    def f(a,b):
        i,j=max(0,int(a*sr)),min(len(pcm),int(b*sr))
        if j<=i: return -99.0
        s=sum(v*v for v in pcm[i:j])/(j-i)
        return 20*math.log10(max(math.sqrt(s),1)/32768)
    return f

def speech_segments2(env, hop_s, sens=0.12, min_dur=0.12, merge_gap=0.20, floor_db=14.0):
    """VAD + 음량 하한. 웅얼거림/리허설 테이크를 발화로 오인하지 않게 한다."""
    import math
    segs = speech_segments(env, hop_s, sens, min_dur, merge_gap)
    def db(a,b):
        i,j=int(a/hop_s),int(b/hop_s)
        v=[x for x in env[i:j] if x>0]
        return -99 if not v else 20*math.log10(max(sum(v)/len(v),1)/32768)
    lv=[(a,b,db(a,b)) for a,b in segs]
    if not lv: return segs
    peak=max(x[2] for x in lv)
    return [(a,b) for a,b,d in lv if d >= peak-floor_db]

def rough_cut_from_speech(cues, segs, total, pad_in=0.06, pad_out=0.10, max_gap=0.25):
    """살릴 자막이 걸친 '발화 구간 전체'를 남긴다.
    자막 시간만 기준으로 자르면 자막이 음성보다 앞설 때 목소리가 잘려나간다."""
    keep=[]
    for a,b,_ in cues:
        lo,hi=a,b
        for x,y in segs:
            if not (y < a-0.05 or x > b+0.05):
                lo=min(lo,x); hi=max(hi,y)
        s,e = max(0,lo-pad_in), min(total,hi+pad_out)
        if keep and s-keep[-1][1] <= max_gap: keep[-1][1]=max(keep[-1][1],e)
        else: keep.append([s,e])
    return [(q(s),q(e)) for s,e in keep]

def butt_join(cues):
    """자막을 빈틈 없이 붙인다 (앞 자막 끝 = 다음 자막 시작). 깜빡임 방지."""
    for i in range(len(cues)-1):
        cues[i][1] = cues[i+1][0]
    return cues

def lines_from_groups(groups):
    """(시작, 끝, [줄...]) -> 줄 단위 큐. 시간은 글자수 비례 배분."""
    out=[]
    for a,b,lines in groups:
        tot=sum(len(x) for x in lines) or 1; cur=a
        for i,x in enumerate(lines):
            e = b if i==len(lines)-1 else cur+(b-a)*len(x)/tot
            out.append([q(cur), q(e), x]); cur=e
    return out


def tighten(keep, segs, pad_in=0.035, pad_out=0.07, min_pause=0.10, min_clip=0.2):
    """컷 '안'에 남은 무음까지 잘라낸다.
    rough_cut_from_speech 는 컷 사이 무음만 없앤다 — 발화 구간 내부의 쉼(마)은 그대로 남는다.
    segs 는 촘촘한 VAD(merge_gap≈0.06) 결과를 넣어야 쉼이 보인다."""
    out=[]
    for a,b in keep:
        sub=sorted([(max(x,a),min(y,b)) for x,y in segs if not (y<=a or x>=b)])
        cur=None
        for x,y in sub:
            s,e = max(a,x-pad_in), min(b,y+pad_out)
            if cur and s-cur[1] <= min_pause: cur[1]=max(cur[1],e)
            else:
                if cur: out.append(cur)
                cur=[s,e]
        if cur: out.append(cur)
    return [(q(s),q(e)) for s,e in out if e-s >= min_clip]

def dead_air(keep, segs):
    """컷 안에 남은 무음 총량과 구간 목록. 결과 검증용."""
    tot=0.0; runs=[]
    for a,b in keep:
        sub=sorted([(max(x,a),min(y,b)) for x,y in segs if not (y<=a or x>=b)])
        cur=a
        for x,y in sub:
            if x-cur>0.001: tot+=x-cur; runs.append(round(x-cur,3))
            cur=max(cur,y)
        if b-cur>0.001: tot+=b-cur; runs.append(round(b-cur,3))
    return tot, sorted(runs, reverse=True)
