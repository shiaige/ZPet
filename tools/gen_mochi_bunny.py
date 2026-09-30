#!/usr/bin/env python3
"""Reproducible 4x antialiased, layered quiet-rabbit Codex atlas."""
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'pets/mochi-pet'
S = 4
FW, FH = 192, 208
COUNT = [8, 6, 6, 6, 6, 6, 6, 6, 6]
INK = '#B89F91'
CREAM = '#FFF9F0'
SHADE = '#F3E6D9'
PINK = '#F5D4CB'
EYE = '#644E45'


def path(draw, start, curves, fill=None, stroke=INK, width=1.65):
    points = [start]
    p = start
    for a, b, c in curves:
        for i in range(1, 25):
            t = i / 24
            u = 1 - t
            points.append((u**3*p[0]+3*u*u*t*a[0]+3*u*t*t*b[0]+t**3*c[0],
                           u**3*p[1]+3*u*u*t*a[1]+3*u*t*t*b[1]+t**3*c[1]))
        p = c
    points = [(round(x*S), round(y*S)) for x, y in points]
    if fill:
        draw.polygon(points, fill=fill)
    if stroke:
        draw.line(points, fill=stroke, width=round(width*S), joint='curve')


def ellipse(d, box, fill, outline=None, width=1.65):
    d.ellipse(tuple(round(v*S) for v in box), fill=fill, outline=outline,
              width=round(width*S))


def frame(row, index):
    phase = 2 * math.pi * index / COUNT[row]
    wave = math.sin(phase)
    im = Image.new('RGBA', (FW*S, FH*S))
    d = ImageDraw.Draw(im)
    ellipse(d, (60, 188, 135, 194), (121, 103, 95, 22))
    pet = Image.new('RGBA', im.size)
    d = ImageDraw.Draw(pet)
    # All poses share a planted seat, with arms occluded by the head.
    ellipse(d, (123, 157, 148, 181), CREAM, INK)
    path(d, (78, 129), [((64, 140),(57, 166),(62, 181)),
         ((68, 195),(123, 196),(131, 180)), ((139, 165),(124, 139),(116, 129)),
         ((104, 124),(87, 124),(78, 129))], SHADE)
    ellipse(d, (75, 143, 119, 187), CREAM)
    for j, x in enumerate((62, 106)):
        if row in (1, 2):
            x += 14 if j else -8
            step = 3*wave*(-1 if j else 1)
            y = 170 if j else 179
            ellipse(d, (x+step,y,x+27+step,y+12), CREAM, INK)
        else:
            ellipse(d, (x,175,x+28,192), CREAM, INK)
    head = Image.new('RGBA', im.size)
    d = ImageDraw.Draw(head)
    # Ear outlines disappear behind the head, so no detached roots are visible.
    droop = 0
    path(d, (69, 88), [((55, 69),(54, 24+droop),(65, 20+droop)),
         ((81, 14+droop),(87, 60),(86, 85)), ((81, 91),(74, 92),(69, 88))], CREAM)
    path(d, (71, 74), [((65, 57),(64, 34),(68, 32)),
         ((75, 29),(80, 57),(79, 76)), ((77, 82),(74, 81),(71, 74))], PINK, None)
    path(d, (106, 84), [((105, 66),(112, 32+droop),(125, 36+droop)),
         ((138, 39),(145, 62),(136, 67)), ((131, 69),(126, 63),(123, 58)),
         ((124, 72),(122, 82),(120, 88)), ((115, 92),(110, 90),(106, 84))], CREAM)
    path(d, (112, 78), [((112, 65),(118, 48),(122, 46)),
         ((121, 56),(124, 61),(128, 63)), ((123, 76),(122, 79),(118, 82)),
         ((116, 83),(114, 81),(112, 78))], PINK, None)
    path(d, (122, 46), [((123, 56),(128, 64),(136, 67))], None, INK, 1.3)
    if row == 5:
        ears = head.crop((0,0,FW*S,96*S)).resize((FW*S,73*S), Image.Resampling.LANCZOS)
        head = Image.new('RGBA', im.size)
        head.alpha_composite(ears, (0,23*S))
        d = ImageDraw.Draw(head)
    # Head is a cheek-shaped silhouette, not an ellipse or a second body.
    path(d, (96, 76), [((67, 74),(50, 91),(49, 111)),
         ((40, 126),(44, 140),(60, 146)), ((76, 153),(117, 153),(133, 145)),
         ((149, 139),(152, 126),(143, 111)), ((140, 89),(123, 75),(96, 76))], CREAM)
    for x in (63, 128):
        ellipse(d, (x-8, 126, x+8, 134), '#FAE1D7')
    glance = (2*wave if row == 8 else (8 if row in (1, 2) else 0))
    closed = (row == 0 and index == 6) or row == 5
    happy = row in (3, 4)
    for x in ((88, 122) if row in (1, 2) else (76, 116)):
        x += glance
        if closed:
            path(d, (x-3.5, 120), [((x-1.5,122),(x+1.5,122),(x+3.5,120))], None, EYE, 1.8)
        elif happy:
            path(d, (x-3.5, 122), [((x-2,117),(x+2,117),(x+3.5,122))], None, EYE, 1.8)
        else:
            ellipse(d, (x-3.6, 116.7, x+3.6, 125.3), EYE)
            ellipse(d, (x-1.8, 117.8, x+0.2, 119.8), '#FFFDF8')
            if row == 5:
                path(d, (x-4, 113.5), [((x-1,114),(x+1,112.3),(x+3,112))], None, INK, 1.1)
    face_layer = Image.new('RGBA', im.size)
    d = ImageDraw.Draw(face_layer)
    path(d, (93, 125), [((94,123.7),(98,123.7),(99,125)),
         ((99,126.5),(97,128),(96,128)), ((95,128),(93,126.5),(93,125))], '#E9B8AB', None)
    if row == 5:
        path(d, (92, 133), [((94,130),(98,130),(100,133))], None, '#A18477', 1.35)
    elif row == 6:
        ellipse(d, (94,130,98,135), '#A18477')
    else:
        path(d, (96, 128), [((96,133),(91,133),(90,130))], None, '#A18477', 1.35)
        path(d, (96, 128), [((96,133),(101,133),(102,130))], None, '#A18477', 1.35)
    head.alpha_composite(face_layer, (16*S if row in (1,2) else 0,0))
    d = ImageDraw.Draw(head)
    if row == 8:
        for x in (76, 116):
            ellipse(d, (x-11,110,x+11,131), None, '#96877C', 1.35)
        path(d, (87,118), [((91,115),(101,115),(105,118))], None, '#96877C', 1.3)
    if row == 7:
        for x in (76, 116):
            path(d, (x-5,113), [((x-2,112),(x+2,114),(x+5,115))], None, INK, 1.3)
    angle = {1: -7, 2: -7, 5: 5, 6: 9, 7: -3, 8: -5}.get(row, 0)
    head = head.rotate(angle, resample=Image.Resampling.BICUBIC, center=(96*S,145*S))
    if row == 5:
        head = head.resize((FW*S, round(FH*S*0.94)), Image.Resampling.LANCZOS)
    pet.alpha_composite(head, (0, (16 if row == 5 else 2 if row == 7 else 0)*S))
    d = ImageDraw.Draw(pet)

    def arm(points):
        path(d, points[0], points[1:], CREAM, INK, 1.5)

    if row in (3, 4):
        raised = Image.new('RGBA', im.size)
        rd = ImageDraw.Draw(raised)
        a = 2.8*wave
        path(rd, (124,163), [((139,161),(153,140+a),(156,131+a)),
             ((158,123+a),(149,121+a),(146,129+a)),
             ((140,144),(132,150),(123,153))], CREAM, INK, 1.5)
        pet.alpha_composite(raised)
        if row == 4:
            pet.alpha_composite(raised.transpose(Image.Transpose.FLIP_LEFT_RIGHT))
        else:
            arm([(76,152), ((70,159),(76,173),(83,171)), ((89,169),(83,158),(81,155))])
    elif row == 5:
        arm([(75,155), ((72,166),(85,176),(95,170)), ((99,163),(87,162),(82,158))])
        arm([(117,155), ((120,166),(107,176),(97,170)), ((93,163),(105,162),(110,158))])
    elif row == 6:
        arm([(75,156), ((62,158),(60,150),(61,143)), ((62,135),(72,137),(71,144)), ((70,150),(77,151),(81,153))])
        arm([(116,153), ((124,166),(113,176),(106,170)), ((102,165),(111,160),(111,156))])
    elif row == 8:
        arm([(115,161), ((103,166),(92,151),(93,142)), ((94,136),(104,137),(103,143)), ((102,151),(113,153),(120,155))])
        arm([(76,154), ((71,163),(78,172),(88,170)), ((96,169),(102,166),(108,166)), ((111,160),(98,158),(84,162))])
    elif row == 7:
        path(d, (69,170), [((83,166),(114,166),(128,170)), ((130,172),(130,180),(127,181)), ((112,185),(79,185),(67,181)), ((65,178),(66,172),(69,170))], '#D4DDD7', '#82968A', 1.5)
        for x in range(75,125,9):
            path(d, (x,176), [((x+1,175),(x+3,175),(x+4,176))], None, '#AAAB9B', 1)
        for j,x in enumerate((79,111)):
            y = 3*wave*(-1 if j else 1)
            arm([(x-5,153), ((x-12,161),(x-9,173+y),(x,174+y)), ((x+9,173+y),(x+7,162),(x+3,155))])
    elif row in (1, 2):
        arm([(77,153), ((69,157),(58,169+3*wave),(66,172+3*wave)), ((74,175),(80,163),(83,156))])
        arm([(116,151), ((124,148),(134,154-3*wave),(132,160-3*wave)), ((129,167),(118,164),(113,158))])
    else:
        arm([(76,152), ((70,159),(76,173),(83,171)), ((89,169),(83,158),(81,155))])
        arm([(116,152), ((122,159),(116,173),(109,171)), ((103,169),(109,158),(111,155))])
    if row in (1,2):
        pet = pet.rotate(-6, resample=Image.Resampling.BICUBIC, center=(96*S,182*S))
    if row == 2:
        pet = pet.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    dy = -6-4*math.cos(phase) if row == 4 else -2*(1-math.cos(phase)) if row in (1,2) else 0
    dx = 1.5*wave if row in (1, 2, 6) else 0
    breath = 1 + (0.015 if row == 0 else 0.004)*wave
    new_h = round(FH*S*breath)
    pet = pet.resize((FW*S, new_h), Image.Resampling.LANCZOS)
    im.alpha_composite(pet, (round(dx*S), round((192-192*breath+dy)*S)))
    return im.resize((FW, FH), Image.Resampling.LANCZOS)


def main():
    sheet = Image.new('RGBA', (max(COUNT)*FW, 9*FH))
    for r, count in enumerate(COUNT):
        for i in range(count):
            sheet.alpha_composite(frame(r, i), (i*FW, r*FH))
    sheet.save(OUT/'spritesheet.webp', 'WEBP', lossless=True, exact=True)
    meta = json.loads((OUT/'pet.json').read_text())
    meta.update(description='奶白小兔绵绵：九种独立姿势，侧向轻移、单爪招手、双爪庆祝、委屈收爪、歪头等待、键盘工作与眼镜审查；温和微动画。',
                columns=max(COUNT), frames=COUNT)
    (OUT/'pet.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2)+'\n')
    preview = Image.new('RGB', (FW*8, FH+36), '#F0EBE5')
    for i in range(8):
        f = frame(0, i)
        preview.paste(f, (i*FW, 28), f)
        ImageDraw.Draw(preview).text((i*FW+12, 10), f'IDLE {i+1:02}', fill=EYE)
    preview.save(OUT/'idle-preview.png')
    backgrounds = []
    for i in range(8):
        bg = Image.new('RGB', (FW*2, FH*2), '#E8E1D9')
        f = frame(0, i).resize(bg.size, Image.Resampling.LANCZOS)
        bg.paste(f, (0, 0), f)
        backgrounds.append(bg)
    backgrounds[0].save(OUT/'idle-preview.gif', save_all=True,
                        append_images=backgrounds[1:], duration=140, loop=0)
    names = ['IDLE', 'RIGHT', 'LEFT', 'WAVE', 'JUMP', 'FAILED', 'WAITING', 'WORKING', 'REVIEW']
    animated = []
    for tick in range(24):
        canvas = Image.new('RGB', (FW*3, (FH+28)*3), '#F0EBE5')
        cd = ImageDraw.Draw(canvas)
        for r, name in enumerate(names):
            x, y = (r % 3)*FW, (r // 3)*(FH+28)
            f = frame(r, tick % COUNT[r])
            canvas.paste(f, (x,y), f)
            cd.text((x+12,y+FH+5), name, fill=EYE)
        animated.append(canvas)
    animated[0].save(OUT/'states-preview.gif', save_all=True, append_images=animated[1:], duration=150, loop=0)
    print('Generated', sheet.size, COUNT)


if __name__ == '__main__':
    main()
