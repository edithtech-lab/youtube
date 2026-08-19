# 실제 사용 중인 프롬프트 상수 발췌

AI 쇼츠 파이프라인(대본 → 컷 분해 → 이미지 → I2V 영상)에서 **실제로 모델에 전송되는
영어 프롬프트 템플릿 원문**이다. 코드에서 프롬프트 부분만 잘라냈다 (API 키·경로 등은 없음).
한국어 주석은 각 문구를 그렇게 쓴 이유·실측 실패 기록이다 — 개선안을 낼 때 이 근거를 깨지 마라.

- 이미지 생성: Gemini 이미지 모델 · 2K · 9:16
- 영상 생성: Veo 3.1 계열 / Seedance 1.5 Pro · 720p · 4~8초 · I2V(시작 프레임 = 그 컷 이미지)


## 1. 영상 프롬프트 템플릿(T2V) + 카메라 프리셋 22종

> 컷당 카메라 워크는 1개만 고른다. 빠르기는 별도 템포 절이 담당.

```python
# 영상 프롬프트 = 이미지 프롬프트 + 「카메라」 + 「시간에 따른 변화」.
# 레퍼런스 채널 역추적 결과 이 두 축이 정지컷과 영상컷을 가르는 핵심이었다.
# 이미지가 없을 때(T2V) — 공식 5요소 순서: 촬영(카메라·구도)을 맨 앞에 둔다.
MOTION_PROMPT = """{shot_line}Camera: {camera}

SUBJECT: {scene}
Motion: {motion}
The motion is already underway on the very first frame — never open on a frozen,
settling shot.

{style}

{tempo}

{audio}
{negative}"""
CAMERA_PRESETS = {
    # 카메라는 '어느 방향으로 움직이는가'만 말한다. 빠르기는 VIDEO_TEMPO 가 담당한다 —
    # 프리셋에 very slow 를 박아두면 역동 모드와 자기모순이 난다.
    "push": "dolly push-in, the frame closing in over the shot",
    "pull": "dolly pull-back, gradually revealing more of the surroundings",
    "down": "camera travels downward across the frame",
    "up": "camera travels upward across the frame",
    "panright": "camera glides to the right, the framing sliding sideways",
    "panleft": "camera glides to the left, the framing sliding sideways",
    "pushdown": "push-in while drifting downward at the same time, "
                "closing in as the framing travels down",
    "pullup": "pull-back while rising upward at the same time, "
              "opening out as the framing lifts",
    "orbit": "orbit, the viewpoint arcing around what is in frame",
    "still": "locked-off camera, no camera movement",
    # ── 역동 그룹 — 속도감이 워크의 정체성이라 예외적으로 빠르기를 프리셋에 포함한다 ──
    "crash": "fast crash zoom-in, rushing toward the subject with real urgency",
    "whip": "quick whip pan, the frame snapping sideways to land on the subject",
    "handheld": "energetic handheld tracking shot, chasing the subject with natural sway and drive",
    "riseorbit": "low-angle rise combined with an orbital arc, sweeping up and around the subject",
    "hyperlapse": "hyperlapse push, the camera rushing forward through the scene as time streaks by",
    "fpv": "FPV racing-drone shot, diving and weaving through the scene with fast swooping agility",
    "dollyzoom": "dolly zoom vertigo effect — pushing in on the subject while the background "
                 "stretches and falls away behind it",
    "whiptilt": "quick whip tilt, the frame snapping vertically to land on the subject",
    "roll": "dutch roll, the horizon tilting and rotating as the camera keeps moving",
    "chase": "chase cam racing right behind the subject as it moves through the scene",
    "gamecam": "smooth third-person follow camera tracking a few meters behind the character "
               "at shoulder height, steady and locked to their pace, exactly like open-world "
               "gameplay footage",
    "sweeparc": "fast sweeping arc around the subject from left to right — the subject stays "
                "centered and locked while the background wheels past behind it",
}
```


## 2. 영상 HUD/주석 VFX 모드 (핵심)

> 너의 §14 VFX 5단계(ORIGIN→BEHAVIOR→TRAJECTORY→INTERACTION→DISSIPATION)에 해당하는 부분. DISSIPATION 만 일부러 반대로 간다 — 편집에서 그 선 위에 자막을 얹어야 해서 사라지지 않게 고정한다.

```python
VIDEO_ANNO_MODES = {
    # ⚠ 'traces along' 은 모델이 **선이 물체 위를 훑고 지나간다**로 읽는다 — 실제로 HUD 막대가
    # 제품 위를 미끄러지는 클립이 나왔다 (2026-08-11 제보). 위치는 못으로 박고, 움직이는 것은
    # '선 안을 지나가는 빛'뿐이라고 못박는다. 정지만 시키면 죽은 화면이 되므로 액션은 남긴다.
    "animate": ("The {accent} HUD visible in the provided frame is where the overlay ENDS UP — "
                "not how it looks at the start. Open the clip with that overlay not yet there, "
                "and draw it on: the hairline grows out from one end of the edge it marks and "
                "runs to the other, the fine graduation ticks switching on one after another "
                "behind it, until it matches the provided frame exactly. This takes about the "
                "first second, then it holds. "
                "It is drawn **in place**, growing along the edge it belongs to. It never slides "
                "across the object, never drifts in from off-screen, never sweeps over the "
                "product as a whole bar, and never changes position or size once complete — "
                "that last part is the failure to avoid. Only the camera moves. "
                "Any circular ground grid already drawn simply holds its place — never add new "
                "grid elements. "
                "It happens once: no looping, no blinking, no repeated scanning, no fading out. "
                "All of it reads one thing: {focus} "
                "It stays locked in perspective to what it measures as the shot moves. "
                "True hairline strokes about one or two pixels wide at 1080p, glowing but never "
                "fat, hugging exactly the thing named above — not the biggest or most prominent "
                "object in the frame — rather than stretching across empty ground. "
                "The HUD is bare geometry: no viewfinder box floating in mid-frame, no corner "
                "brackets, no icons, no scanner readouts, no serial codes or interface labels — "
                "no letters, digits or words."),
    # 지면 원형 그리드는 '땅에 선 구조물을 측량하는 와이드 컷'에서만 — 이미지 쪽 규칙과 같다
    # (2026-08-11: 이미지만 wide 한정으로 고치고 영상은 무조건이라, 클로즈업·소품 클립마다
    #  화면 아래에 대형 레이더 원판이 그려져 피사체에서 시선이 이탈했다)
    "draw": ("Early in the shot a {accent} holographic technical HUD switches on over the scene, "
             "reading exactly one thing: {focus} A single hairline contour draws itself onto the "
             "outline of that one thing{dim}{grid}, with a soft neon bloom — the line grows from "
             "one end of that outline to the other and stops there. "
             "It finishes drawing within the first second or two and then holds: the finished "
             "line stays exactly on that outline and never slides across the object, never "
             "drifts, never sweeps over it again. No looping, no blinking, no redrawing, no "
             "fading out. "
             "It stays locked to what it measures. Rendered by software, never hand-drawn: "
             "true hairline strokes about one or two pixels wide at 1080p, glowing but never "
             "fat, hugging exactly the thing named above — not the biggest or most prominent "
             "object in the frame — rather than stretching across empty ground. "
             "The HUD is bare geometry: no viewfinder box floating in mid-frame, no corner "
             "brackets, no icons, no scanner readouts, no serial codes or interface labels — "
             "no letters, digits or words."),
    # 발광 하이라이트 판 — HUD(선) 대신 대상 전체를 반투명 발광으로 점등 (피라미드 룩)
    "glow_animate": ("The translucent {accent} glow overlay already covering the structure holds "
                     "steady and simply breathes: a very slow, barely-there shift of light across "
                     "its surface, with the edges and ridgelines staying evenly lit. It never "
                     "flashes, strobes, loops or fades out. It highlights exactly one thing: {focus} "
                     "That is what glows — not the biggest or most prominent object in the frame. "
                     "It stays locked to the structure's surface in perspective as the shot "
                     "moves, never spilling onto the ground or sky. The rest of the frame stays "
                     "natural. Pure light only — no letters, digits, words or interface "
                     "elements."),
    # ── 화살표·X·영역 판 (레퍼런스 실측으로 추가) ──────────────────────
    # 공통: 라벨(글자)은 여기서 그리지 않는다. 2K 이미지에 구운 것을 I2V 가 유지할 뿐이다
    # (720p 6초에서 새 글자를 그리게 하면 뭉개진다 — VIDEO_TEXT_KEEP 과 같은 원리).
    "arrow_draw": ("Early in the shot a single bold {accent} arrow draws itself into the scene, "
                   "showing exactly one movement: {focus} The arrow grows from its tail to its "
                   "head along the real path in perspective, reaching full length within the "
                   "first second or so, and then holds. "
                   "Only ONE arrow — never a scatter of arrows, never repeated chevrons, never "
                   "a new arrow appearing later. Once drawn it stays put: it does not slide "
                   "around the frame, loop, blink or fade out. No letters, digits or words."),
    "arrow_animate": ("The bold {accent} arrow already in the frame stays exactly where it is, "
                      "pointing at the same thing at the same size and angle — it never slides "
                      "around, never repeats, never multiplies. It shows one movement: {focus} "
                      "The only animation is a brighter pulse of light running once along the "
                      "arrow from tail to head, after which it settles into a steady glow and "
                      "holds. No looping, no blinking, no fading out, no new arrows."),
    "reject_draw": ("Early in the shot a single large {accent} X is stamped over exactly one "
                    "thing: {focus} The two strokes snap in quickly, one after the other, and "
                    "then the X holds perfectly still for the rest of the clip. "
                    "Just the one X — nothing else is marked, no extra symbols appear, and it "
                    "never slides, spins, blinks or fades out. No letters, digits or words."),
    "reject_animate": ("The large {accent} X already in the frame stays exactly where it is, "
                       "covering the same thing at the same size and angle: {focus} "
                       "It holds steady with only a faint settle of light along its strokes — "
                       "it never slides, spins, multiplies, blinks or fades out."),
    "zone_draw": ("Early in the shot a {accent} outline draws itself around exactly one "
                  "region: {focus} The boundary traces around that region until it closes, and "
                  "the area inside takes on a very faint tint of the same colour. This finishes "
                  "within the first second or so and then holds. "
                  "One region only. Once closed the outline stays locked to that region in "
                  "perspective as the shot moves — it never slides across the scene, never "
                  "resizes, never blinks or fades out. No letters, digits or words."),
    "zone_animate": ("The {accent} boundary already drawn around one region stays locked "
                     "to it: same shape, same size, same place. It encloses one thing: {focus} "
                     "A brighter pulse travels once around the boundary and then it settles into "
                     "a steady glow. It never slides, resizes, multiplies, blinks or fades out."),
    # 만화 기호 판 — anime 톤. 홀로그램·발광 대신 집중선·충격 기호가 '탁' 하고 붙는다.
    # 만화는 원래 정지 기호라, 계속 흐르게 하면 그림이 지저분해진다 → 붙고 나면 멈춘다.
    "manga_draw": ("Early in the shot, cartoon emphasis marks snap into place around exactly one "
                   "thing: {focus} Thick focus lines sweep inward toward it from the edges of the "
                   "frame and a few bold flat impact marks pop in beside it. They land within the "
                   "first second or two and then hold perfectly still for the rest of the clip: "
                   "no looping, no blinking, no drifting, no fading out. They are drawn in the "
                   "same thick dark outline and flat color as the picture — flat shapes only, "
                   "never glowing, never translucent. No letters, digits or words."),
    "manga_animate": ("The cartoon emphasis marks already in the frame hold their place and only "
                      "quiver very slightly, the way a held manga panel does. They keep pointing "
                      "at exactly one thing: {focus} They never multiply, drift, blink or fade "
                      "out, and no new marks are added. Flat shapes in the same outline and color "
                      "as the picture — never glowing. No letters, digits or words."),
    "glow_draw": ("As the shot plays, a translucent {accent} holographic overlay ignites over "
                  "exactly one thing: {focus} That is what lights up — not the biggest or most "
                  "prominent object in the frame. The glow sweeps up from its base to its top as it "
                  "switches on, filling the structure's entire visible volume with soft luminous "
                  "energy — noticeably brighter along its edges, ridgelines and silhouette, with "
                  "a small bright flare at its highest point. The overlay clings exactly to the "
                  "structure's surface and stays locked to it in perspective as the shot moves, "
                  "never spilling onto the ground, sky or neighbouring objects. Everything else "
                  "in the frame stays untouched and natural. Pure light only — no letters, "
                  "digits, words or interface elements."),
}
```


## 3. 영상 네거티브 + 유지 절(글자·홀로그램·룩 잠금) + I2V 템플릿

> VIDEO_TEXT_KEEP / VIDEO_HOLO_KEEP / VIDEO_GAME_LOOK / VIDEO_ANIME_LOOK 은 모두 '시작 프레임에 구워진 요소를 영상이 지우거나 뭉개는' 실패에 대응해 나중에 덧붙인 절이다. MOTION_PROMPT_I2V 가 실제 영상 생성의 뼈대.

```python
# 카메라 워크 제한(whip pan·rapid zoom·shaky 금지)은 풀었다 — 역동 프리셋과 모순이라서.
# 클립 중간 편집 컷만 계속 막는다: 소재는 끊김 없는 원테이크여야 편집에서 자를 수 있다.
# 'HUD readouts' 전면 금지는 글자 없는 도형 HUD(게이지·스캔선·바)까지 지운다 — Motion 이
# 도형을 그리라는데 네거티브가 readouts 를 금지하면 반쪽 게이지가 나온다 (정면충돌).
# → '글자 읽어내기(alphanumeric readouts)'만 금지로 좁히고, 시키지 않은 HUD 장식은
#   별도 줄로 계속 막는다 (주석 없는 컷은 깨끗하게 — 채널 문법 유지).
VIDEO_NEGATIVE = ("Avoid: any text, letters, numbers, captions, subtitles, watermarks, logos. "
                  "Avoid: alphanumeric readouts, serial codes, interface labels, icons, corner "
                  "brackets. Avoid: HUD graphics, gauges or grids that the Motion above did not "
                  "explicitly ask for; when it does ask, they stay bare geometry with nothing "
                  "written on them. "
                  "Avoid: editing cuts or scene changes mid-clip — one continuous shot. "
                  "Avoid: people talking or mouthing words.")
# 시작 이미지에 수치가 구워져 있을 때 (2026-08-10 방침 전환: 지우지 말고 살린다).
# '영상이 새 글자를 그리는 것'은 계속 금지 — 720p에서 뭉개진다("20km"→"2?:00" 실측).
# 2K 이미지에 이미 선명하게 박힌 readout 을 I2V 가 유지하는 건 다른 문제라 지키게 한다.
# (전면 금지를 그대로 두면 모델이 이미지의 숫자를 지우거나 뭉개는 쪽으로 움직인다)
VIDEO_TEXT_KEEP = ("The start frame already carries small text: {m} — keep it exactly as it is: "
                   "in the same place, crisp and legible, locked to the graphic it belongs to "
                   "in perspective as the shot moves. Never blur, erase, redraw, duplicate, "
                   "translate or replace it, and never add any other text.")
VIDEO_NEGATIVE_KEEP = ("Avoid: adding any NEW text, letters, numbers, captions, subtitles, "
                       "watermarks or logos — the one existing HUD readout is wanted; keep it "
                       "sharp and unchanged. "
                       "Avoid: editing cuts or scene changes mid-clip — one continuous shot. "
                       "Avoid: people talking or mouthing words.")
# 시작 이미지에 홀로그램이 구워져 있을 때 — VIDEO_TEXT_KEEP 과 같은 원리의 유지 절.
# motion 이 홀로그램을 재언급하지 않으면 I2V 가 시작 프레임의 미세 발광 요소를 지우거나
# 뭉갠다 (숫자 readout 실측과 동일 계열). _build_motion_prompt 가 홀로 컷에 자동 첨부한다.
VIDEO_HOLO_KEEP = ("The start frame already carries a translucent glowing cyan hologram "
                   "standing in the real scene — keep it for the entire clip: luminous, "
                   "see-through, its thin wireframe edges crisp, locked to its position in "
                   "perspective as the shot moves. Never erase, dim, solidify or duplicate "
                   "it, and keep the real environment around it fully photoreal.")
# game 톤 영상 — RDR·차세대 게임 물리 엔진의 '무게감' 공식 (유레카 ragdoll·지형 흔적·재질별
# 반응을 영상 모델이 그릴 수 있는 현상으로 번역). 스타일은 이미지가 정하고 영상은 물리만 시킨다.
# game 톤 I2V — 룩 유지 절. 영상 모델의 실패 모드는 '실사로의 드리프트'다 (숫자·홀로그램
# 유지 절과 같은 패턴). 시작 프레임의 게임 렌더 룩과 캐릭터 정체성을 클립 내내 잠근다.
VIDEO_GAME_LOOK = ("The start frame is a stylized AAA game-engine render — hold that exact "
                   "in-game look for the entire clip: the same slightly idealized surfaces, "
                   "bold grade and bloom, and the character's exact face and outfit. Never "
                   "drift toward live-action photorealism, and never add any game interface, "
                   "minimap or on-screen indicators.")
# 만화 요약 톤 I2V — 실패 모드는 '정교한 애니로의 드리프트'다 (game 톤의 실사 드리프트와
# 같은 계열). 첫 프레임의 단순 플랫 셀 룩과 캐릭터 생김새를 클립 내내 잠근다.
VIDEO_ANIME_LOOK = ("The start frame is a simple flat cartoon drawing — hold exactly that look "
                    "for the entire clip: the same thick even outlines, the same flat colors "
                    "with no shading or gradients, the same round simple faces with dot eyes, "
                    "and each character's exact hair, face and outfit. Never drift toward "
                    "detailed anime art, 3D, cel shadows, glossy eyes or photorealism, and never "
                    "add new characters, props or background detail that is not already there.")
VIDEO_GAME_PHYS = ("Physical weight everywhere, like a cutting-edge game physics engine: "
                   "bodies move with mass and momentum, staggering and catching their balance "
                   "when pushed; cloth, hair and fur react to motion, wind and wetness; "
                   "footsteps and wheels press real tracks into snow, mud and dust, and grime "
                   "clings to bodies and gear; muscles shift visibly under skin as humans and "
                   "animals move; objects collide and respond by their material — wood "
                   "splinters, metal dents, water wakes and foams. Every impact reads with "
                   "weight; nothing floats or slides weightlessly.")

# 시작 프레임이 있을 때(I2V) — 공식 가이드: "이미지가 이미 피사체·배경·구도·스타일을 정의하므로
# 프롬프트는 액션·카메라·오디오에 집중하라." 장면을 다시 묘사하면 이미지와 싸운다.
# 단 '아무것도 바꾸지 마라'는 금지 — 컷의 존재 이유가 대본상 '변화'(출혈이 멈춤, 수지가 굳음)인데
# 그 지시가 Motion 을 눌러 미세 움직임만 나온다. 스타일·정체성만 잠그고 변화는 허용한다.
# 첫 프레임부터 움직임 진행 중 — 쇼츠는 첫 0.5초 정지면 스와이프당한다.
MOTION_PROMPT_I2V = """Animate the provided start frame.

Camera: {camera}
Motion: {motion}

Keep the start frame's style, subject identity, lighting and color grade —
but the Motion above is the whole point of this shot: let it visibly transform
the scene as described, not just idle micro-movement.
The motion is already underway on the very first frame — never open on a frozen,
settling shot.
{tempo}

{audio}
{negative}"""
```


## 4. 대표 톤 블록 예시 (docu3d · blueprint · aerial · xsection)

> 톤은 15종이며 여기 4종만 발췌. 스타일 블록은 '어떻게 보이는가'만 정하고 '무엇을 보여주는가'는 SUBJECT 가 정한다.

```python
    "docu3d": """Style: rendered as a cinematic on-location 3D reconstruction — the camera is
standing at the real site, not looking at a model on a table. The subject sits in its actual
environment with real ground, weather and atmosphere: haze hanging in the air, light raking
across surfaces, terrain and structures receding into depth behind it. Real scale, real place.
Materials keep their own character — pale limestone, cold steel, weathered timber, damp earth,
oxidised copper, wet rock — held at restrained saturation so nothing shouts.
Graded like a cinema feature: shadows carry a cool navy tint while highlights stay warm and clean,
strong contrast, fine filmic texture. **The scene keeps its own natural light** — a sunlit noon
courtyard stays bright and open, an overcast morning stays soft, a night storm stays dark.
Never force gloom onto a scene that should be lit, never a flat blue wash,
never a studio backdrop, never a plinth or display stand.
Photoreal-leaning 3D with clean readable forms and crisp surface detail.
Immersive, precise, expensive-looking. If any cool cyan light appears in the scene itself
(a lamp, a reflection), keep it subtle — the frame stays clean unless an annotation,
or a holographic reconstruction described in the SUBJECT, is explicitly asked for.""",
    # ⑩ blueprint — 1분공구리류 설계 도해. 다크 네이비 + 백색 선화 + 네온 하이라이트 하나
    "blueprint": """Style: rendered as a technical blueprint diagram on a dark navy drafting board.
Clean white line-work with precise dimension lines and hatching, one or two elements
highlighted with a single glowing neon accent (cyan or red).
Flat orthographic or simple section view, engineering-drawing aesthetic,
but NO readable text, numbers or labels. Minimal, precise, analytical.""",
    # ⑪ aerial — 실사 드론 항공. arch3d(3D 렌더 전경)와 달리 '진짜 항공 촬영' 룩
    "aerial": """Style: rendered as real aerial drone photography shot from high above
on a full-frame camera. Photorealistic city, terrain or infrastructure seen from the air,
natural atmospheric haze and sunlight, crisp detail, documentary realism —
looks like actual drone footage, not a 3D render.""",
    # ⑫ xsection — 단면 실험. 핵심은 '속이 보이는 것'이지 수조가 아니다.
    # 잘린 단면·투명 벽·반으로 가른 모형 중 장면에 맞는 방법을 모델이 고르게 둔다.
    "xsection": """Style: rendered as a real tabletop demonstration where the subject is opened up
so the inside is visible — sliced clean through, cut in half, or held against a transparent wall,
whichever suits it. Internal layers, channels and structure exposed at eye level.
Built from real physical materials in a bright studio: clean neutral background,
soft even lighting, tack-sharp macro detail, shallow but readable depth.
Looks like practical-effects science footage, not CG.""",
    # ⑨ labmacro — 실험 쇼츠 실사 룩 (레퍼런스: 갈륨·우라늄 등 테이블탑 실험 채널).
    # 어두운 무채색 테이블 + 검은 니트릴 장갑 + 고정 매크로. 카메라는 안 움직이고 피사체가 변한다.
```


## 5. 컷 분해 LLM 규칙 (한국어 · 발췌)

> 대본을 컷으로 나누는 LLM에게 주는 지시. '캐논 문구'(반복 피사체 동일 묘사), chain 판단 기준, 홀로그램 재구성 문법이 여기 있다. 여기에 '인과 1단계 규칙'과 '분해뷰(exploded view) 문법'을 추가하려 한다.

```python
[1. 분해 규칙]
1. 컷은 {n_cuts}개 내외.
   **한 컷의 대사는 공백 포함 {chars_lo}~{chars_hi}자**로 묶어라 — 낭독 4~8초에 해당한다.
   짧은 문장은 **바로 앞뒤 문장과 한 컷으로 묶는다.** 단 장면·피사체가 바뀌는 자리는 묶지 마라.
   (2초짜리 컷은 영상 모델이 만들 수 없어 결국 앞뒤와 합쳐진다 — 처음부터 묶는 편이 낫다)
   **지시어 정합 — 묶는 방향을 정하는 규칙**: "이게/이 문/그것"처럼 앞 문장의 피사체를
   가리키는 대사는 반드시 **그 피사체가 화면에 보이는 컷에** 묶는다.
   (예: "대체 이게 어떻게 성을 무너뜨렸을까요?"는 목마 컷의 **마지막** 문장이지, 다음 장면
   (야영지)의 첫 문장이 아니다 — 화면에 없는 것을 '이게'라고 부르면 시청자가 길을 잃는다)
   **대사 전량 커버**: 대본의 모든 문장은 순서대로 **정확히 한 컷의 line 에** 속해야 한다 —
   누락·중복·바꿔쓰기 금지, line 은 원문을 글자 그대로 복사한다. (자막·음성 타이밍이 line 의
   글자 수로 정렬되므로, 한 문장이 빠지거나 달라지면 뒤 컷 전체의 타이밍이 밀린다)
2. **첫 문장(훅)은 반드시 독립 컷.** 가장 자극적이고 이상한 그림을 뽑아라.
3. **`chain`(이어짐) — 앞 컷과 같은 공간·같은 대상을 연속으로 보여줄 때만 true.**
   판단 기준 한 줄: "**앞 컷의 그림에서 카메라가 멈추지 않고 그대로 이어서 움직여도 말이 되는가?**"
   (영상 생성은 앞 컷 이미지에서 출발해 이 컷 이미지로 도착한다 — 두 그림이 한 공간 안에
    있어야 그 사이를 이어 그릴 수 있다. 공간이 다르면 모델이 억지로 워프시켜 어색해진다.)
   · 켠다: ①한 공간을 파고들 때 (전경 → 다가감 → 내부) ②같은 대상의 상태가 변할 때
     (물이 차오름, 구조물이 무너짐, 불이 번짐)
   · 끈다: 장소·피사체·시대가 바뀌면 **무조건 false**. 도해·자료화면으로 넘어갈 때도 false.
   · 묶음의 **첫 컷은 false**, 이어지는 2~3번째만 true.
   · **한 영상에 묶음은 최대 2개, 묶음당 최대 3컷.** 대부분의 컷은 false 다 —
     장면이 바뀌는 게 정상이고, 이어짐은 예외적으로 쓰는 장치다. 애매하면 false.
3-1. **전환의 대비 — 몰입은 '이어짐'만큼 '끊김'이 만든다.**
   · `chain=false` 인 컷은 **장면 전환 지점**이다. 앞 컷과 **확실히 다른 그림**을 잡아라 —
     같은 각도·같은 거리에서 피사체만 바꾸면 전환이 아니라 실수처럼 보인다.
     (거리를 바꾸거나 — 원경↔매크로, 시점을 바꾸거나 — 밖↔안, 밝기를 바꿔라)
   · 이어짐 묶음은 **한 방향으로 진행**시켜라. 전경 → 다가감 → 내부처럼 한 걸음씩 들어가야지,
     들어갔다 나왔다 하면 어지럽다.
   · 대본의 전환어("그래서", "그런데 여기서", "진짜 문제는")가 나오는 자리는 **반드시 chain=false**.
     말이 꺾이는 지점에서 화면도 같이 꺾여야 시청자가 따라온다.
   · **같은 핵심 피사체의 '전신 샷'을 체인이 아닌데도 연달아 놓지 마라.** 컷은 독립 생성이라
     같은 물건도 매번 디테일이 조금씩 다르게 나온다 — 전신이 연속되면 그 차이가 바로 보인다.
     캐논 문구([1]의 반복 피사체 규칙)로 편차를 줄이되, **배치로도 숨겨라**: 대사가 허락하면
     사이에 다른 피사체 컷을 끼우거나, 한쪽을 부분 디테일(밧줄 매듭·바퀴·나뭇결 매크로)로
     잡아라. 부분 클로즈업은 '같은 물건의 일부'로 읽혀 디자인이 달라도 티가 나지 않는다.
4. 숫자·등급은 글자로 그리지 마라. 그 숫자가 뜻하는 상태를 사물로 보여준다.
5. 특정 실제 제품을 지목하는 컷은 type=product, `search_ko` 에 검색어. subject_en 도 채운다 —
   기본은 실물 검색이지만 사용자가 [AI로 전환]할 수 있어야 한다 (상표·로고는 빼고 일반형으로 묘사).
6. 브랜드명·로고·모델명 금지. 사람은 손·팔·뒷모습·실루엣 위주, 얼굴은 알아볼 수 없게.
   (game 톤 컷만 예외 — 스타일라이즈드 게임 캐릭터 얼굴은 보여도 된다. 실존 인물 닮기는 계속 금지)
7. **반복 피사체 캐논 — 2컷 이상 다시 나오는 핵심 피사체(주인공 구조물·기계·물건·건물)는
   생김새를 한 번 확정하고, 등장하는 모든 컷에 같은 문구로 써라.**
   · 재질·색·형태·비율·마모 상태까지 박은 상세 영어 묘사 한 구(캐논 문구)를 만들고, 그 피사체가
     나오는 **모든 컷의 subject_en 앞머리에 토씨 하나 바꾸지 말고 그대로 복사**하라.
     컷마다 달라지는 것(구도·거리·행위·주변 상황·홀로그램)은 캐논 문구 **뒤에** 덧붙인다.
     (예: 캐논 "a colossal wooden horse built from weathered dark ship planks, rope lashings
      and bronze nails, standing on a crude wheeled sled" → 컷A "..., towering before the
      city gate at dawn" / 컷B "..., split open lengthwise revealing the hollow interior")
   · 각 컷은 서로를 모르는 독립 생성이라 **같은 문구가 유일한 연결고리다.** 컷마다 묘사를
     새로 쓰면 매번 다른 물건이 나온다 — weather_en 의 '같은 현장 = 같은 대기' 규칙과 같은 이유.
   · 배경 소품·행인처럼 매번 달라도 티 안 나는 것은 제외. 이야기의 주인공 피사체에만 써라.

[2. beat — 이 컷이 대본에서 맡은 역할. 반드시 하나 부여]
hook(훅) / context(정체·결핍·배경) / constraint(제약·뻔한답 기각·에스컬레이션) /
despair(절망 비트) / pivot(발상 전환 선언) / solution(해법·반전 보상) /
analogy(생활 비유·대조군) / closing(여운·감정 낙인)

[3. beat별 톤 기본값 — style 을 이 기준으로 채워라]
docu3d 가 이 채널의 대표 톤이다. 건축물·유적·구조물·현장을 '그 자리에 서서' 보여주는 컷,
즉 훅·구조 설명·해법 증명 컷의 기본값으로 docu3d 를 먼저 검토하라.
hook→docu3d 또는 cine / context(과거·역사·서사)→archive, (현재 상황)→snap
constraint·despair→docu3d 또는 tech3d(단면으로 문제가 '생기는' 과정)
pivot·solution→docu3d(현장 재현) 또는 tech3d(도해로 원리를 짚을 때)
analogy→snap(부엌·욕실 등 생활 장면) / closing→docu3d·arch3d(전경) 또는 snap
미시·인체는 sci3d, 전경·건설·지형은 arch3d. 실사로 못 만드는 과장은 illust.
실물 실험·시연·제품 데모(테이블 위에서 만지고 반응이 일어나는 장면)는 labmacro.
**단, 대본이 한 현장(건축물·유적·공사장·자연 지형)의 이야기를 이어가는 중이라면
labmacro·xsection·tech3d 로 빠지지 마라.** 이 톤들은 배경을 비우고 스튜디오·검은 배경으로
가기 때문에, 현장 이야기 한복판에 끼면 시청자가 장소를 잃는다. 그 자리에서 원리를 설명해야
하면 docu3d 를 유지하고 subject_en 에 클로즈업 대상을 적어라
(예: "close on two granite blocks locking together on the wet rock, storm sea behind").
실험실·공장·테이블이 실제로 대본에 나올 때만 위 세 톤을 써라.
설계·치수·구조 비교·금지(X) 설명은 blueprint(청사진 도해).
도시·지형·시설을 하늘에서 부감할 땐 aerial(실사 드론 항공).
**인물이 이야기를 끌고 가는 재연 컷**(역사적 사건의 재연, 썰쇼츠형의 인물 서사·감정 장면)은
game(게임 렌더) — **유일하게 얼굴·표정이 나와도 되는 톤**이다. 주인공은 뒷모습 어깨너머(OTS)
구도를 우선하고, 감정이 요점인 순간에만 정면·클로즈업을 써라. 시대 의상·소품·장소의 생활감을
subject_en 에 구체적으로 담아라. 실존 인물(왕·장군·근현대 유명인)은 game 톤이라도 실제 얼굴을
닮게 그리지 마라 — 매번 창작 얼굴로. 원리·구조 설명 컷에는 game 을 쓰지 마라(그건 docu3d·tech3d).
장소가 주인공인 훅은 '위성 줌인' 패턴이 강하다: 훅 컷을 aerial 로 잡고 subject_en 에 위성·항공
시점을 명시한 뒤, 다음 컷을 chain=true 현장 컷으로 이으면 지도에서 현장으로 내리꽂는 오프닝이 된다.
속·단면을 갈라 원리를 증명하는 컷(층이 드러나고 안에서 무슨 일이 일어나는지)은 xsection(단면 실험).
힘·흐름·방향을 설명하는 컷은 subject_en에 glowing flow lines 또는 luminous arrows를 명시하라.
톤은 '주 톤 + 양념' 구조로 짜라. 영상 전체의 절반 안팎은 대표 톤(주로 docu3d)으로 밀어
채널 색을 유지하고, 나머지를 archive·snap·tech3d·illust 등으로 섞어 흐름에 변화를 준다.
대표 톤은 연속으로 와도 되지만, 보조 톤(archive·snap·illust 등)은 3연속으로 쓰지 마라.

[3-1. 홀로그램 재구성 — 카메라로 찍을 수 없는 것만 실사 현장 위에 겹쳐라]
실사 현장 위에 시안 홀로그램(와이어프레임 + 반투명 볼륨)을 겹쳐, 지금 그 자리에 없는 것을
재구성하는 연출이다. 별도 필드는 없다 — **subject_en 과 motion_en 에 직접 써넣는다.**
docu3d·arch3d·aerial·cine 톤의 현장 컷에서만 쓴다.
· **홀로그램은 반드시 subject_en 에 완성된 모습으로 써서 이미지에 굽는다.** 영상 모델이
  가는 와이어프레임을 새로 그리면 뭉개진다 — motion_en 은 점등·맥동·스캔·소멸처럼
  '이미 서 있는 홀로그램의 변화'만 시켜라. 무에서 조립되는 과정(assembles itself)은 금지.
  '나타나는 순간'이 필요하면 chain 을 써라: 앞 컷을 홀로그램 없는 같은 현장 실사로 잡고
  이 컷을 chain=true 로 이으면 앞 클립이 이 컷 이미지로 도착하며 홀로그램이 자연스럽게
  떠오른다 ([1]-3 묶음 규칙과 weather_en 동일 문구 규칙은 그대로 지켜라).
· 켜는 조건 — 대사가 다음 넷 중 하나를 말할 때만:
  ① 과거 재구성(사라진 구조물·원래 모습): beat=context·solution. 대사 신호 "원래는",
     "당시에는", "지금은 사라진".
     subject_en 예: "the surviving stone foundation of the ruined hall at dusk; above it, a
     translucent glowing cyan wireframe hologram of the vanished wooden superstructure stands
     reassembled in its original position, thin luminous edges and faint transparent volumes,
     while the real ruin and the landscape stay fully photoreal"
  ② 투시 재구성(숨은 내부·지하·가려진 구조): beat=constraint·solution. 대사 신호 "속에는",
     "벽 뒤에", "기초는", "땅속에". **'벽 안에 보인다'가 아니라 벽 위에 겹쳐 그린 투영이다**
     — 실물 벽은 끝까지 불투명하게 두어라 (껍질이 투명해지는 xray 와는 다른 연출이다).
     subject_en 예: "the massive stone facade fully opaque and photoreal; superimposed OVER it
     like a projection, a glowing cyan wireframe hologram of the hidden timber skeleton, drawn
     at the exact position and scale of the structure behind the wall"
  ③ 비교·대안(기각되는 뻔한 답, 만약 ~였다면): beat=constraint·pivot. 대사 신호 "그냥
     ~하면 되지 않냐", "~했다면 어땠을까". 대안 설계를 실물 옆에 홀로그램으로 세워 굽고,
     영상에서 **한 번에** 무너뜨려라 — 다단계 액션은 모델이 중간을 건너뛴다.
     motion_en 예: "the translucent cyan hologram of the conventional straight wall standing
     beside the real structure buckles and shatters into fading cyan fragments that dissolve
     in mid-air, while the real scene around it stays still and photoreal"
  ④ 스케일 비교(크기를 익숙한 것으로): beat=hook·context. 대사 신호 "아파트 ~층 높이",
     "축구장 ~개 넓이". 익숙한 사물의 홀로그램을 실물 옆에 실제 비율로 세운다.
     subject_en 예: "the real dam wall in morning haze; beside it a translucent glowing cyan
     wireframe hologram of a ten-storey apartment building stands at true scale for height
     comparison, thin luminous edges, the entire real landscape photoreal"
· motion_en 규칙 — 홀로그램 컷의 motion_en 은 **반드시 홀로그램을 언급**하고(언급이 없으면
  영상 모델이 지워버린다) 점등·맥동형으로 써라. 문장 끝에 이 고정 절을 그대로 붙여라:
  "while the real scene around it stays still and photoreal".
  motion_en 예: "the cyan wireframe hologram brightens to full presence, its edges pulsing
  gently and a faint scan shimmer passing across its translucent surfaces, while the real
  scene around it stays still and photoreal"
· 카메라가 격하면 헤어라인이 지글거린다 — 홀로그램 컷은 still·push·orbit 계열이 어울린다.
· 절대 끄는 조건: 실물로 그냥 찍으면 되는 대상(보이는 것을 홀로그램으로 또 그리지 마라),
  analogy(생활 비유)·closing(여운) 컷, 분위기·감정 컷,
  archive·snap·illust·labmacro·xsection·blueprint·tech3d·sci3d 톤.
· **다큐의 선 — 최우선 규칙.** 배경·지면·하늘·실물은 끝까지 100% 실사이고, 홀로그램은
  프레임 속 소수 요소 하나다. 화면 전체를 덮는 그리드·파티클·디지털 배경·홀로그램 도시
  전경은 금지 — 그 순간 다큐가 아니라 SF가 된다. 홀로그램이 화면의 주인이 되면 실패다.
· **한 영상에 최대 1~2컷, 연속 컷 금지.** 애매하면 쓰지 마라 — 실물이 이긴다.
· **홀로그램 컷은 focus_en 과 measure_en 을 반드시 빈 문자열로 둬라.** 홀로그램 자체가 이
  컷의 강조 장치다 — HUD·발광 주석까지 겹치면 두 벌 강조로 화면이 SF 광고가 된다.
· 홀로그램에도 글자·숫자는 금지. 순수한 선과 반투명 면만.

[4-a. focus_en — 주석이 가리킬 단 하나]
대사가 **무언가를 설명하는 컷**일 때만 채운다. 그 문장이 말하는 대상·현상 하나를 영어로.
**그 순간 대사가 "이걸 보라"고 말하는 바로 그 물체·부위여야 한다** — 화면에서 가장 큰 것도,
그 컷의 주인공 전체도 아니다. 대사가 "돌끼리 맞물린 부분"을 말하면 등대 전체가 아니라
맞물린 이음매 하나이고, "파도가 때리는 밑동"이면 탑이 아니라 밑동이다.
대사를 다시 읽고, 그 문장에서 시청자가 눈으로 확인해야 하는 것을 그대로 적어라.
분위기 컷(훅의 풍경, 감정, 마무리)은 빈 문자열 — 주석 없이 깨끗한 화면이 낫다.
예외: 훅에서 숫자 하나가 결정적일 때(예: "20km나 떨어진")는 focus_en 과 measure_en 을
함께 채워라 — 첫 2초에 숫자가 박히면 시청자를 잡는다.
홀로그램 재구성 컷([3-1])과 그래픽 애니메이션을 붙인 컷([4])은 반드시 빈 문자열 —
강조 장치는 컷당 하나다. 홀로그램·그래픽 위에 주석을 또 얹지 않는다.
**한 영상에서 3~4컷만 채워라.** 매 컷 강조가 켜지면 그건 강조가 아니라 배경이고, 시청자
시선이 대사가 아니라 화면 여기저기의 HUD 를 따라다닌다. 대사가 물체를 콕 집어 설명하는
컷만 남기고 나머지는 비워라. 채우지 않은 컷에는 주석이 그려지지 않는다.
(4컷을 넘기면 코드가 약한 컷부터 자동으로 끈다 — 네가 아껴 쓸수록 네가 고른 컷이 살아남는다)

[4-b. measure_en — 화면에 새길 수치]
대사에 숫자가 나오고 그게 **이 컷의 요점**일 때만 채운다 (예: "20km나 떨어진" → "20km",
"46년을 버텼는데" → "46Y", "40분이면 다 타서" → "40min", "두 개씩 붙어" → "x2").
분위기·감정 컷이나 숫자가 곁가지면 빈 문자열. 한 영상에서 3~5컷을 넘지 않게 아껴 써라 —
전부 붙이면 정보 과잉이 된다.
**중요: measure_en 은 focus_en 이 채워진 컷에만 넣어라.** 수치는 주석 치수선 위에 얹히므로
가리킬 대상이 없으면 화면에 나오지 않고 버려진다. 숫자를 새기고 싶으면 focus_en 도 채워라.
마무리(closing) 컷은 여운이 목적이라 수치를 넣어도 화면에 안 나온다 — 넣지 마라.

[4-d. anno_kind · anno_label — 강조를 무엇으로 그릴까]
focus_en 을 채운 컷에만 정한다 (비운 컷은 둘 다 빈 문자열).
**강조는 "이걸 보세요"가 아니라 "이게 이렇게 됩니다"를 그리는 것이다.** 그 컷 대사가 말하는
논리에 맞는 도구를 골라라 — 레퍼런스 채널이 실제로 쓰는 다섯 가지다:

· arrow  — 움직임·경로·흐름·상승/하강을 말할 때. **가장 많이 쓰는 도구다.**
           "물이 지하수까지 차오릅니다" / "물길을 이쪽으로 돌립니다" / "하중이 이렇게 흐릅니다"
· reject — 안 되는 방법·실패·금지를 말할 때. beat=constraint·despair 와 짝이 맞는다.
           "그렇게는 안 됩니다" / "5년 만에 통째로 쓸려갔죠" / "이 방법은 못 씁니다"
· zone   — 부위 하나가 아니라 **구역·범위**를 통째로 말할 때.
           "이 일대가 전부 잠깁니다" / "여기가 지반이 약한 구간입니다"
· hud    — 치수·수치·계측. measure_en 이 있으면 거의 항상 이것.
           "높이가 45m입니다" / "두께 3.5m로 쌓았죠"
· glow   — 와이드·항공에서 구조물 **전체**를 지목할 때. 부분 설명에는 쓰지 마라.

anno_label 은 그 대상의 짧은 영문 이름이다 (Steel Lid · Trench · Dry Floor · Inner Fill ·
Sand Trap 처럼 대문자로 시작하는 1~2단어). 이름이 있으면 화면이 훨씬 잘 읽힌다.
**한글은 쓰지 마라** — AI 가 글자를 뭉갠다. 마땅한 영어 이름이 없으면 빈 문자열로 두어라.
라벨은 이미지에만 새겨지고 영상은 그것을 그대로 유지한다.

[4-c. chars — 이 컷에 나오는 인물 (anime 톤 전용)]
작품요약형(C)에서만 채운다. 캐릭터 시트의 라벨 **한 글자**를 배열로: ["A"], ["A","B"] 처럼.
그 컷에 실제로 프레임 안에 있는 인물만 적어라 — 한 컷에 셋을 넘기지 마라(작게 뭉개진다).
인물이 안 나오는 컷(텅 빈 코트, 전광판, 배경만)은 빈 배열.
**이름을 쓰지 마라** — 시트에는 A·B·C·D 라벨만 있어서 이름으론 누구인지 못 짚는다.
같은 인물은 영상 내내 같은 라벨이어야 한다. 라벨 배정은 첫 등장 순서대로 A부터.
anime 가 아닌 톤에서는 항상 빈 배열.

[4-c. weather_en — 날씨·대기 (사실감 레이어)]
현장(야외·실물 공간) 컷에 채운다 — 공기 중에 보이는 것을 영어 짧은 구로.
(예: "dry heat haze, fine sand dust drifting low" / "cold sea spray and storm wind" /
 "thin morning mist hanging over the water" / "dust motes in shafts of light")
· 대본에 단서(폭풍·비·사막·바다·겨울…)가 있으면 반드시 그걸 따르라.
· 단서가 없으면 장소와 이야기 정서에 어울리는 것 **하나만** 골라라.
· **같은 현장을 보여주는 컷들은 전부 같은 대기를 그대로 복사해 써라** — 특히 chain 묶음은
  동일 문구여야 한다. 컷마다 날씨가 바뀌면 한 장소가 여러 장소처럼 보인다.
· 시간대(새벽·한낮·노을·밤)는 별도 필드가 없다 — 대본에 단서가 있을 때만 이 필드에 함께
  녹여라 (예: "golden late-afternoon light through drifting dust"). 단서가 없으면 넣지 마라.
· 스튜디오·도해·자료화면 컷(labmacro·blueprint·illust·xsection, screen 샷)은 빈 문자열.
```
