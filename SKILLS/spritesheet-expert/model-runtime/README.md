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
Download weights separately with `prepare_item_models.py --cache-dir <cache> --profile standard` using the installed runtime Python. The shared workflow requires these checkpoints and runs offline. Qwen proposes groups or closed-taxonomy labels. SAM2 turns boxes into masks. Neither model writes an atlas. See `../references/local-model-item-workflow.md` for setup, relocation, Studio, and CLI commands.
