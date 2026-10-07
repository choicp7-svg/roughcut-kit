# -*- coding: utf-8 -*-
"""
capcut_kit — 캡컷(CapCut PC) draft_content.json 읽기/쓰기 툴킷
아워프로젝트 릴스 프로젝트 36개를 파싱해서 추출한 자막 스타일 프리셋 내장.
CapCut 9.1.0 / draft version 360000 (new_version 179.0.0) 기준.
"""
import json, os, uuid, copy, shutil, re

US = 1_000_000  # CapCut 타임라인 단위 = 마이크로초

# ---------------------------------------------------------------- 프리셋
# 폰트는 '제목'으로만 지정한다. 실제 경로는 각 PC에서 env.resolve_font()가 찾는다.
PRESETS = {
    # 스타일을 안 정했을 때 기본값. 캡컷 기본 폰트 + 흰 글씨 + 얇은 검정 외곽선. 폰트 설치 없이 누구나 됨.
    "기본": dict(font="캡컷 기본", font_file="en.ttf",
        size=11.0, bold=True, color="#FFFFFF", stroke="#000000", stroke_w=0.0231182798743248,
        shadow=False, letter_spacing=-0.05, line_spacing=0.02, y=-0.0945, scale=1.0),

    # ── 아워프로젝트(치상) 릴스에서 실제로 쓰는 스타일 3종. 폰트만 캡컷 기본으로 바꿔서 누구나 그대로 쓸 수 있게 함 ──
    # 요즘 릴스 본문 자막 기본. 외곽선 없이 은은한 검정 그림자(0.45), 자간 -0.05, 중하단, 1.165배
    "치상_그림자": dict(font="캡컷 기본", font_file="en.ttf",
        size=10.0, bold=True, color="#FFFFFF", stroke=None, stroke_w=0.08,
        shadow=True, shadow_alpha=0.45267489552497864, letter_spacing=-0.05, line_spacing=0.02,
        y=-0.07242760180995433, scale=1.1651231359529823),
    # 검정 배경 박스 안에 흰 글씨. 하단
    "치상_검정박스": dict(font="캡컷 기본", font_file="en.ttf",
        size=11.0, bold=False, color="#FFFFFF", stroke=None, stroke_w=0.08,
        shadow=False, letter_spacing=-0.05, line_spacing=0.02, y=-0.1705, scale=1.0,
        bg="#000000", bg_alpha=1.0, bg_style=1, bg_round=0.0, bg_w=0.14, bg_h=0.14),
    # 굵은 검정 외곽선 + 그림자. 배경이 밝거나 복잡할 때. 하단, 1.16배
    "치상_외곽선": dict(font="캡컷 기본", font_file="en.ttf",
        size=10.0, bold=True, color="#FFFFFF", stroke="#000000", stroke_w=0.08,
        shadow=True, letter_spacing=0.0, line_spacing=0.02, y=-0.1946, scale=1.1617),
}

def resolve_preset(name, draft_root):
    """프리셋 이름 → 이 PC에서 바로 쓸 수 있는 설정(폰트 실경로 포함)."""
    import env
    p = dict(PRESETS[name] if isinstance(name, str) else name)
    if p["font"] == "캡컷 기본":
        p["font_path"] = env.capcut_system_font(draft_root)
    else:
        p["font_path"] = env.resolve_font(p["font"], draft_root, fallback_file=p.get("font_file"))
    p["font_title"] = "none" if p["font"] == "캡컷 기본" else p["font"]   # 캡컷은 기본 폰트를 'none'으로 기록한다
    p["font_size"]  = p["size"]
    return p

def _hx(c):
    c = c.lstrip("#")
    return [int(c[i:i+2], 16) / 255.0 for i in (0, 2, 4)]

def nid():
    """캡컷 스타일 대문자 UUID (4번째 블록 소문자 유지 관례는 무시해도 열림)"""
    return str(uuid.uuid4()).upper()

# ---------------------------------------------------------------- 로드/세이브
def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save(draft, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False)

def index(draft):
    idx = {}
    for k, v in draft["materials"].items():
        if isinstance(v, list):
            for m in v:
                if isinstance(m, dict) and "id" in m:
                    idx[m["id"]] = (k, m)
    return idx

def caption_track(draft):
    for t in draft["tracks"]:
        if t["type"] == "text" and t.get("flag") == 1:
            return t
    return None

def main_video_track(draft):
    for t in draft["tracks"]:
        if t["type"] == "video" and t.get("flag") == 0:
            return t
    return None

# ---------------------------------------------------------------- 자막 생성
def _text_material(text, preset, words=None, dur_ms=0):
    p = preset
    styles = [{
        "fill": {"content": {"render_type": "solid", "solid": {"color": _hx(p["color"])}}},
        "font": {"id": "", "path": p["font_path"]},
        "range": [0, len(text)],
        "size": p["font_size"],
    }]
    if p["bold"]:
        styles[0]["bold"] = True
    if p["shadow"]:
        styles[0]["shadows"] = [{"alpha": p.get("shadow_alpha", 0.9), "angle": -45,
            "content": {"render_type": "solid", "solid": {"color": [0, 0, 0]}},
            "diffuse": 0.0589849092066288, "distance": 4.999999523162842,
            "thickness_projection_angle": -45, "thickness_projection_distance": 0,
            "thickness_projection_enable": False}]
    if p["stroke"]:
        styles[0]["strokes"] = [{
            "content": {"render_type": "solid", "solid": {"color": _hx(p["stroke"])}},
            "mode": 0, "width": p["stroke_w"]}]
    content = json.dumps({"styles": styles, "text": text}, ensure_ascii=False)
    if words is None:
        words = {"start_time": [0], "end_time": [dur_ms], "text": [text]}
    return {
        "id": nid(), "name": "", "type": "subtitle",
        "recognize_task_id": "", "recognize_text": text,
        "recognize_model": "", "punc_model": "",
        "content": content, "base_content": content,
        "words": words,
        "current_words": {"start_time": [], "end_time": [], "text": []},
        "global_alpha": 1.0,
        "combo_info": {"text_templates": []},
        "caption_template_info": {"resource_id": "", "third_resource_id": "", "resource_name": "",
            "category_id": "", "category_name": "", "effect_id": "", "request_id": "",
            "path": "", "is_new": False, "source_platform": 0},
        "layer_weight": 1,
        "letter_spacing": p["letter_spacing"], "line_spacing": p["line_spacing"],
        "text_curve": None, "text_loop_on_path": False, "offset_on_path": 0.0,
        "enable_path_typesetting": False, "text_exceeds_path_process_type": 0,
        "text_typesetting_paths": None, "text_typesetting_paths_file": "",
        "text_typesetting_path_index": 0,
        "has_shadow": p["shadow"], "shadow_color": "#000000" if p["shadow"] else "",
        "shadow_alpha": p.get("shadow_alpha", 0.9), "shadow_smoothing": 0.45, "shadow_distance": 5.0,
        "shadow_point": {"x": 0.6363961030678928, "y": -0.6363961030678928},
        "shadow_angle": -45.0, "shadow_thickness_projection_enable": False,
        "shadow_thickness_projection_angle": 0.0, "shadow_thickness_projection_distance": 0.0,
        "border_alpha": 1.0, "border_color": p["stroke"] or "",
        "border_width": p["stroke_w"], "border_mode": 0,
        "style_name": "", "text_color": p["color"], "text_alpha": 1.0,
        "font_name": "", "font_title": p["font_title"], "font_size": p["font_size"],
        "font_path": p["font_path"], "font_id": "", "font_resource_id": "",
        "initial_scale": 1.0, "font_url": "", "typesetting": 0, "alignment": 1,
        "line_feed": 1, "use_effect_default_color": True, "is_rich_text": False,
        "shape_clip_x": False, "shape_clip_y": False, "ktv_color": "",
        "text_to_audio_ids": [], "bold_width": 0.00800000037998, "italic_degree": 0,
        "underline": False, "underline_width": 0.05, "underline_offset": 0.22,
        "sub_type": 0, "check_flag": 15, "text_size": 30,
        "font_category_name": "", "font_source_platform": 0, "font_third_resource_id": "",
        "font_category_id": "", "add_type": 1, "operation_type": 0, "recognize_type": 0,
        "fonts": [],
        "background_color": p.get("bg") or "",
        "background_alpha": p.get("bg_alpha", 1.0),
        "background_style": p.get("bg_style", 0),
        "background_round_radius": p.get("bg_round", 0.0),
        "background_width": p.get("bg_w", 0.14),
        "background_height": p.get("bg_h", 0.14),
        "background_vertical_offset": 0.0, "background_horizontal_offset": 0.0,
        "background_fill": "", "single_char_bg_enable": False, "single_char_bg_color": "",
        "single_char_bg_alpha": 1.0, "single_char_bg_round_radius": 0.3,
        "single_char_bg_width": 0.0, "single_char_bg_height": 0.0,
        "single_char_bg_vertical_offset": 0.0, "single_char_bg_horizontal_offset": 0.0,
        "font_team_id": "", "tts_auto_update": False, "text_preset_resource_id": "",
        "group_id": "", "preset_id": "", "preset_name": "", "preset_category": "",
        "preset_category_id": "", "preset_index": 0, "preset_has_set_alignment": False,
        "force_apply_line_max_width": False, "language": "ko-KR",
        "relevance_segment": [], "original_size": [], "fixed_width": -1.0,
        "fixed_height": -1.0, "multi_language_current": "none",
    }

def _text_segment(mat_id, anim_id, start_us, dur_us, preset, render_index, track_render_index):
    return {
        "id": nid(), "source_timerange": None,
        "target_timerange": {"start": int(start_us), "duration": int(dur_us)},
        "render_timerange": {"start": 0, "duration": 0},
        "desc": "", "state": 0, "speed": 1.0, "is_loop": False, "is_tone_modify": False,
        "reverse": False, "intensifies_audio": False, "cartoon": False,
        "volume": 1.0, "last_nonzero_volume": 1.0,
        "clip": {"scale": {"x": preset["scale"], "y": preset["scale"]}, "rotation": 0.0,
                 "transform": {"x": 0.0, "y": preset["y"]},
                 "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0},
        "uniform_scale": {"on": True, "value": 1.0},
        "material_id": mat_id, "extra_material_refs": [anim_id],
        "render_index": render_index, "keyframe_refs": [],
        "enable_lut": False, "enable_adjust": False, "enable_hsl": False, "visible": True,
        "group_id": "", "enable_color_curves": True, "enable_hsl_curves": True,
        "track_render_index": track_render_index, "hdr_settings": None,
        "enable_color_wheels": True, "track_attribute": 0, "is_placeholder": False,
        "template_id": "", "enable_smart_color_adjust": False, "template_scene": "default",
        "common_keyframes": [], "caption_info": None,
        "responsive_layout": {"enable": False, "target_follow": "", "size_layout": 0,
                              "horizontal_pos_layout": 0, "vertical_pos_layout": 0},
        "enable_color_match_adjust": False, "enable_color_correct_adjust": False,
        "enable_adjust_mask": False, "raw_segment_id": "", "lyric_keyframes": None,
        "enable_video_mask": True, "digital_human_template_group_id": "",
        "color_correct_alg_result": "", "source": "segmentsourcenormal",
        "enable_mask_stroke": False, "enable_mask_shadow": False,
        "enable_color_adjust_pro": False, "segment_color_tag": "",
    }

def set_captions(draft, cues, preset="치상_그림자", track_render_index=None):
    """cues = [{'start': 초, 'end': 초, 'text': '...', 'words': [(시작초, 끝초, '단어'), ...]}]
    기존 자막 트랙(flag=1)이 있으면 통째로 교체, 없으면 새로 만든다."""
    p = PRESETS[preset] if isinstance(preset, str) else preset
    tr = caption_track(draft)
    idx = index(draft)
    if tr is not None:
        # 기존 자막 material / animation material 청소
        drop = set()
        for s in tr["segments"]:
            drop.add(s["material_id"]); drop.update(s["extra_material_refs"])
        draft["materials"]["texts"] = [m for m in draft["materials"].get("texts", []) if m["id"] not in drop]
        draft["materials"]["material_animations"] = [
            m for m in draft["materials"].get("material_animations", []) if m["id"] not in drop]
        if track_render_index is None and tr["segments"]:
            track_render_index = tr["segments"][0].get("track_render_index", 1)
        tr["segments"] = []
    else:
        tr = {"id": nid(), "type": "text", "flag": 1, "attribute": 0,
              "name": "", "is_default_name": True, "segments": []}
        draft["tracks"].append(tr)
    if track_render_index is None:
        track_render_index = max([s.get("track_render_index", 0)
                                  for t in draft["tracks"] for s in t["segments"]] or [0]) + 1
    base_ri = 14000
    draft["materials"].setdefault("texts", [])
    draft["materials"].setdefault("material_animations", [])
    for i, c in enumerate(cues):
        start_us = int(round(c["start"] * US))
        dur_us = int(round(c["end"] * US)) - start_us     # 끝 = 다음 시작과 정확히 같은 정수가 되게
        if i + 1 < len(cues):                             # 겹침 방지: 끝이 다음 시작을 넘지 않게
            dur_us = min(dur_us, int(round(cues[i + 1]["start"] * US)) - start_us)
        if dur_us <= 0:
            continue
        words = None
        if c.get("words"):
            st, et, tx = [], [], []
            for (ws, we, w) in c["words"]:
                st.append(int(round((ws - c["start"]) * 1000)))
                et.append(int(round((we - c["start"]) * 1000)))
                tx.append(w)
            words = {"start_time": st, "end_time": et, "text": tx}
        m = _text_material(c["text"], p, words, dur_ms=int(dur_us / 1000))
        a = {"id": nid(), "type": "sticker_animation", "animations": [],
             "multi_language_current": "none"}
        draft["materials"]["texts"].append(m)
        draft["materials"]["material_animations"].append(a)
        tr["segments"].append(_text_segment(m["id"], a["id"], start_us, dur_us, p,
                                            base_ri + i, track_render_index))
    return tr

# ---------------------------------------------------------------- 러프 컷
def apply_cuts(draft, keep, track=None):
    """keep = [(원본시작초, 원본끝초), ...] — 메인 비디오 트랙을 이 구간만 남기고 재구성.
    세그먼트 1개짜리 트랙(통영상)을 기준으로 자른다."""
    tr = track or main_video_track(draft)
    assert tr and len(tr["segments"]) >= 1, "메인 비디오 트랙에 세그먼트가 없음"
    proto = tr["segments"][0]
    src0 = proto["source_timerange"]["start"]
    out, cur = [], 0
    for (a, b) in keep:
        d = int(round((b - a) * US))
        if d <= 0:
            continue
        s = copy.deepcopy(proto)
        s["id"] = nid()
        s["source_timerange"] = {"start": src0 + int(round(a * US)), "duration": d}
        s["target_timerange"] = {"start": cur, "duration": d}
        out.append(s); cur += d
    tr["segments"] = out
    draft["duration"] = max(draft.get("duration", 0), cur)
    return cur / US

def shift_captions_for_cuts(cues, keep):
    """컷 적용 후 타임라인 기준으로 자막 시간 재매핑."""
    out, cur = [], 0.0
    for (a, b) in keep:
        for c in cues:
            s, e = max(c["start"], a), min(c["end"], b)
            if e - s < 0.08:
                continue
            nc = dict(c)
            nc["start"], nc["end"] = cur + (s - a), cur + (e - a)
            if c.get("words"):
                nc["words"] = [(cur + (ws - a), cur + (we - a), w)
                               for (ws, we, w) in c["words"] if a <= ws < b]
            out.append(nc)
        cur += (b - a)
    return out

# ---------------------------------------------------------------- SRT
def clear_timeline_cache(project_dir, draft_root):
    """캡컷 9.x는 한 번 열어본 프로젝트의 타임라인을 Timelines/ 아래 사본으로 들고 있고, 닫을 때 그걸로 바깥
    draft_content.json 을 덮어쓴다. 바깥 파일을 고쳤으면 이 사본을 치워야 캡컷이 바깥 파일을 다시 읽는다.
    삭제하지 않고 <CapCut>/_trash/<프로젝트>_<id>/ 로 옮긴다. 옮긴 항목 이름 목록을 돌려준다."""
    base = draft_root.replace("\\", "/").split("/User Data/")[0]
    trash = os.path.join(base, "_trash", os.path.basename(project_dir) + "_" + uuid.uuid4().hex[:6])
    moved = []
    for f in ["Timelines", "draft.extra", "template.tmp", "template-2.tmp", "draft_content.json.bak"]:
        p = os.path.join(project_dir, f)
        if os.path.exists(p):
            os.makedirs(trash, exist_ok=True)
            shutil.move(p, os.path.join(trash, f)); moved.append(f)
    return moved

def to_srt(cues):
    def ts(t):
        h, r = divmod(t, 3600); m, s = divmod(r, 60)
        return "%02d:%02d:%06.3f" % (h, m, s).replace(".", ",")
    lines = []
    for i, c in enumerate(cues, 1):
        def f(t):
            h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
            return "%02d:%02d:%06.3f" % (h, m, s)
        lines.append(str(i))
        lines.append(f(c["start"]).replace(".", ",") + " --> " + f(c["end"]).replace(".", ","))
        lines.append(c["text"]); lines.append("")
    return "\n".join(lines)
