# Hugging Face Fashion Model Setup

This project is wired to load a bundled Core ML model named `model.mlmodelc` (or several fallback names) in `ClosetHomeView`.

## 1) Install conversion dependencies

```bash
python -m pip install -U "huggingface_hub[cli]" "exporters[coreml]" coremltools
```

## 2) Convert the Hugging Face model to Core ML

```bash
./scripts/convert_hf_fashion_model.sh
```

By default this uses:

- `Kankanaghosh/vit-fashion-mnist`

You can override:

```bash
MODEL_ID=mmabas77/fashion-mnist-mobilenetv2 ./scripts/convert_hf_fashion_model.sh
```

## 3) Add model to Xcode

1. Drag `artifacts/hf_fashion_coreml/model.mlpackage` into the `AI Closet` group.
2. Check target membership for `AI Closet`.
3. Build once; Xcode will compile it to `model.mlmodelc`.

## 4) Verify at runtime

In Xcode console, you should see:

- `USING CUSTOM CORE ML MODEL: model`

If you instead see:

- `NO CUSTOM CORE ML MODEL FOUND...`

then the model wasn't bundled correctly.
