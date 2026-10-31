#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Optional, explicit pixel-art conversion of known sprite cells. Pillow only."""
from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re

from PIL import Image, __version__ as pillow_version
from runio import atomic_save_image, atomic_write_bytes, atomic_write_text
from spritecore.paths import resolve_run_path
from spritecore.tool_theme import THEME_SCRIPT, TOOL_CSS

MAX_PIXELS = 4_194_304


def read(path):
    def invalid_constant(value):
        raise ValueError(f'Nonfinite JSON number: {value}')
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError(f'{Path(path).name} must be a JSON object')
    return value


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dump(path, value):
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def size(value, label):
    if not isinstance(value, list) or len(value) != 2 or any(type(n) is not int or n < 1 for n in value):
        raise ValueError(f'{label} must be two positive integers')
    return tuple(value)


def median_cut(colors, budget):
    samples = Image.new('RGB', (len(colors), 1))
    samples.putdata(colors)
    indexed = samples.quantize(colors=budget, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    raw = indexed.getpalette()
    return sorted({tuple(raw[index*3:index*3+3]) for _, index in indexed.getcolors()})


def hue_bucket(rgb):
    """12 hue buckets for clearly saturated colors, else None."""
    high, low = max(rgb), min(rgb)
    if high < 60 or high - low < 0.35 * high:
        return None
    r, g, b = rgb
    if high == r:
        hue = ((g - b) / (high - low)) % 6
    elif high == g:
        hue = (b - r) / (high - low) + 2
    else:
        hue = (r - g) / (high - low) + 4
    return int(hue * 2) % 12


def accent_preserving_palette(colors, budget):
    """Median cut, plus reserved slots for small saturated hues it would erase.

    Median cut splits by pixel count, so a purple tongue or green eyes collapse
    into the dominant browns. Hue buckets that no palette color represents get
    up to a quarter of the budget, each as the median of the bucket's more
    saturated half, so the accent keeps its punch.
    """
    if not colors:
        return []
    palette = median_cut(colors, budget)
    if budget < 4:
        return palette
    covered = {hue_bucket(color) for color in palette}
    lost = {}
    for color in colors:
        bucket = hue_bucket(color)
        if bucket is not None and bucket not in covered:
            lost.setdefault(bucket, []).append(color)
    floor = max(4, len(colors) // 2000)
    accents = sorted(((len(group), bucket) for bucket, group in lost.items() if len(group) >= floor), reverse=True)
    accents = accents[:budget // 4]
    if not accents:
        return palette
    reserved = []
    for _count, bucket in accents:
        group = sorted(lost[bucket], key=lambda c: (max(c) - min(c), c), reverse=True)
        group = group[:max(1, len(group) // 2)]
        reserved.append(tuple(sorted(channel)[len(channel) // 2] for channel in zip(*group)))
    return sorted(set(median_cut(colors, budget - len(reserved))) | set(reserved))


def compile_conversion(request, source, *, source_bytes=None):
    if not isinstance(request, dict):
        raise ValueError('Conversion request must be a JSON object')
    allowed = {'operation', 'source', 'grid', 'cell', 'palette_size', 'semantics', 'state', 'fps', 'loop', 'pivot',
               'action', 'animation_workflows'}
    if set(request) - allowed:
        raise ValueError('Unknown request fields: ' + ', '.join(sorted(set(request) - allowed)))
    if request.get('operation') != 'convert-to-pixel-art':
        raise ValueError('Explicit operation convert-to-pixel-art is required')
    columns, rows = size(request.get('grid'), 'grid')
    width, height = size(request.get('cell'), 'cell')
    count = columns * rows
    if count > 256 or width * height * count > MAX_PIXELS:
        raise ValueError('Output exceeds 256 frames or 4194304 pixels')
    budget = request.get('palette_size')
    if type(budget) is not int or not 1 <= budget <= 256:
        raise ValueError('palette_size must be an integer from 1 through 256')
    semantics = request.get('semantics')
    if semantics not in ('animation', 'effects', 'variants', 'still-assets'):
        raise ValueError('Declare animation, effects, variants, or still-assets; tiles use the tile workflow')
    state = request.get('state')
    if not isinstance(state, str) or not re.fullmatch('[a-z][a-z0-9-]*', state):
        raise ValueError('state must be a lowercase slug')
    temporal = semantics in ('animation', 'effects')
    fps, loop = request.get('fps'), request.get('loop')
    if temporal:
        if type(fps) is not int or not 1 <= fps <= 240 or type(loop) is not bool:
            raise ValueError('Temporal input requires explicit integer fps (1..240) and boolean loop')
    elif fps is not None or loop is not None or 'animation_workflows' in request:
        raise ValueError('Static variants must not declare animation timing or workflows')
    action, workflows = request.get('action'), request.get('animation_workflows')
    if action is not None and not isinstance(action, str):
        raise ValueError('action must be a string')
    if workflows is not None and (not isinstance(workflows, list) or not all(isinstance(w, str) and w for w in workflows)):
        raise ValueError('animation_workflows must be a list of workflow ids')
    row_meta = {key: value for key, value in (('action', action), ('animation_workflows', workflows)) if value is not None}
    if source_bytes is None:
        source_bytes = Path(source).read_bytes()
    with Image.open(BytesIO(source_bytes)) as opened:
        if opened.width * opened.height > MAX_PIXELS or getattr(opened, 'n_frames', 1) != 1:
            raise ValueError('Use one still sheet of at most 4194304 pixels; extract animated containers first')
        if opened.width % columns or opened.height % rows:
            raise ValueError('Source dimensions must divide exactly into the declared grid; cropping is forbidden')
        source_image = opened.convert('RGBA')
    sw, sh = source_image.width // columns, source_image.height // rows
    if width * sh != height * sw:
        raise ValueError('One uniform scale is required; target cell aspect ratio differs from source')
    pivot = request.get('pivot')
    if pivot is None and temporal:
        raise ValueError('Temporal input requires an explicit source-cell pivot')
    if pivot is not None:
        if not isinstance(pivot, list) or len(pivot) != 2 or any(type(n) not in (int, float) or not math.isfinite(n) for n in pivot):
            raise ValueError('pivot must contain two finite source-cell coordinates')
        if not 0 <= pivot[0] <= sw or not 0 <= pivot[1] <= sh:
            raise ValueError('pivot lies outside the source cell')
    frames, visible = [], []
    for i in range(count):
        x, y = (i % columns) * sw, (i // columns) * sh
        frame = source_image.crop((x, y, x + sw, y + sh)).resize((width, height), Image.Resampling.NEAREST)
        frames.append(frame)
        visible.extend(rgb[:3] for rgb in frame.get_flattened_data() if rgb[3])
    palette = accent_preserving_palette(visible, budget)
    palette_image = Image.new('P', (1, 1))
    palette_image.putpalette([v for color in (palette or [(0, 0, 0)]) for v in color] + list((palette or [(0, 0, 0)])[0]) * (256 - max(1, len(palette))))
    converted, metrics = [], []
    for i, baseline in enumerate(frames):
        output = baseline.convert('RGB').quantize(palette=palette_image, dither=Image.Dither.NONE).convert('RGBA')
        output.putalpha(baseline.getchannel('A'))
        pixels = [tuple(c) if c[3] else (0, 0, 0, 0) for c in output.get_flattened_data()]
        output.putdata(pixels)
        converted.append(output)
        metrics.append({'index': i, 'bbox': list(output.getchannel('A').getbbox()) if output.getchannel('A').getbbox() else None,
                        'alpha_values': sorted(set(output.getchannel('A').get_flattened_data())),
                        'changed_rgb_cells': sum(a[:3] != b[:3] for a, b in zip(baseline.get_flattened_data(), pixels) if a[3])})
    scale = width / sw
    manifest = {'schema_version': 1, 'kind': 'pixel-art-conversion', 'status': 'review-required',
                'source_sha256': sha(source_bytes), 'source_file': 'source-input' + (Path(source).suffix.lower() or '.img'), 'pillow_version': pillow_version,
                'frame_semantics': semantics, 'cell': {'width': width, 'height': height},
                'game_input': 'converted.png', 'frame_layout': {'cellWidth': width, 'cellHeight': height,
                'rows': {state: [{'x': i % columns * width, 'y': i // columns * height, 'w': width, 'h': height} for i in range(count)]}},
                'animation': {'rows': {state: {'fps': fps, 'loop': loop, **row_meta}}} if temporal else {'rows': {}},
                'conversion': {'source_cell': [sw, sh], 'scale': scale, 'source_pivot': pivot,
                'output_pivot': [v * scale for v in pivot] if pivot is not None else None,
                'pivot_convention': 'continuous cell-edge coordinates; no rounding or frame recentering',
                'alpha_policy': 'nearest-sampled source alpha; no threshold or component removal',
                'palette': [list(c) for c in palette], 'palette_scope': 'whole sheet',
                'warnings': ['Reduction can lose thin features or particles through sampling. Review native playback and contact views.',
                             'This is imported conversion provenance, not provider generation or engine approval.']},
                'frames': metrics}
    return frames, converted, manifest


def sheet(frames, grid):
    w, h = frames[0].size
    output = Image.new('RGBA', (w * grid[0], h * grid[1]))
    for i, frame in enumerate(frames):
        output.paste(frame, (i % grid[0] * w, i // grid[0] * h))
    return output


def viewer(baseline, converted, manifest):
    payload = {'manifest': manifest, 'baseline': [list(im.get_flattened_data()) for im in baseline],
               'converted': [list(im.get_flattened_data()) for im in converted]}
    template = Path(__file__).resolve().parents[1] / 'assets' / 'pixel-conversion-viewer.html'
    page = template.read_text(encoding='utf-8').replace('__THEME_CSS__', TOOL_CSS).replace('__THEME_SCRIPT__', THEME_SCRIPT)
    return page.replace('__CONVERSION__', json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c'))


def validate(output):
    output = Path(output).expanduser().resolve()
    request = read(resolve_run_path(output, 'request.json'))
    name = request.get('source', '')
    if not isinstance(name, str) or not name.startswith('source-input.') or Path(name).name != name:
        raise ValueError('Invalid source snapshot path')
    baseline, frames, manifest = compile_conversion(request, resolve_run_path(output, name))
    if name != manifest['source_file']:
        raise ValueError('Source snapshot filename does not match conversion metadata')
    if read(resolve_run_path(output, 'conversion.json')) != manifest:
        raise ValueError('Conversion metadata does not match source and settings')
    expected = [('baseline.png', sheet(baseline, request['grid'])), ('converted.png', sheet(frames, request['grid']))]
    expected += [(f'frames/{i:04d}.png', image) for i, image in enumerate(frames)]
    if sorted(p.name for p in resolve_run_path(output, 'frames').iterdir()) != [f'{i:04d}.png' for i in range(len(frames))]:
        raise ValueError('Frame inventory differs from the declared grid')
    for name, image in expected:
        with Image.open(resolve_run_path(output, name)) as actual:
            if actual.size != image.size or actual.convert('RGBA').tobytes() != image.tobytes():
                raise ValueError('Pixel mismatch: ' + name)
    if resolve_run_path(output, 'index.html').read_text(encoding='utf-8') != viewer(baseline, frames, manifest):
        raise ValueError('Preview does not match conversion')
    return {'valid': True, 'frames': len(frames), 'status': 'review-required'}


def convert(request_path, output):
    request_path, output = Path(request_path), Path(output)
    request = read(request_path)
    if not isinstance(request.get('source'), str) or not request['source'].strip():
        raise ValueError('source must be a non-empty local path string')
    source = (request_path.parent / request['source']).resolve()
    source_bytes = source.read_bytes()
    baseline, frames, manifest = compile_conversion(request, source, source_bytes=source_bytes)
    # Exclusive creation keeps prior sources, outputs and approvals intact.
    output.mkdir(parents=True, exist_ok=False)
    source_name = manifest['source_file']
    atomic_write_bytes(output / source_name, source_bytes)
    request = {**request, 'source': source_name}
    dump(output / 'request.json', request)
    dump(output / 'conversion.json', manifest)
    atomic_save_image(sheet(baseline, request['grid']), output / 'baseline.png')
    atomic_save_image(sheet(frames, request['grid']), output / 'converted.png')
    (output / 'frames').mkdir()
    for i, frame in enumerate(frames):
        atomic_save_image(frame, output / 'frames' / f'{i:04d}.png')
    atomic_write_text(output / 'index.html', viewer(baseline, frames, manifest))
    return validate(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest='command', required=True)
    c = cmds.add_parser('convert')
    c.add_argument('--request', type=Path, required=True)
    c.add_argument('--output', type=Path, required=True)
    v = cmds.add_parser('validate')
    v.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        result = convert(args.request, args.output) if args.command == 'convert' else validate(args.output)
        print(json.dumps(result))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f'Pixel conversion: {exc}\n')


if __name__ == '__main__':
    main()
