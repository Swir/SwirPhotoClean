<div align="center">

<img src="assets/SwirPhotoClean.png" width="150" alt="SwirPhotoClean logo">

# SWIR PhotoClean

### Fast duplicate photo finder & similar image finder for Windows

Find duplicate photos, detect visually similar images, compare them side by side and safely recover disk space — **locally, without uploading your photos anywhere**.

[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)](https://github.com/Swir/SwirPhotoClean)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Local processing](https://img.shields.io/badge/Processing-100%25%20Local-success)](https://github.com/Swir/SwirPhotoClean)
[![Languages](https://img.shields.io/badge/UI-English%20%7C%20Polski-blueviolet)](https://github.com/Swir/SwirPhotoClean)
[![Release](https://img.shields.io/github/v/release/Swir/SwirPhotoClean?display_name=tag&sort=semver)](https://github.com/Swir/SwirPhotoClean/releases)

[Download for Windows](https://github.com/Swir/SwirPhotoClean/releases) · [Report a bug](https://github.com/Swir/SwirPhotoClean/issues) · [Project status](STATUS.md)

</div>

---

## Why SwirPhotoClean?

Photo libraries quickly fill up with copied downloads, exported versions, messenger duplicates, edited images and nearly identical shots. SwirPhotoClean is a **Windows duplicate photo finder**, **duplicate image finder** and **similar photo finder** designed to help you review those files safely before removing anything.

The application works locally on your PC. It does **not** require an account, subscription or cloud upload.

### Highlights

| Feature | What it does |
|---|---|
| **Exact duplicate detection** | Uses full-file **SHA-256** comparison to identify identical files. |
| **Similar image detection** | Uses image hashes, aspect ratio and low-resolution colour comparison to find visually similar photos. |
| **Side-by-side comparison** | Compare two images with dimensions, file sizes and full paths. |
| **Multiple folders** | Scan several folders and their subfolders in one session. |
| **Safe manual cleanup** | Nothing is automatically selected for deletion. You decide what goes to the Windows Recycle Bin. |
| **Protection against mistakes** | The app prevents selecting every image from the same result group. |
| **CSV export** | Export scan results for Excel or further review. |
| **Bilingual interface** | Switch between **English** and **Polski**. |
| **Local & private** | Images stay on your computer during analysis. |

---

## What can it find?

SwirPhotoClean can help detect:

- exact duplicate photos,
- copied images stored in different folders,
- renamed duplicates,
- visually similar photos,
- alternate exports of the same image,
- near-duplicate pictures with small visual differences,
- repeated downloads,
- photo collections that may be wasting disk space.

Typical searches this project is useful for include **find duplicate photos Windows 11**, **remove duplicate pictures**, **similar image finder**, **duplicate JPG finder**, **photo deduplication tool**, **offline photo cleaner** and **duplicate image remover for Windows**.

> Similarity results are suggestions for manual review. Two photos marked as similar are not automatically safe to delete.

---

## Download

Go to **[GitHub Releases](https://github.com/Swir/SwirPhotoClean/releases)** and download the latest Windows ZIP package.

1. Download the release ZIP.
2. Extract the **entire archive**.
3. Open the extracted folder.
4. Run `SwirPhotoClean.exe`.

Do not move only the EXE file out of the application folder — keep the complete extracted package together.

### System requirements

- Windows 10 or Windows 11
- 64-bit system recommended
- No account required
- No online photo upload required

---

## How to use

1. Click **Add folder** / **Dodaj folder**.
2. Add one or more folders you want to scan.
3. Enable similar-photo detection if needed.
4. Choose a similarity sensitivity level. **Standard** is a good starting point.
5. Click **Scan photos** / **Skanuj zdjęcia**.
6. Select a result group from the left panel.
7. Select up to two images with `Ctrl` to compare them side by side.
8. Review the image, size, dimensions and path carefully.
9. Mark individual files with **Mark / unmark for Recycle Bin**.
10. Click **Move selected to Recycle Bin** and confirm the list.

Files are moved to the normal Windows Recycle Bin when the operating system confirms that the operation is safe. SwirPhotoClean does not empty the Recycle Bin automatically.

---

## Exact duplicates vs similar photos

### Exact duplicates

Exact duplicate detection compares the full contents of each file using **SHA-256**. Files must match byte-for-byte to be classified as identical.

This is useful for finding:

- copied files,
- renamed copies,
- the same image stored in multiple folders.

### Similar photos

Similar-photo detection uses several lightweight visual signals, including:

- gradient / difference-based image hashes,
- aspect ratio,
- low-resolution colour comparison.

This can detect images that look alike even when their files are not identical.

Examples include resized exports, slightly edited versions and similar shots from a photo series.

Because visual similarity is subjective, **all similar-image results require human review**.

---

## Privacy & safety

SwirPhotoClean is built around a local-first workflow.

- No user account is required.
- Photos are processed locally.
- The application does not automatically choose photos for removal.
- Selected files are rechecked before the move operation.
- The app protects against marking every image in a result group.
- Files are moved to the Windows Recycle Bin instead of being permanently erased.
- The operation stops when the Recycle Bin action cannot be reliably confirmed.

For important photo libraries, keeping a backup is always recommended before large cleanup operations.

---

## Supported image formats

Supported:

- JPG / JPEG
- PNG
- WebP
- BMP
- single-image TIFF
- single-image GIF

Currently not supported:

- HEIC
- RAW camera formats
- animated images
- multi-page image files

Images above **40 megapixels** are skipped and reported.

---

## Important limitations

- Similar photos can still be completely different photos that only look alike.
- Large crops, strong colour changes or rotation without usable EXIF information may reduce similarity detection accuracy.
- Similarity groups are created around a reference image, so not every pair inside one group must be equally similar.
- Exact and similar-result groups can overlap.
- Reparse points, junctions and some cloud-placeholder files are skipped.
- A hardlink to an already-read file is not counted as another independent copy.
- Network and removable drives may be scanned, but Recycle Bin operations from them are blocked.
- Do not actively edit or synchronize scanned folders while moving files.

The **“To Recycle Bin”** size is the sum of selected file sizes. It is not guaranteed free space until the Windows Recycle Bin is emptied.

---

## Language

The application interface is available in:

- 🇬🇧 English
- 🇵🇱 Polski

Use the language selector in the top-right corner of the application.

The selected language is stored locally in:

```text
%LOCALAPPDATA%\SwirPhotoClean\settings.json
```

Changing the interface language keeps your current scan results, selected folders and marked files.

---

## Run from source

Requirements:

- Windows 10/11
- Python **3.12** from python.org
- Tcl/Tk enabled in the Python installation

```powershell
git clone https://github.com/Swir/SwirPhotoClean.git
cd SwirPhotoClean
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

---

## Tests

Run the automated test suite with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

---

## Build the Windows EXE

Install build dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

Build with PyInstaller:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name SwirPhotoClean --icon assets/SwirPhotoClean.ico --add-data "assets;assets" run.py
```

The application will be created in:

```text
dist\SwirPhotoClean\
```

Run:

```text
dist\SwirPhotoClean\SwirPhotoClean.exe
```

When copying the built application to another computer, copy the **whole `SwirPhotoClean` folder**, not only the EXE.

GitHub Actions also tests the project on Windows and builds a ZIP artifact. A CI build artifact is not automatically considered a stable release. See **[STATUS.md](STATUS.md)** for the current verification status.

---

## Search terms / discoverability

<details>
<summary>Common keywords related to SwirPhotoClean</summary>

<br>

`duplicate photo finder` · `duplicate image finder` · `duplicate photo remover` · `similar image finder` · `similar photo finder` · `photo duplicate cleaner` · `Windows duplicate photos` · `Windows 11 duplicate photo finder` · `find duplicate pictures` · `remove duplicate photos` · `find similar images` · `photo cleaner Windows` · `offline photo cleaner` · `local duplicate finder` · `image deduplication` · `photo deduplication` · `duplicate JPG finder` · `duplicate PNG finder` · `duplicate image scanner` · `photo organizer` · `disk space cleaner photos` · `Python duplicate image finder` · `SHA-256 duplicate finder` · `perceptual image hash` · `image similarity checker`

</details>

---

## Reporting bugs

Found a problem? Open an issue:

**https://github.com/Swir/SwirPhotoClean/issues**

Please include:

- SwirPhotoClean version,
- Windows version,
- steps to reproduce the issue,
- image format involved,
- relevant error message.

Only attach photos that you are allowed to share publicly.

---

## Version

Current README documentation targets **SwirPhotoClean 0.3.0**.

This is still a test-stage release. Similar-image detection should be treated as an aid for manual comparison, not as an automatic deletion decision.

---

## Autor / Author

Created by **[Swir](https://github.com/Swir)**.

More projects: **[github.com/Swir](https://github.com/Swir)**

If SwirPhotoClean is useful to you, consider leaving a ⭐ on the repository — it helps other users discover the project.
