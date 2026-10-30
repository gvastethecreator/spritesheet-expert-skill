from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

import convert_pixel_art as converter
from convert_pixel_art import accent_preserving_palette, convert, validate

SCRIPTS = Path(__file__).resolve().parents[2] / 'SKILLS/spritesheet-expert/scripts'


def fixture(tmp_path, *, temporal=True):
    image = Image.new('RGBA', (16, 8), (90, 240, 20, 0))
    # Movement belongs to the source; tiny detached pixels and partial alpha are intentional.
    for i, dy in enumerate((0, -2)):
        for x in range(2, 5):
            for y in range(3 + dy, 7 + dy):
                image.putpixel((i*8+x, y), (200, 30, 60, 128))
        image.putpixel((i*8+6, 2 + dy), (20, 70, 190, 255))
    image.save(tmp_path / 'source.png')
    request = {'operation': 'convert-to-pixel-art', 'source': 'source.png', 'grid': [2, 1],
               'cell': [8, 8], 'palette_size': 2, 'semantics': 'animation' if temporal else 'variants', 'state': 'jump'}
    if temporal:
        request.update(fps=9, loop=False, pivot=[4, 7], action='responsive jump', animation_workflows=['responsive-jump'])
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request))
    return path, request, image


def test_conversion_preserves_motion_alpha_timing_and_existing_import(tmp_path):
    path, request, source = fixture(tmp_path)
    output = tmp_path / 'converted'
    before = hashlib.sha256((tmp_path / 'source.png').read_bytes()).hexdigest()
    assert convert(path, output) == {'valid': True, 'frames': 2, 'status': 'review-required'}
    for i in range(2):
        actual = Image.open(output / 'frames' / f'{i:04d}.png').convert('RGBA')
        expected = source.crop((i*8, 0, (i+1)*8, 8))
        assert actual.getchannel('A').tobytes() == expected.getchannel('A').tobytes()
        assert actual.getpixel((6, 2-2*i)) == (20, 70, 190, 255)
    manifest = json.loads((output / 'conversion.json').read_text())
    assert manifest['conversion']['output_pivot'] == [4, 7]
    assert len(manifest['conversion']['palette']) == 2
    assert manifest['animation']['rows']['jump'] == {
        'fps': 9, 'loop': False, 'action': 'responsive jump', 'animation_workflows': ['responsive-jump']}
    result = subprocess.run([sys.executable, str(SCRIPTS / 'unpack_atlas_run.py'),
        '--manifest', str(output / 'conversion.json'), '--out-dir', str(tmp_path / 'run'),
        '--frame-semantics', 'animation', '--background-removal', 'none', '--extraction-mode', 'components'],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    imported = json.loads((tmp_path / 'run/sprite-request.json').read_text())
    assert imported['states']['jump']['fps'] == 9
    assert imported['states']['jump']['loop'] is False
    assert imported['states']['jump']['action'] == 'responsive jump'
    assert imported['states']['jump']['animation_workflows'] == ['responsive-jump']
    images = sorted((tmp_path / 'run/frames/jump').glob('*.png'))
    assert len(images) == 2
    assert Image.open(images[1]).convert('RGBA').tobytes() == Image.open(output / 'frames/0001.png').convert('RGBA').tobytes()
    assert hashlib.sha256((tmp_path / 'source.png').read_bytes()).hexdigest() == before


@pytest.mark.parametrize('change', [
    {'operation': 'pack'}, {'grid': [3, 1]}, {'cell': [8, 7]}, {'fps': None}, {'pivot': None},
])
def test_conversion_rejects_implicit_or_ambiguous_transform(tmp_path, change):
    path, request, _ = fixture(tmp_path)
    request.update(change)
    path.write_text(json.dumps(request))
    with pytest.raises(ValueError):
        convert(path, tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_conversion_common_scale_empty_slot_and_repeat(tmp_path):
    path, request, source = fixture(tmp_path, temporal=False)
    source.paste((0, 0, 0, 0), (8, 0, 16, 8))
    source.save(tmp_path / 'source.png')
    request.update(cell=[4, 4], pivot=[4, 7])
    path.write_text(json.dumps(request))
    convert(path, tmp_path / 'a')
    convert(path, tmp_path / 'b')
    assert (tmp_path / 'a/converted.png').read_bytes() == (tmp_path / 'b/converted.png').read_bytes()
    manifest = json.loads((tmp_path / 'a/conversion.json').read_text())
    assert manifest['conversion']['output_pivot'] == [2, 3.5]
    assert manifest['frames'][1]['bbox'] is None
    assert manifest['animation']['rows'] == {}
    expected = source.crop((0, 0, 8, 8)).resize((4, 4), Image.Resampling.NEAREST)
    assert Image.open(tmp_path / 'a/frames/0000.png').getchannel('A').tobytes() == expected.getchannel('A').tobytes()


def test_conversion_rejects_output_reuse_and_pixel_drift(tmp_path):
    path, _, _ = fixture(tmp_path)
    out = tmp_path / 'out'
    convert(path, out)
    with pytest.raises(FileExistsError):
        convert(path, out)
    image = Image.open(out / 'frames/0000.png').convert('RGBA')
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.save(out / 'frames/0000.png')
    with pytest.raises(ValueError, match='Pixel mismatch'):
        validate(out)
    copied_request = out / 'request.json'
    invalid = json.loads(copied_request.read_text())
    invalid['source'] = 123
    copied_request.write_text(json.dumps(invalid))
    with pytest.raises(ValueError, match='Invalid source snapshot path'):
        validate(out)
    copied_request.write_text('[]')
    with pytest.raises(ValueError, match='must be a JSON object'):
        validate(out)


def test_conversion_uses_one_source_snapshot_when_the_live_file_changes(tmp_path, monkeypatch):
    path, _, _ = fixture(tmp_path)
    source = tmp_path / 'source.png'
    original = source.read_bytes()
    compile_original = converter.compile_conversion

    def change_after_decode(request, source_path, **kwargs):
        result = compile_original(request, source_path, **kwargs)
        if Path(source_path) == source:
            Image.new('RGBA', (16, 8), (10, 20, 30, 255)).save(source)
        return result

    monkeypatch.setattr(converter, 'compile_conversion', change_after_decode)
    output = tmp_path / 'converted'
    assert convert(path, output) == {'valid': True, 'frames': 2, 'status': 'review-required'}
    assert source.read_bytes() != original
    assert (output / 'source-input.png').read_bytes() == original
    manifest = json.loads((output / 'conversion.json').read_text())
    assert manifest['source_sha256'] == hashlib.sha256(original).hexdigest()
    assert validate(output)['valid'] is True


def test_palette_keeps_a_small_saturated_accent_that_median_cut_drops():
    browns = [(90 + i % 40, 50 + i % 25, 30 + i % 10) for i in range(4000)]
    purple_tongue = [(110, 30, 150)] * 40

    palette = accent_preserving_palette(browns + purple_tongue, 8)

    assert len(palette) <= 8
    assert (110, 30, 150) in palette
