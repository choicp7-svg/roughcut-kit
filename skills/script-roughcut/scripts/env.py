# -*- coding: utf-8 -*-
"""각 PC 환경 자동 탐지 — 윈도우/맥 공용.
캡컷 draft 루트, 그 PC의 원래(네이티브) 경로, 폰트 경로를 알아서 찾는다.

두 가지 실행 환경을 모두 지원한다.
  1) 클로드 코드(터미널) — 스크립트가 내 PC에서 직접 돈다. 캡컷 폴더를 네이티브 경로로 바로 찾는다.
  2) Cowork(데스크톱 앱) — 연결한 폴더가 ~/mnt/<폴더명> 아래에 마운트된다. 거기서 찾는다.
캡컷을 다른 곳에 설치했으면 환경변수 CAPCUT_DRAFT_ROOT 로 draft 폴더를 직접 지정할 수 있다.
"""
import os, glob, json, re, sys

MNT = os.path.expanduser("~/mnt")
DRAFT_TAIL = "/User Data/Projects/com.lveditor.draft"

# 연결한 폴더가 무엇이든(CapCut / Movies / Local / draft 폴더 자체) 잡히도록 넓게 훑는다 (Cowork)
DRAFT_GLOBS = [
    MNT + "/*" + DRAFT_TAIL,                    # CapCut 폴더를 연결
    MNT + "/*/CapCut" + DRAFT_TAIL,             # Movies(맥)/Local(윈) 을 연결
    MNT + "/*/*/CapCut" + DRAFT_TAIL,
    MNT + "/*/Projects/com.lveditor.draft",
    MNT + "/*/com.lveditor.draft",
    MNT + "/com.lveditor.draft",
]

# 각 OS의 캡컷 기본 위치 (폴더 접근 요청할 때 쓸 후보)
CANDIDATE_ROOTS = {
    "win": ["~/AppData/Local/CapCut"],
    "mac": ["~/Movies/CapCut", "~/Library/Containers/com.lemon.lvoverseas/Data/Movies/CapCut"],
}

def _p(path):
    return path.replace("\\", "/").rstrip("/")

def _native_candidates():
    c = []
    if os.environ.get("CAPCUT_DRAFT_ROOT"):
        c.append(os.environ["CAPCUT_DRAFT_ROOT"])
    if sys.platform.startswith("win"):
        la = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
        c.append(la + "/CapCut" + DRAFT_TAIL)
    elif sys.platform == "darwin":
        c.append(os.path.expanduser("~/Movies/CapCut" + DRAFT_TAIL))
        c.append(os.path.expanduser("~/Library/Containers/com.lemon.lvoverseas/Data/Movies/CapCut" + DRAFT_TAIL))
    else:  # 리눅스/WSL 등 — 환경변수 또는 ~/mnt 로만 찾는다
        pass
    return [_p(x) for x in c]

def is_mounted(draft_root):
    """Cowork 마운트(~/mnt) 아래인지."""
    return _p(draft_root).startswith(_p(MNT) + "/")

def find_draft_root():
    for p in _native_candidates():
        if os.path.isdir(p):
            return p
    for pat in DRAFT_GLOBS:
        hits = [h for h in glob.glob(pat) if os.path.isdir(h)]
        if hits:
            return sorted(hits, key=lambda h: -len(glob.glob(h + "/*/draft_content.json")))[0]
    return None

def _stored_root(draft_root):
    """프로젝트 메타에 적힌 '그 PC 기준' 캡컷 루트 경로 원문."""
    f = os.path.join(draft_root, "root_meta_info.json")
    if os.path.exists(f):
        try:
            m = json.load(open(f, encoding="utf-8"))
            if m.get("root_path"): return m["root_path"]
            for e in m.get("all_draft_store", []):
                if e.get("draft_root_path"): return e["draft_root_path"]
        except Exception: pass
    for p in glob.glob(draft_root + "/*/draft_meta_info.json")[:20]:
        try:
            r = json.load(open(p, encoding="utf-8")).get("draft_root_path")
            if r: return r
        except Exception: pass
    return None

def platform_of(draft_root):
    if not is_mounted(draft_root):
        if sys.platform.startswith("win"): return "win"
        if sys.platform == "darwin":       return "mac"
    r = _stored_root(draft_root) or ""
    if re.match(r"^[A-Za-z]:", r): return "win"
    if r.startswith("/"):          return "mac"
    if "AppData" in draft_root:    return "win"
    if "/Movies/" in draft_root or "/Library/" in draft_root: return "mac"
    return "win"

def native_root(draft_root):
    """이 PC에서의 캡컷 draft 루트 경로 (구분자는 '/'로 통일).
    직접 실행 중이면 draft_root 자체가 네이티브 경로다."""
    if not is_mounted(draft_root):
        return _p(os.path.abspath(draft_root))
    r = _stored_root(draft_root)
    return _p(r) if r else None

def native_user(draft_root):
    r = native_root(draft_root) or ""
    parts = r.split("/")
    if len(parts) > 2 and parts[1].lower() == "users": return parts[2]
    if not is_mounted(draft_root):
        return os.path.basename(_p(os.path.expanduser("~")))
    return None

def app_base(draft_root):
    """캡컷 사용자 데이터 루트 (…/CapCut) 네이티브 경로."""
    r = native_root(draft_root) or ""
    return r.split("/User Data/")[0] if "/User Data/" in r else None

def capcut_system_font(draft_root):
    """캡컷 기본 시스템 폰트(en.ttf)의 네이티브 경로. OS별로 위치가 다르다."""
    if platform_of(draft_root) == "mac":
        return "/Applications/CapCut.app/Contents/Resources/Font/SystemFont/en.ttf"
    apps = os.path.abspath(os.path.join(draft_root, "..", "..", "..", "Apps"))
    vers = sorted([d for d in glob.glob(apps + "/*")
                   if os.path.exists(d + "/Resources/Font/SystemFont/en.ttf")],
                  key=lambda d: [int(x) for x in os.path.basename(d).split(".") if x.isdigit()])
    base = app_base(draft_root)
    if vers and base:
        return base + "/Apps/" + os.path.basename(vers[-1]) + "/Resources/Font/SystemFont/en.ttf"
    d = user_font_dir(draft_root)
    return (d + "/NotoSansKR-Regular.ttf") if d else "en.ttf"

def user_font_dir(draft_root):
    """사용자가 설치한 폰트 폴더 (네이티브 경로)."""
    if platform_of(draft_root) == "mac":
        u = native_user(draft_root)
        return ("/Users/%s/Library/Containers/com.lemon.lvoverseas/Data/Library/Fonts" % u) if u else None
    if not is_mounted(draft_root) and os.environ.get("LOCALAPPDATA"):
        return _p(os.environ["LOCALAPPDATA"]) + "/Microsoft/Windows/Fonts"
    u = native_user(draft_root)
    return ("C:/Users/%s/AppData/Local/Microsoft/Windows/Fonts" % u) if u else None

def scan_fonts(draft_root, limit=40):
    """이 PC의 기존 프로젝트에서 실제로 쓰인 폰트 (제목 -> 경로).
    다른 OS에서 만든 프로젝트의 경로는 걸러낸다."""
    plat = platform_of(draft_root); found = {}
    files = sorted(glob.glob(draft_root + "/*/draft_content.json"),
                   key=os.path.getmtime, reverse=True)[:limit]
    for f in files:
        try: d = json.load(open(f, encoding="utf-8"))
        except Exception: continue
        for m in d.get("materials", {}).get("texts", []) or []:
            t, p = m.get("font_title"), (m.get("font_path") or "").replace("\\", "/")
            if not (t and p) or t == "none" or "SystemFont" in p: continue
            native = bool(re.match(r"^[A-Za-z]:", p)) if plat == "win" else p.startswith("/")
            if native and t not in found: found[t] = p
    return found

MISSING_FONTS = []   # 이 PC에 없어서 캡컷 기본 폰트로 대체한 폰트 제목들

def _font_ok(path, draft_root):
    """직접 실행 중이면 실제 파일이 있는지 확인. Cowork(마운트)면 확인 불가 → 있다고 본다."""
    if is_mounted(draft_root): return True
    return bool(path) and os.path.exists(path)

def resolve_font(title, draft_root, fonts=None, fallback_file=None):
    fonts = fonts if fonts is not None else scan_fonts(draft_root)
    cand = None
    if title in fonts: cand = fonts[title]
    else:
        for k, v in fonts.items():
            if title.split()[0].lower() in k.lower(): cand = v; break
    if cand is None:
        d = user_font_dir(draft_root)
        if d and fallback_file: cand = d + "/" + fallback_file
    if cand and _font_ok(cand, draft_root):
        return cand
    if title not in MISSING_FONTS: MISSING_FONTS.append(title)
    sysf = capcut_system_font(draft_root)
    return sysf

def project_native_path(draft_root, name):
    r = native_root(draft_root)
    return (r + "/" + name) if r else name

project_win_path = project_native_path      # 이전 이름 호환

def describe():
    root = find_draft_root()
    if not root:
        return {"ok": False, "error": "캡컷 프로젝트 폴더를 못 찾음",
                "확인할_곳": CANDIDATE_ROOTS,
                "힌트": "캡컷이 다른 곳에 설치돼 있으면 환경변수 CAPCUT_DRAFT_ROOT 에 "
                        "…/CapCut/User Data/Projects/com.lveditor.draft 경로를 넣어줘. "
                        "Cowork라면 캡컷 폴더를 세션에 연결해야 한다."}
    projects = sorted(glob.glob(root + "/*/draft_content.json"), key=os.path.getmtime, reverse=True)
    return {"ok": True, "os": platform_of(root), "mode": "cowork" if is_mounted(root) else "native",
            "draft_root": root,
            "native_root": native_root(root), "user": native_user(root),
            "system_font": capcut_system_font(root), "user_font_dir": user_font_dir(root),
            "projects": len(projects),
            "recent": [os.path.basename(os.path.dirname(p)) for p in projects[:10]],
            "fonts": list(scan_fonts(root).keys())[:15]}

if __name__ == "__main__":
    print(json.dumps(describe(), ensure_ascii=False, indent=1))
