# Neutral background and Grok video pipeline research

Verified: 2026-07-30

## Question

Which background-removal and video-decoding/provider contracts can support neutral-background sprite generation and first-frame-to-video animation without weakening licensing, portability, or provenance?

## Answer

Use flat gray, white, or black for new generation. Preserve source alpha, remove simple flat neutral edges with a connected matte, and use rembg with `birefnet-general` when the background is ambiguous. Keep `birefnet-general-lite` as a speed option and the open BEN2 base as an explicit comparison path. Do not default to BRIA RMBG 2.0 because its public model is non-commercial.

Use `$grok-imagine` as an optional provider boundary. Image-to-video accepts a starting image; omit an aspect override so the input ratio is retained. Copy accepted media immediately because xAI URLs are temporary. Require the runner's completed invocation manifest before classifying a video as Grok-generated.

Decode accepted videos through an optional `imageio-ffmpeg` extra. Its common-platform wheels include FFmpeg and its streaming reader yields RGB frames plus codec, size, fps, and duration metadata. Keep core sprite preparation usable when this extra is absent.

## Sources and findings

- [rembg model list](https://github.com/danielgatis/rembg#models): includes `birefnet-general`, `birefnet-general-lite`, portrait/DIS/HRSOD/COD variants, and `isnet-anime`; models download on first use.
- [BiRefNet repository](https://github.com/ZhengPeng7/BiRefNet) and [license](https://github.com/ZhengPeng7/BiRefNet/blob/main/LICENSE): high-resolution dichotomous segmentation/matting variants; source is MIT licensed.
- [BEN2 repository](https://github.com/PramaLLC/BEN2): the public base uses `AutoModel.from_pretrained`, targets confidence-guided matting/edge refinement, and is MIT licensed; the repository separately advertises commercial access to its full model.
- [BRIA RMBG 2.0 repository](https://github.com/Bria-AI/RMBG-2.0): public model is CC BY-NC 4.0 and requires a commercial agreement for commercial use, so it is excluded as the default.
- [xAI video generation](https://docs.x.ai/developers/model-capabilities/video/generation): image-to-video is `prompt + image`; generation is asynchronous; URLs are temporary; duration is 1-15 seconds; the input aspect ratio is used by default and an explicit override stretches it.
- [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html): `fps` and `select` provide deterministic temporal sampling primitives.
- [imageio-ffmpeg repository](https://github.com/imageio/imageio-ffmpeg): BSD-2-Clause wrapper; common-platform wheels include FFmpeg; `read_frames()` yields metadata followed by RGB byte frames; `get_ffmpeg_exe()` resolves an override, bundled, conda, or system executable.
- Local provider inspection: `grok 0.2.114` stable, default model `grok-4.5`, installed but unauthenticated on 2026-07-30. The local `$grok-imagine` runner defaults to dry-run and requires `--ack-run` for inference.
- Local decoder inspection: `ffmpeg`, `ffprobe`, `imageio_ffmpeg`, PyAV, OpenCV, and ImageIO were unavailable on PATH/current Python on 2026-07-30.

Later implementation verification installed the pinned `imageio-ffmpeg==0.6.0` extra in an isolated test environment. Its bundled FFmpeg decoded a real MP4 through the new two-pass ingestion path; the core environment remains free of the video dependency.

Representative matte verification also installed the pinned
`rembg[cpu]==2.0.78` background extra in an isolated environment and downloaded
the `birefnet-general` ONNX model. The provider-backed green mascot tests used
that runtime successfully on gray, black, and white inputs; the model remains
optional and is not installed into the core environment.

## Implementation impact

- Replace generated chroma-key language and fallback colors with a `generation_background` neutral contract.
- Make `birefnet-general` the quality model recorded by default; auto may still choose conservative neutral matte for perfectly flat sources.
- Expand matte proof to checker, black, gray, white, and alpha mask.
- Add an optional video extra and fail clearly when no decoder exists.
- Keep Grok execution outside the atlas engine; ingest only completed, counted, copied, hash-bound media.

## Uncertainty

Code and fake-backend tests cannot prove Grok motion quality. Representative
BiRefNet matte inspection has now been completed for the provider-backed green
mascot matrix. An explicitly acknowledged, authenticated Grok run remains a
separate visual gate.
