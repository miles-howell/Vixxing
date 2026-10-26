"""Hero composition for the README: key out a magenta background and composite the handset into the hero layout.

usage: compose_hero.py <subject.webp> <base.png> <cutout_out.png> <hero_out.png> <fit_box> <fade>
  fit_box: x0,y0,x1,y1 in 1200-unit hero coordinates (subject bbox is fitted inside)
  fade:    fraction of the cutout's height, from the bottom, faded to transparent

Published hero was built with (requires Pillow + numpy; base = hero-layout.svg
without the <g id="subject"> placeholder, rendered at 2400px wide):
  compose_hero.py generated.webp base.png hero-subject.png ../hero.png 740,16,1170,278 0.22
"""
import sys
from PIL import Image, ImageFilter
import numpy as np

src, base_path, cut_out, hero_out, box, fade = sys.argv[1:7]
x0, y0, x1, y1 = map(float, box.split(','))
fade = float(fade)

rgb = np.asarray(Image.open(src).convert('RGB')).astype(np.float32)
r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]

# Key colour = median of the border pixels.
border = np.concatenate([rgb[:4].reshape(-1, 3), rgb[-4:].reshape(-1, 3),
                         rgb[:, :4].reshape(-1, 3), rgb[:, -4:].reshape(-1, 3)])
key = np.median(border, axis=0)
key_m = min(key[0], key[2]) - key[1]

# Magenta-ness relative to the key: 1 = background, 0 = subject.
m = (np.minimum(r, b) - g) / key_m
alpha = 1 - np.clip((m - 0.25) / (0.75 - 0.25), 0, 1)

# Despill: the subject is neutral charcoal plus a green rim, so red/blue never
# need to exceed green by much; clamping them removes magenta bleed on edges.
limit = g
out = rgb.copy()
out[..., 0] = np.minimum(r, limit + 6)
out[..., 2] = np.minimum(b, limit + 6)

a_img = Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
cut = Image.fromarray(out.astype(np.uint8)).convert('RGBA')
cut.putalpha(a_img)
cut = cut.crop(cut.getchannel('A').point(lambda v: 255 if v > 8 else 0).getbbox())

if fade > 0:
    w, h = cut.size
    ramp = np.ones(h, dtype=np.float32)
    n = int(h * fade)
    ramp[h - n:] = np.linspace(1, 0, n) ** 1.4
    a = np.asarray(cut.getchannel('A')).astype(np.float32) * ramp[:, None]
    cut.putalpha(Image.fromarray(a.astype(np.uint8)))
cut.save(cut_out, optimize=True)

base = Image.open(base_path).convert('RGBA')
s = base.size[0] / 1200
bw, bh = (x1 - x0) * s, (y1 - y0) * s
scale = min(bw / cut.size[0], bh / cut.size[1])
sub = cut.resize((round(cut.size[0] * scale), round(cut.size[1] * scale)), Image.Resampling.LANCZOS)
px = round(x0 * s + (bw - sub.size[0]) / 2)
py = round(y0 * s + (bh - sub.size[1]) / 2)
base.alpha_composite(sub, (px, py))
base.save(hero_out, optimize=True)
print(cut_out, cut.size, '->', sub.size, 'at', (px, py), 'key', key.round())
