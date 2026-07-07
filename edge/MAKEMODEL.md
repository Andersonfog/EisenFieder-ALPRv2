# Make / model recognition (optional)

This is the one vehicle field the system leaves **blank on purpose**: the make
and model of the car (e.g. "Ford F-150"). Everything else — plate, colour,
company branding, occupant count — is measured from the real image. Make/model
is off until *you* add a classifier **and prove it's accurate enough on your own
camera's view.** This page explains why, and exactly how to turn it on.

## Why it's blank by default

A make/model classifier you download is almost always trained on clean, straight-
on photos from car listings. Your entrance camera sees something very different:
a car at an angle, half-cropped, in glare or shadow. A model that scores 95% on
catalog photos can be badly wrong on real entrance crops. Guessing "Toyota Camry"
because it's *probably* right is exactly the kind of fake-looking data this
product refuses to show. So: **measure first, trust second.**

## The idea in one sentence

Run a real classifier, but only write down its answer when it's **confident
enough** — and decide "enough" by measuring how often it's actually right at each
confidence level.

## What you need

1. **A model** in ONNX format (`model.onnx`) that takes a square image and
   outputs one score per class.
2. **A labels file** (`labels.txt`): one label per line, in the same order as
   the model's output classes. Each line is a make/model, written either as
   `Ford F-150` (first word = make) or `Ford|F-150` (explicit).
3. **A small test set** of *your own* entrance-camera crops, sorted into folders
   named exactly like the labels:

   ```
   testset/
     Ford F-150/     shot1.jpg  shot2.jpg ...
     Toyota Camry/   ...
     Honda Civic/    ...
   ```

   Even 20–40 images per common vehicle is enough to get a feel for accuracy.

## Step 1 — Measure it

```bash
cd edge
python -m tools.measure_make_model --data testset --model model.onnx --labels labels.txt
```

You'll get something like:

```
Images evaluated : 120
Overall top-1    : 61.7%

Confidence gate → what you'd get if you set min_confidence there:
   min_conf   coverage   answered   accuracy
       0.00     100.0%        120      61.7%
       0.50      74.2%         89      78.7%
       0.60      55.0%         66      86.4%
       0.70      38.3%         46      93.5%
       0.90      12.5%         15      98.0%
```

How to read it:

- **coverage** = of all cars, how many the model was that sure about (and so
  would get a make/model filled in).
- **accuracy** = of those answered cars, how often it was **right**.

There's a trade-off: a higher gate = fewer cars labelled, but the labels you do
show are more trustworthy. Pick the lowest confidence you'd be comfortable
trusting. In the example above, `0.70` labels ~38% of cars and is right ~94% of
the time — a reasonable choice. Below your chosen gate, the field stays blank.

## Step 2 — Turn it on

Put the model + labels somewhere on the camera unit (e.g. `edge/models/`) and
edit `config.yaml`:

```yaml
detector:
  makemodel_backend: "onnx"
  makemodel_model_path: "models/makemodel.onnx"
  makemodel_labels_path: "models/makemodel_labels.txt"
  makemodel_min_confidence: 0.70   # the gate you chose in Step 1
  makemodel_input_size: 224        # whatever square size your model expects
```

Restart the camera. From now on, make/model appears in the console **only** when
the classifier clears your gate; otherwise it's left blank — same honest rule as
every other field.

## Common gotchas

- **Labels out of order.** The labels file order must match the model's output
  order exactly, or every prediction maps to the wrong name.
- **Wrong input size / preprocessing.** The default pipeline is standard ImageNet
  (resize-to-square, RGB, ImageNet mean/std). If your model was trained
  differently, adjust `_preprocess` in `efsurveillance/recognizer.py`.
- **Test set too clean.** Measure on *entrance-camera* crops, not catalog photos,
  or the accuracy numbers will lie to you.
- **`makemodel_backend: off` (no quotes)** parses as a boolean in YAML — keep the
  quotes: `"off"` / `"onnx"`.

## Why there's no bundled model

None of the readily available make/model models are vetted for angled entrance
crops, so shipping one would just be guessing with extra steps. The framework and
the measurement tool are here so you can drop in a model you've actually checked.
The metric math (`compute_metrics`) is unit-tested, so the numbers you read are
trustworthy even though the model is yours to provide.
