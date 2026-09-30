from PIL import Image, ImageDraw, ImageFont
sheet = Image.open('/Users/WilliamWang/.zcode/workspace/default/ZPet/pets/mochi-pet/spritesheet.webp')
FW, FH, S = 192, 208, 1.5
ROWS = ["0 idle", "1 run-right", "2 run-left", "3 wave", "4 jump",
        "5 failed", "6 waiting", "7 running", "8 review"]
font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 22)
COLS = 3
cw, ch = int(FW * S) + 20, int(FH * S) + 50
out = Image.new('RGB', (COLS * cw + 20, 3 * ch + 20), (250, 247, 242))
d = ImageDraw.Draw(out)
for r in range(9):
    cell = sheet.crop((0, r * FH, FW, (r + 1) * FH)).resize((int(FW*S), int(FH*S)), Image.LANCZOS)
    x = 20 + (r % COLS) * cw
    y = 20 + (r // COLS) * ch
    out.paste(cell, (x, y), cell)
    d.text((x + 4, y + int(FH * S) + 8), ROWS[r], fill=(60, 60, 60), font=font)
out.save('/tmp/mochi-review.png')
print('review sheet:', out.size)
