"""Application text and per-user language preference (no image data stored)."""
import json
import os
import tempfile
from pathlib import Path

language = "pl"
EN = {
    "Mniej kopii. Więcej miejsca na wspomnienia.": "Fewer copies. More room for memories.",
    "100% lokalnie": "100% local",
    "+ Dodaj folder": "+ Add folder",
    "Usuń z listy": "Remove folder",
    "Szukaj też podobnych": "Include similar photos",
    "Standardowy": "Standard", "Ścisły": "Strict", "Szeroki": "Broad",
    "Skanuj zdjęcia": "Scan photos",
    "Dodaj foldery ze zdjęciami. Skanowanie niczego nie usuwa.": "Add photo folders. Scanning does not remove files.",
    "Anuluj": "Cancel", "GRUPY ZDJĘĆ": "PHOTO GROUPS",
    "Rodzaj": "Type", "Pliki": "Files",
    "PORÓWNAJ  •  Ctrl + klik: dwa zdjęcia  •  dwuklik podglądu: powiększenie": "COMPARE  •  Ctrl + click: two photos  •  double-click preview: enlarge",
    "Do kosza": "Recycle", "Zdjęcie": "Photo", "Wymiary": "Dimensions", "Rozmiar": "Size",
    "Zaznacz / odznacz do kosza": "Select / deselect for recycling",
    "Odznacz wszystko": "Clear selection", "Kopiuj ścieżkę": "Copy path",
    "◇\n\nWybierz zdjęcie do porównania": "◇\n\nChoose a photo to compare",
    "Brak wyników": "No results", "Przenieś zaznaczone do kosza": "Move selected to Recycle Bin",
    "Eksport CSV": "Export CSV", "Raport": "Report",
    "Podobne ≠ identyczne. Sprawdź podgląd. Nic nie jest zaznaczane automatycznie.": "Similar ≠ identical. Review the previews. No automatic selection.",
    "Wybierz folder ze zdjęciami": "Choose a photo folder",
    "Wybierz folder": "Choose a folder", "Najpierw dodaj co najmniej jeden folder.": "Add at least one folder first.",
    "Rozpoczynanie skanowania…": "Starting scan…",
    "Skan anulowany. Wyniki niepełne — uruchom skan ponownie.": "Scan cancelled. Results are incomplete — scan again.",
    "Gotowe • {v0} zdjęć • {v1} grup • {v2} uwag": "Done • {v0} photos • {v1} groups • {v2} notices",
    "Przeniesiono do kosza: {v0}. Uruchom nowy skan. Uwagi: {v1}.": "Moved to Recycle Bin: {v0}. Scan again. Notices: {v1}.",
    "Przerwano przenoszenie": "Recycling interrupted", "Operacja nie powiodła się.": "Operation failed.",
    "Identyczne": "Identical", "Podobne • sprawdź": "Similar • review", "TAK": "YES",
    "Obraz przekracza limit podglądu": "Image exceeds the preview size limit",
    "Podgląd niedostępny": "Preview unavailable",
    "Skopiowano pełne ścieżki wybranych zdjęć.": "Full paths of selected photos copied.",
    "Zachowaj zdjęcie": "Keep a photo",
    "Zostaw przynajmniej jedno zdjęcie w każdej grupie. Zaznacz pojedynczy wiersz, aby wybrać jedną kopię.": "Keep at least one photo in each group. Select a single row to choose one copy.",
    "Do kosza: {v0} plików • {v1}": "Selected: {v0} files • {v1}",
    "\n… i {v0} kolejnych": "\n… and {v0} more",
    "Potwierdź przeniesienie do kosza": "Confirm moving to Recycle Bin",
    "Przenieść {v0} plików do systemowego kosza?\n\n{v1}\n\nPodobne zdjęcia mogą przedstawiać różne ujęcia. Przywracanie odbywa się przez Kosz Windows.": "Move {v0} files to the Recycle Bin?\n\n{v1}\n\nSimilar photos may show different shots. Restore files using the Windows Recycle Bin.",
    "Eksport wyników": "Export results", "Zapisano raport CSV.": "CSV report saved.",
    "Eksport nieudany": "Export failed", "Raport skanowania": "Scan report",
    "Brak uwag. Obsługiwane: JPG, PNG, WebP, BMP oraz jednostronicowe TIFF/GIF. HEIC i RAW nie są obsługiwane w tej wersji.": "No notices. Supported: JPG, PNG, WebP, BMP and single-frame TIFF/GIF. HEIC and RAW are not supported in this version.",
    "Trwa operacja": "Operation in progress",
    "Przerwać operację i zamknąć po jej bezpiecznym zakończeniu?": "Cancel the operation and close when it has stopped safely?",
    "Kończenie operacji…": "Finishing operation…",
    "obraz przekracza limit 40 megapikseli": "image exceeds the 40 megapixel limit",
    "obraz animowany lub wielostronicowy — pominięty": "animated or multi-page image — skipped",
    "plik zmienił się podczas skanowania": "file changed during scanning",
    "Próg podobieństwa musi mieścić się w zakresie 0–16.": "Similarity threshold must be between 0 and 16.",
    "{v0}: folder niedostępny lub dowiązanie": "{v0}: folder unavailable or a link",
    "{v0}: dowiązanie / plik chmurowy — pominięty": "{v0}: link / cloud placeholder — skipped",
    "{v0}: drugie dowiązanie do tego samego pliku — pominięte": "{v0}: another hard link to the same file — skipped",
    "Odczytano {v0} zdjęć • {v1}": "Read {v0} photos • {v1}",
    "Porównywanie zdjęć • {v0}/{v1}": "Comparing photos • {v0}/{v1}",
    "Dowiązanie w ścieżce: {v0}": "Link in path: {v0}",
    "Plik zmienił się: {v0}": "File changed: {v0}",
    "Zawartość pliku zmieniła się: {v0}": "File content changed: {v0}",
    "Plik niedostępny: {v0}: {v1}": "File unavailable: {v0}: {v1}",
    "Skan został anulowany. Uruchom pełny skan.": "Scan was cancelled. Run a full scan.",
    "Zaznaczenie zawiera plik spoza wyników.": "Selection contains a file outside the results.",
    "Zostaw co najmniej jedno zdjęcie w każdej grupie.": "Keep at least one photo in every group.",
    "Sprawdzanie przed przeniesieniem • {v0}": "Verifying before recycling • {v0}",
    "Przeniesiono do kosza • {v0}": "Moved to Recycle Bin • {v0}",
    "Operacja przerwana; część plików mogła już trafić do kosza.": "Operation cancelled; some files may already be in the Recycle Bin.",
    "Grupa": "Group", "Typ": "Type", "Ścieżka": "Path", "Bajty": "Bytes", "Szerokość": "Width", "Wysokość": "Height",
    "Przenoszenie do kosza w tej wersji jest dostępne tylko na Windows.": "Recycling is only available on Windows in this version.",
    "Nie można ustalić woluminu pliku.": "Cannot identify the file's volume.",
    "Kosz obsługujemy tylko na lokalnych dyskach stałych. Dysk sieciowy lub wymienny: operacja zablokowana.": "Recycling is supported only on fixed local drives. Network or removable drive: operation blocked.",
    "Windows nie potwierdził dostępności kosza; plik pozostawiono na miejscu.": "Windows did not confirm Recycle Bin availability; the file was left in place.",
    "Trwałe usuwanie jest zabronione": "Permanent deletion is prohibited",
    "Błąd kosza Windows: {v0}": "Windows Recycle Bin error: {v0}",
    "Windows przerwał przenoszenie do kosza.": "Windows cancelled recycling.",
    "Windows nie zwrócił potwierdzenia umieszczenia pliku w koszu.": "Windows did not confirm the file was placed in the Recycle Bin.",
    "Plik pozostał na miejscu; kosz nie potwierdził przeniesienia.": "The file remains in place; recycling was not confirmed.",
    "Nie zapisano języka": "Language not saved",
    "Nie można zapisać ustawienia języka. Wybór będzie działał tylko do zamknięcia aplikacji.": "Cannot save the language preference. It will apply only until the app closes.",
}

def tr(message, **values):
    return (EN.get(message, message) if language == "en" else message).format(**values) if values else (EN.get(message, message) if language == "en" else message)

def settings_file():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config")) / "SwirPhotoClean" / "settings.json"

def load_language(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8")).get("language")
        return value if value in ("pl", "en") else "pl"
    except (OSError, ValueError, AttributeError):
        return "pl"

def save_language(path, value):
    if value not in ("pl", "en"):
        raise ValueError("Unsupported language")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({"language": value}, stream)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
