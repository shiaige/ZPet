#!/usr/bin/env python3
"""Check the delivered atlas and load it through the existing Qt loader."""
import json
import os
import sys
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
folder = Path(sys.argv[1]) if len(sys.argv) > 1 else root/'pets/mochi-pet'
meta = json.loads((folder/'pet.json').read_text())
im = Image.open(folder/'spritesheet.webp')
assert im.mode == 'RGBA', im.mode
assert meta['cell'] == {'width': 192, 'height': 208}
assert im.size == (meta['columns']*192, 9*208)
assert 1 <= meta['columns'] <= 8
assert len(meta['frames']) == 9
for row, count in enumerate(meta['frames']):
    assert 1 <= count <= meta['columns']
    for col in range(meta['columns']):
        alpha = im.crop((col*192, row*208, (col+1)*192, (row+1)*208)).getchannel('A')
        bounds = alpha.getbbox()
        assert bool(bounds) == (col < count), (row, col, bounds)
        if bounds:
            assert bounds[0] > 0 and bounds[1] > 0 and bounds[2] < 192 and bounds[3] < 208
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['ZPET_PORT'] = '57996'
sys.path.insert(0, str(root/'daemon'))
from PySide6 import QtWidgets
app = QtWidgets.QApplication([])
import zpet
info = next(p for p in zpet.discover_pets() if p['name'] == 'mochi-pet')
rows = {r: len(f) for r, f in zpet.load_frames(info).items()}
print('Atlas verified:', folder, im.size, meta['frames'])
print('Daemon discovered pet:', info)
print('Daemon loaded rows:', rows)
