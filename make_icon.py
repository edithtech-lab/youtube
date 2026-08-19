'''통합 수집기 아이콘 생성 — 에메랄드 라운드 사각형 + 흰색 깔때기(수집) 글리프'''
from PIL import Image, ImageDraw

S = 512  # 고해상도로 그린 뒤 축소 (안티에일리어싱)
img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 라운드 사각형 배경 (에메랄드 세로 그라데이션)
radius = int(S * 0.24)
top = (52, 211, 153)     # #34d399
bot = (5, 150, 105)      # #059669
grad = Image.new('RGBA', (S, S), (0, 0, 0, 0))
gd = ImageDraw.Draw(grad)
for y in range(S):
    t = y / S
    r = int(top[0] + (bot[0] - top[0]) * t)
    g = int(top[1] + (bot[1] - top[1]) * t)
    b = int(top[2] + (bot[2] - top[2]) * t)
    gd.line([(0, y), (S, y)], fill=(r, g, b, 255))
mask = Image.new('L', (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=radius, fill=255)
img.paste(grad, (0, 0), mask)

# 흰색 깔때기 (여러 소재 → 하나로 수집)
W = (255, 255, 255, 255)
cx = S // 2
# 깔때기 몸통: 넓은 위 → 좁은 아래 + 짧은 배출구
funnel = [
    (int(S*0.24), int(S*0.34)),   # 좌상
    (int(S*0.76), int(S*0.34)),   # 우상
    (int(S*0.565), int(S*0.60)),  # 우 수렴
    (int(S*0.565), int(S*0.80)),  # 배출구 우하
    (int(S*0.435), int(S*0.80)),  # 배출구 좌하
    (int(S*0.435), int(S*0.60)),  # 좌 수렴
]
d.polygon(funnel, fill=W)

# 위쪽에 모여드는 3개 점 (수집되는 소재)
rr = int(S * 0.052)
for dx, dy in [(-0.145, -0.045), (0.0, -0.075), (0.145, -0.045)]:
    x = cx + int(S * dx)
    y = int(S * 0.27) + int(S * dy)
    d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=W)

# 멀티사이즈 .ico 저장
sizes = [16, 24, 32, 48, 64, 128, 256]
icons = [img.resize((s, s), Image.LANCZOS) for s in sizes]
icons[0].save('C:/dev/collector/icon.ico', format='ICO',
              sizes=[(s, s) for s in sizes], append_images=icons[1:])
img.resize((256, 256), Image.LANCZOS).save('C:/dev/collector/icon.png')
print('아이콘 생성 완료: icon.ico, icon.png')
