# AI 쇼츠 파이프라인 브리핑 — 구체적 조언 요청용

너(GPT)가 준 "Universal Cinematic Mechanism Visualization" 마스터 프롬프트를 검토했다.
우리는 이미 상당 부분을 구현했고, 이제 **일반론이 아니라 아래 실제 시스템·실제 프롬프트에 맞춘
구체적 개선안**이 필요하다. 먼저 시스템을 설명하고, 끝에 구체 질문 6개를 묻는다.

---

## 1. 파이프라인 개요

1. 한국어 나레이션 대본 (쇼츠 30~60초) 작성
2. LLM이 대본을 **컷 단위로 분해** — 컷당 낭독 4~8초. 각 컷에 부여:
   - `beat` (hook/context/constraint/despair/pivot/solution/analogy/closing)
   - `style` (아래 톤 15종 중 1개), `shot` (wide/medium/close/macro/pov)
   - `subject_en` (이미지 프롬프트 재료), `motion_en` (영상 모션 지시)
   - `chain` (앞 컷과 같은 공간이면 true — 영상이 이어짐)
3. 컷마다 **2K 정지 이미지 생성** (Gemini 이미지 모델, 9:16)
4. 컷마다 **I2V 영상 생성** (Veo 3.1 계열 / Seedance 1.5 Pro, 720p, 4/6/8초)
   - 시작 프레임 = 이 컷의 이미지 (API 파라미터로 전달)
   - **도착 프레임 = 다음 컷의 이미지** (chain 컷일 때, API `lastFrame` 파라미터)
5. 편집 프로그램(캡컷)에서 나레이션·자막과 합쳐 완성

핵심 구조: **컷들은 서로를 모르는 독립 생성**이다. 일관성은 오직
(a) 동일한 영어 묘사 문구의 반복(아래 '캐논 문구'), (b) 체인의 시작/도착 프레임으로만 확보된다.

## 2. 이미 구현된 설계 원칙 (이걸 전제로 답해달라)

- **캐논 문구**: 2컷 이상 등장하는 핵심 피사체는 재질·색·형태·비율을 박은 영어 묘사 한 구를
  확정하고, 등장하는 모든 컷의 subject_en 앞머리에 그대로 복사한다. (네 §1 Identity Lock에 해당)
- **톤 15종**: docu3d(현장 3D 재구성, 대표 톤) · tech3d(도해, 강조 1색) · xsection(단면 실험) ·
  blueprint(청사진) · sci3d · arch3d · aerial · cine · snap · archive · illust · anime · game ·
  labmacro · product. 톤별로 스타일 블록 + 전용 네거티브가 프롬프트에 붙는다.
- **홀로그램 원칙 (실측 교훈)**: 카메라로 찍을 수 없는 것(사라진 구조·벽 뒤 내부)은 실사 위에
  시안 와이어프레임 홀로그램으로 겹친다. **홀로그램은 반드시 이미지에 완성된 모습으로 굽고,
  영상은 '이미 서 있는 홀로그램의 변화'(점등·맥동·소멸)만 시킨다** — 영상 모델이 가는 선을
  새로 그리면 뭉개진다. '나타나는 순간'은 체인으로 해결(홀로그램 없는 이미지 → 있는 이미지 도착).
- **HUD/주석 VFX 문법**: 컷당 강조 대상 1개(focus). 윤곽선은 마킹하는 모서리에서 자라나
  1초 내 완성 후 **고정**(깜빡임·재스캔·페이드아웃 금지 — 편집 자막을 위에 얹어야 해서
  일부러 사라지지 않게 한다). 원근에 잠김. 글자는 이미지에 구운 것만 유지, 영상이 새로
  그리는 글자는 전면 금지(720p에서 붕괴).
- **모션 원칙**: 컷당 카메라 워크 1개(프리셋 22종). I2V 프롬프트는 장면을 다시 묘사하지 않고
  카메라+모션+오디오만 지시. 첫 프레임부터 움직임 진행 중이어야 함(쇼츠 스와이프 방지).

## 3. 실측으로 확인된 실패 모드 (이 제약 안에서 답해달라)

- 720p 영상이 글자를 새로 그리면 붕괴한다 ("20km" → "2?:00")
- 영상 모델이 가는 와이어프레임·헤어라인을 새로 그리면 뭉개진다 → 이미지에 굽는 것만 안전
- **다단계 액션은 중간을 건너뛴다** — "A가 무너지고 B가 드러나고 C가 빛난다"를 시키면
  A→C로 점프한다. 한 클립에 큰 액션 1개가 한계
- 스타일 드리프트: game 톤은 실사로, anime 톤은 정교한 애니로 흘러간다 → 룩 잠금 절 필수
- HUD가 물체 위를 '미끄러지는' 오독 ("traces along" → 막대가 제품 위를 슬라이드)
- 프롬프트끼리 싸우면 반쪽 결과가 나온다 (네거티브가 모션 지시와 충돌한 사례 있음)

## 4. 실제 산출물 샘플 — "트로이 목마" 편, 컷 9 (내부 단면 컷)

### 4-1. 이미지 프롬프트 (실제 생성 사용분, 요약 없이 원문)

```
SUBJECT: cross section view of a massive ancient Trojan wooden horse crafted from rough
weathered dark timber planks, revealing a hollow interior packed with fully armed ancient
Greek soldiers holding swords

Setting: inside wooden horse cavity.
Shot: clean cross-section cutaway showing the internal structure, sliced open

Style: rendered as a cinematic on-location 3D reconstruction — the camera is standing at
the real site, not looking at a model on a table. (…이하 docu3d 스타일 블록·재질·그레이딩 지시…)

A holographic technical HUD in glowing cyan (#22D3EE) switches on over the scene.
It reads exactly ONE thing: a hollow interior packed with fully armed ancient Greek soldiers.
(…한 개의 헤어라인 윤곽선 + 치수선 1개, 픽셀 굵기·블룸·금지 사항 상세 지시…)
The dimension line carries the readout "x30" once. It is the ONLY text in the frame.

Avoid: subtitles, watermarks, logos… / Avoid: cluttered background, harsh flash, motion blur…
```

### 4-2. 같은 컷의 영상(I2V) 프롬프트 (원문)

```
Animate the provided start frame.

Camera: push-in while drifting downward at the same time, closing in as the framing travels down
Motion: luminous cyan arrows stream out from inside the wooden belly towards the rear exit hatch

The glowing cyan HUD visible in the provided frame is where the overlay ENDS UP — not how it
looks at the start. Open the clip with that overlay not yet there, and draw it on: the hairline
grows out from one end of the edge it marks (…1초 내 완성 후 고정, 슬라이드 금지, 루프 금지…)

The start frame already carries small text: "x30" / "Hidden Troop" — keep it exactly as it is (…)

Keep the start frame's style, subject identity, lighting and color grade — but the Motion above
is the whole point of this shot: let it visibly transform the scene.
The motion is already underway on the very first frame.

(템포 절 + 사운드 절 + 네거티브: 새 글자 금지 / 클립 중간 편집 컷 금지 / 대사 금지)
```

## 5. 구체 질문 — 이 시스템에 바로 넣을 수 있는 문구로 답해달라

1. **Exploded View를 이 파이프라인으로 만드는 최적 패턴은?**
   우리 계획: 분해 상태를 이미지에 굽고(subject_en: 부품이 실제 조립 축을 따라 분리,
   방향 유지) 영상은 재조립만 시킨다. 또는 체인 2컷(분해 이미지 → 조립 이미지 도착).
   이 두 방식의 subject_en / motion_en **실제 문구 예시**를 각각 써달라.
   (제약: 다단계 액션 불가, 4~8초, 부품이 임의 회전하며 흩어지는 실패를 막아야 함)

2. **단면(xsection) 컷에서 모핑 억제 네거티브 문구는?**
   "물체가 휘거나 녹으며 열리는" 변형을 막는, Veo가 실제로 알아듣는 Avoid 문구를 제안해달라.

3. **도착 프레임(lastFrame) 전환 품질**: 지금은 API 파라미터만 주고 프롬프트에 전환 방식
   지시가 없다. "크로스페이드/모핑이 아니라 물리적 카메라·피사체 동작으로 도착하라"는 절을
   넣으면 나아질까, 아니면 "Motion이 장면을 변화시켜야 한다" 절과 싸울까? 문구를 제안해달라.

4. **흐름(Flow) VFX 문법**: 네 §13(SOURCE→PATH→INTERACTION→OUTPUT)을 4~8초 클립의
   motion_en 한두 문장으로 압축하면? 컷 9의 "arrows stream out from the belly towards the
   hatch"보다 나은 실제 문구 패턴을 (힘/물/공기/열 각 1개씩) 예시로 써달라.

5. **인과 1단계 규칙**: 메커니즘 컷의 motion_en을 "A moves → B responds" 인과 1단계로
   제한하는 규칙을 컷 분해 LLM 프롬프트에 넣으려 한다. LLM이 잘 따르도록 예시 2개를 포함한
   규칙 문구를 한국어로 써달라.

6. **네 §15 효과 어휘(pulse=에너지, heat distortion=열 등) 중 Veo 3.1이 720p에서
   실제로 안정적으로 그리는 것과 피해야 하는 것**을 경험적으로 구분해달라.
   (우리 실측: 헤어라인 신규 생성 = 실패, 글자 신규 생성 = 실패, 이미 구운 발광 요소 유지 = 성공)
