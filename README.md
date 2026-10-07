# roughcut-kit

캡컷·프리미어 프로 러프컷 작업을 Claude Code에서 말로 시키기 위한 플러그인입니다.
스킬 3개와 `premiere-pro` MCP 서버 설정이 들어 있습니다.

## 들어 있는 것

| 구성 | 이름 | 하는 일 |
| --- | --- | --- |
| 스킬 | `capcut-roughcut` | 캡컷에서 자동 자막만 걸어 둔 프로젝트를 받아 자막 싱크 보정, 반복 테이크·무음 제거, 오인식 교정, 릴스 자막 리듬으로 재분할, 효과음 얹기 |
| 스킬 | `script-roughcut` | 대본 순서대로 드라마·콩트 촬영본을 골라 프리미어 XML·SRT와 캡컷 프로젝트 생성 |
| 스킬 | `capcut-edit` | 캡컷/剪映 프로젝트의 자막·타이밍·속도·볼륨·애니메이션 편집, 롱폼을 쇼츠로 자르기 |
| MCP 서버 | `premiere-pro` | [premiere-pro-mcp](https://github.com/leancoderkavy/premiere-pro-mcp)를 `npx`로 실행해 프리미어 프로를 직접 조작 |

## 설치

```bash
claude plugin marketplace add choicp7-svg/roughcut-kit
```

```bash
claude plugin install roughcut-kit@roughcut-kit
```

설치 후 `/roughcut-kit:capcut-roughcut 0904`처럼 부르거나, "0904 컷편집해줘", "대본대로 러프컷해줘"처럼 말하면 됩니다.

## 필요한 것

- Python 3, ffmpeg (없으면 `pip install imageio-ffmpeg` 후 `FFMPEG` 환경변수로 경로 지정)
- `script-roughcut`: `pip install faster-whisper pillow pypdf`
- `capcut-edit`: 별도의 `capcut` CLI가 PATH에 있어야 합니다
- `premiere-pro` MCP 서버: Node.js, 프리미어 프로, 그리고 premiere-pro-mcp의 프리미어 쪽 브리지 패널 설치 (해당 저장소 안내 참고)

## 캡컷 프로젝트 폴더

OS 기본 위치를 자동으로 찾습니다. 캡컷 프로젝트를 다른 드라이브에 두었다면 환경변수로 지정하세요.

```bash
export CAPCUT_DRAFT_ROOT="/Volumes/외장드라이브/CapCut Drafts"
```

## 주의

- 캡컷 프로젝트 형식은 비공개라 캡컷 버전이 바뀌면 깨질 수 있습니다. 결과는 항상 새 프로젝트로 만들고 원본은 건드리지 않습니다.
- 캡컷 프로젝트를 쓰는 작업은 캡컷을 종료한 상태에서 실행하세요.

## 출처

- `capcut-roughcut`의 자막 스타일 프리셋과 기본 효과음 세트는 치상(아워프로젝트)의 것입니다.
- `capcut-edit`와 `premiere-pro-mcp`는 각 원작자의 것입니다.
