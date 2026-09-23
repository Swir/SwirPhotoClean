# SWIR PhotoClean 1.0.0

## Polski

SWIR PhotoClean 1.0.0 to lokalny, review-first cleaner zdjęć dla Windows 10/11. Wydanie stabilne będzie opublikowane dopiero po zamknięciu całej bramki bezpieczeństwa 1.0 i rzeczywistym teście Windows Recycle Bin: przeniesienie wygenerowanej kopii, ręczne Przywróć, ponowna weryfikacja oraz zachowanie oryginału.

### Najważniejsze zmiany

- Dokładne duplikaty oparte na pełnym SHA-256 oraz ostrożne wykrywanie podobnych zdjęć wymagające ręcznego review.
- Difference View ogranicza duże źródła do wspólnego rozmiaru analizy przed wczytaniem drugiego obrazu, co wyraźnie zmniejsza szczytowe zużycie RAM podczas pełnoekranowego porównania dużych zdjęć bez zmiany semantyki wyniku.
- Smart Keep, Folder Health, bezpieczne Session Save / Resume i pełnoekranowe porównanie zdjęć z zoomem oraz panoramowaniem.
- Burst Cleaner i dodatkowe insighty jakościowe wspierające wybór najlepszej kopii bez automatycznego zaznaczania plików do usunięcia.
- Photo Quality Score ogranicza duże źródła przed kosztowną konwersją/orientacją, a cache jakości jest teraz osłonięty kontrolą tożsamości pliku ze skanu, więc usunięty lub podmieniony plik nie zachowuje starej rekomendacji Smart Keep/Burst.
- Profile wydajności, anulowanie skanowania, diagnostyka problemów, obsługa uszkodzonych plików, długich ścieżek i błędów dostępu.
- Polski / English, HiDPI/resize, własna ikona i spójny branding `SwirPhotoClean — by Swir`.
- Bezpieczny cleanup: rewalidacja plików, ochrona co najmniej jednej kopii w grupie oraz wyłącznie Windows Recycle Bin — bez fallbacku do trwałego usuwania.
- Portable PyInstaller onedir, packaged `SwirPhotoClean.exe --self-test`, checksumy SHA-256, provenance i publiczny post-release smoke.
- Packaged evidence workflow wiążący fizyczny test Recycle/Restore z dokładnym release safety contractem i wersją 1.0.0.
- Produkcyjny Recycle/Restore zapisuje teraz receipt tożsamości obiektu systemu plików zwrócony przez Windows Shell; jeżeli system udostępnia stabilny file index/inode, ręcznie przywrócony plik musi być tym samym obiektem, który faktycznie trafił do Kosza, więc identyczna bajtowo nowa kopia nie może podszyć się pod Restore evidence.
- Zapis `RELEASE_EVIDENCE.json` jest fail-closed: nie może nadpisać ani aliasować surowego raportu Recycle/Restore, odrzuca niebezpieczny istniejący cel i używa unikalnego stagingu z fsync, walidacją oraz atomową podmianą.
- Odczyt raportu Recycle/Restore do attestacji jest teraz fail-closed: używa jednego ograniczonego wielkością uchwytu, odrzuca symlinki/junction/reparse i hardlinki oraz wykrywa zmianę tożsamości/metadanych pliku w trakcie snapshotu.

Rozpakuj cały ZIP i uruchom `SwirPhotoClean.exe`. Nie przenoś samego EXE poza folder aplikacji.

## English

SWIR PhotoClean 1.0.0 is a local, review-first photo cleaner for Windows 10/11. The stable release will be published only after the complete 1.0 safety gate is closed with real Windows Recycle Bin evidence: move the generated copy, manually Restore it, verify it again, and prove the original was preserved.

### Highlights

- Exact duplicate detection based on full SHA-256 plus conservative similar-photo detection that always requires human review.
- Difference View bounds a large source to the shared analysis size before loading the second image, substantially reducing peak RAM during fullscreen comparison of large photos without changing result semantics.
- Smart Keep, Folder Health, safe Session Save / Resume, and fullscreen photo comparison with zoom and pan.
- Burst Cleaner and quality insights that help choose the best copy without automatically marking files for removal.
- Photo Quality Score now bounds large sources before expensive orientation/grayscale conversion, and cached quality evidence is guarded by scan-time file identity so a removed or replaced file cannot keep serving a stale Smart Keep/Burst recommendation.
- Performance profiles, scan cancellation, diagnostics, corrupt-file resilience, long-path handling, and access-error reporting.
- Polish / English UI, HiDPI/resize support, custom icon, and consistent `SwirPhotoClean — by Swir` branding.
- Safe cleanup with file revalidation, at-least-one-copy group protection, and Windows Recycle Bin only — no permanent-delete fallback.
- Portable PyInstaller onedir package, packaged `SwirPhotoClean.exe --self-test`, SHA-256 checksums, provenance, and public post-release smoke verification.
- Packaged evidence workflow binding the physical Recycle/Restore test to the exact release safety contract and 1.0.0 version identity.
- Production Recycle/Restore now records a filesystem-object identity receipt returned by Windows Shell; when the filesystem exposes a stable file index/inode, the manually restored file must be the same object that was actually moved to Recycle Bin, so a newly recreated byte-identical copy cannot impersonate Restore evidence.
- `RELEASE_EVIDENCE.json` persistence is fail-closed: it cannot overwrite or alias the raw Recycle/Restore report, rejects an unsafe existing target, and uses exclusive randomized staging with fsync, validation, and atomic replacement.
- Recycle/Restore report intake for attestation is now fail-closed: it uses one size-bounded file handle, rejects symlink/junction/reparse and hardlink inputs, and detects file identity/metadata changes during snapshotting.

Extract the entire ZIP and launch `SwirPhotoClean.exe`. Keep the executable with its accompanying files.

## Release qualification

The source version is pinned to **1.0.0** before the physical Windows evidence is collected so that the evidence is generated by the exact version intended for publication. This does not make the release publishable by itself. Stable publication remains blocked until the authoritative `STATUS.md` checklist reaches 8/8, valid packaged Windows runtime evidence is present, exact-head release checks are green, and the resulting public ZIP/checksum/provenance assets pass post-release smoke verification.
