# Local model runtime

This isolated Python 3.12 environment is optional. The deterministic alpha,
packing, review, and QA commands do not depend on it.

Install dependencies without downloading model weights:

```powershell
python ..\scripts\setup_item_model_runtime.py --profile nvidia
```

The installer keeps the virtual environment, the `uv` cache, and Hugging Face
checkpoints under `SKILLS/spritesheet-expert/.local/` by default. Those files
are not published or committed. Pass explicit absolute directories when the
skill installation is read-only.

Run the doctor after setup:

```powershell
python ..\scripts\check_item_model_runtime.py
```

Use `--profile cpu` on CPU hosts. Both profiles are pinned in `uv.lock`.

Add `--capability lucida` and/or `--capability ben2` during setup for background
removal. All selected extras share the same lock. BEN2's implementation is pinned
to commit `2c99a5da477b5523585bfa5c893888a6e818a8f6` of the
[official repository](https://github.com/PramaLLC/BEN2).
Lucida uses reviewed custom Transformers code at its fixed checkpoint revision.
Do not install a floating Git branch or use BEN2's remote AutoModel dispatcher.

Read `python`, `modelCacheDir` and `capabilities` from the generated configuration.
With that Python, run `prepare_item_models.py --cache-dir <cache> --profile lucida`
or `--profile ben2`. Preparation records an immutable checkpoint receipt. Repeat
with `--offline` to check local availability without contacting Hugging Face.
Inference loads the recorded snapshot with `local_files_only=True`. Set
`SPRITE_MODEL_CACHE=<cache>` when using a non-default cache outside Studio.

After relocating the skill, rerun setup with explicit runtime, model-cache and
uv-cache directories. A virtual environment is rebuilt, not copied as a portable
binary. Setup `--offline` requires the Python distribution and dependency wheels
already available in the uv cache; available model weights alone are not enough.
Workspaces contain source/results, never these host-specific environment paths.
The doctor verifies imports and CUDA. A prepared capability is not an inference
or visual-quality certificate; record measured model runs separately.
Download weights separately with `prepare_item_models.py --cache-dir <cache> --profile standard` using the installed runtime Python. The shared workflow requires these checkpoints and runs offline. Qwen proposes groups or closed-taxonomy labels. SAM2 turns boxes into masks. Neither model writes an atlas. See `../references/local-model-item-workflow.md` for setup, relocation, Studio, and CLI commands.
