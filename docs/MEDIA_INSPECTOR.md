# Media Type Inspector

`View -> Media types...` (`Ctrl+Alt+M`) is a local, read-only review aid for a completed SWIR PhotoClean scan.

## What it does

The inspector groups scanned files into four deliberately conservative buckets:

- **Camera photos** — the file contains EXIF `Make` or `Model` camera/device metadata.
- **Screenshot candidates** — no camera metadata is present and the image has an exact common screen resolution. PNG/WebP candidates are medium confidence; other formats stay low confidence.
- **Graphics** — no camera metadata is present and a graphics-friendly format exposes strong structural evidence such as an alpha channel or palette mode.
- **Unknown** — there is not enough reliable evidence to classify the image.

Every row shows the dimensions, source format, confidence level and the signals that produced the result.

## Safety rules

- The feature never changes files, EXIF or scan groups.
- It never marks anything for the Recycle Bin.
- It never turns a classification into a cleanup decision.
- Existing Safe Mode and Recycle Bin validation remain unchanged.
- Analysis runs in a cancellable worker thread and only posts UI updates back to Tk.
- Unavailable files are reported as unknown/unavailable rather than guessed.

## Why "candidate" matters

A screen-sized image is not automatically a screenshot. Photos can be resized to phone or desktop resolutions, and some screenshot tools can save JPEG files. Camera EXIF therefore takes precedence, and screen-size evidence is intentionally not presented as certainty.

The inspector also does **not** claim to detect memes. Reliable meme detection would normally need text/content analysis and would create more false positives than this pre-1.0 safety-focused tool should accept. Such files remain graphics or unknown unless a stronger local signal exists.

## Current evidence

Screenshot candidate evidence:

1. no EXIF camera `Make`/`Model`;
2. exact match to a curated common desktop/mobile screen pixel size;
3. PNG/WebP raises confidence from low to medium.

Graphic evidence:

1. no EXIF camera `Make`/`Model`;
2. PNG/WebP/GIF/BMP source;
3. alpha channel or palette mode.

Camera-photo evidence:

1. EXIF `Make` and/or `Model`;
2. `DateTimeOriginal`, when present, is shown as an additional supporting signal.

## Limitations

This is an explainable organization/review helper, not a computer-vision truth engine. Cropped screenshots, screenshots at unusual resolutions, exported photos without EXIF and flattened graphics may remain `Unknown`. That is intentional: before 1.0, SWIR PhotoClean prefers missing classification over unsafe confidence.
