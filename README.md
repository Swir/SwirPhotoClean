# SWIR PhotoClean

<img src="assets/SwirPhotoClean.png" width="160" alt="Ikona SWIR PhotoClean">

**Znajdź duplikaty i podobne zdjęcia na Windows. Porównaj je i odzyskaj miejsce.**

Lokalna aplikacja z polskim interfejsem. Bez konta, abonamentu i wysyłania zdjęć do internetu.

> Wersja 0.1.0: pierwsze wydanie testowe. Podobieństwo jest wskazówką do ręcznego porównania, nie potwierdzeniem, że można usunąć zdjęcie.

## Funkcje

- Wiele folderów i skanowanie podfolderów w tle; przycisk anulowania.
- **Identyczne pliki:** porównanie SHA-256 całej zawartości.
- **Podobne zdjęcia:** różnicowy hash obrazu, proporcje i porównanie kolorów. Trzy poziomy czułości.
- Podgląd dwóch zdjęć obok siebie, wymiary i rozmiary; pełne ścieżki można skopiować jednym przyciskiem.
- Ręczne zaznaczanie plików do systemowego kosza. Brak automatycznego zaznaczania.
- Blokada zaznaczenia wszystkich zdjęć w dowolnej grupie.
- Ponowne sprawdzenie zawartości i metadanych wybranych plików oraz zachowywanych kopii przed operacją.
- Raport pominiętych plików i eksport wyników do CSV czytelnego w Excelu.

## Uruchomienie ze źródeł

Windows 10/11, Python **3.12** z oficjalnego instalatora python.org (włączony Tcl/Tk).

```powershell
git clone https://github.com/Swir/SwirPhotoClean.git
cd SwirPhotoClean
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

## Jak używać

1. Kliknij **Dodaj folder**. Możesz dodać więcej niż jeden.
2. Wybierz, czy szukać również podobnych zdjęć. Zacznij od poziomu Standardowego.
3. Kliknij **Skanuj zdjęcia** i poczekaj na zakończenie.
4. Wybierz grupę po lewej. Zaznacz do dwóch wierszy z użyciem Ctrl, aby porównać obrazy.
5. W razie potrzeby kliknij **Kopiuj ścieżkę**, aby skopiować pełne położenie wybranych zdjęć.
6. Wybierz pojedynczy plik i kliknij **Zaznacz / odznacz do kosza**. Kolumna „Do kosza” pokaże TAK. Sam wybór wiersza do podglądu niczego nie zaznacza do usunięcia.
7. Kliknij **Przenieś zaznaczone do kosza**, sprawdź listę i potwierdź.
8. Pliki można przywrócić przez systemowy Kosz Windows. Po przenoszeniu wykonaj nowy skan.

„Do kosza” pokazuje sumę rozmiarów zaznaczonych plików, nie gwarantowaną ilość wolnego miejsca. Pliki w koszu nadal zajmują miejsce; aplikacja nie opróżnia kosza.

## Obsługiwane pliki i ograniczenia

- JPG/JPEG, PNG, WebP, BMP oraz pojedyncze obrazy TIFF/GIF.
- HEIC, RAW, animacje i wielostronicowe pliki nie są obsługiwane. Obrazy powyżej 40 megapikseli są pomijane i raportowane.
- Dowiązania, junctions i pliki z atrybutem reparse (w tym część plików chmurowych) są pomijane. Hardlink do już odczytanego pliku nie jest liczony jako kolejna kopia.
- Kosz działa wyłącznie na lokalnych dyskach stałych w Windows. Dyski sieciowe i wymienne mogą być skanowane, ale przenoszenie z nich jest blokowane.
- Podobne zdjęcia mogą być różnymi ujęciami. Obrót bez EXIF, duże kadrowanie i znaczne zmiany kolorów mogą nie zostać wykryte.
- Grupa podobieństwa porównuje zdjęcia ze stałym zdjęciem bazowym; nie wszystkie pary w grupie muszą być równie podobne. Grupy identyczne i podobne mogą się częściowo pokrywać.
- Przy pierwszym błędzie kosza przenoszenie jest zatrzymywane. Wcześniejsze udane operacje nie są automatycznie cofane.
- Nie edytuj i nie synchronizuj aktywnie skanowanych folderów podczas przenoszenia. Program ponownie sprawdza pliki, ale nie blokuje innych aplikacji przed zmianami.

## English

SWIR PhotoClean is a local **Windows duplicate photo finder and similar image finder** with a Polish interface. Scan multiple folders, compare images side by side, review dimensions and sizes, export a CSV report and manually move selected copies to the Windows Recycle Bin. No account or cloud upload is required.

Exact matches use full-file SHA-256. Similarity uses gradient hashes, aspect ratios and a low-resolution color comparison. Similar matches require human review. The app never automatically selects photos for disposal and prevents selecting every member of a group.

## Testy i budowanie EXE

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name SwirPhotoClean --icon assets/SwirPhotoClean.ico --add-data "assets;assets" run.py
```

Uruchom `dist/SwirPhotoClean/SwirPhotoClean.exe`. Do przenoszenia aplikacji skopiuj **cały folder** `dist/SwirPhotoClean`, nie sam plik EXE.

Automatyzacja GitHub Actions testuje kod na Windows i buduje paczkę ZIP jako artefakt. Artefakt kompilacji nie oznacza automatycznie zatwierdzonego wydania. Aktualny zakres weryfikacji: [STATUS.md](STATUS.md).

## Zgłaszanie problemów

Otwórz [Issues](https://github.com/Swir/SwirPhotoClean/issues). Podaj wersję Windows i aplikacji, kroki odtworzenia, typ pliku i komunikat błędu. Dołączaj tylko zdjęcia, które możesz publicznie udostępnić.

Autor: [Swir](https://github.com/Swir) · [Pozostałe programy](https://github.com/Swir#readme)
