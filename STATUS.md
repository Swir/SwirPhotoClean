## Rozwój do 1.0 — 2026-09-19

Gałąź `main` zawiera już warstwę profesjonalnego review z **Smart Keep**, **Folder Health**, bezpiecznym **Session Save / Resume** oraz pełnoekranowym porównaniem dwóch zdjęć z synchronicznym zoomem i panoramowaniem. Funkcje te nie zmieniają modelu bezpieczeństwa: nic nie jest automatycznie zaznaczane do usunięcia, a sesje nie zapisują zaznaczeń do Kosza.

Najnowszym publicznym wydaniem pozostaje **v0.3.0 prerelease**. Rozwój do 1.0 jest aktywny, ale stabilne 1.0 nie będzie publikowane przed przejściem całej bramki odbioru. Aktualny wynik bramki pozostaje **7 / 8 = 87,5%**; jedynym niespełnionym kryterium jest realnie potwierdzone przeniesienie wygenerowanej kopii do Kosza Windows i jej przywrócenie przy zachowaniu oryginału.

## Aktualizacja 0.3.0 — 2026-09-10

Interfejs Polski / English, wybór zapisywany w lokalnych ustawieniach użytkownika. Zmiana zachowuje wyniki, zaznaczenia, foldery i poziom podobieństwa. 29 testów przechodzi, w tym angielski układ przy skalowaniu 150%, trwałość ustawień, uszkodzony plik ustawień, nagłówki CSV i komunikaty. Samokontrola paczki sprawdza także przełączenie i ponowne uruchomienie z zapisanym językiem. Komunikaty zewnętrznych bibliotek i przyciski systemowych dialogów mogą zależeć od systemu. Historyczny raport skanowania pozostaje w języku, w którym wykonano skan.

Użytkownik potwierdził poprawne działanie 0.2.1. Wydanie 0.3.0 pozostaje wydaniem testowym; szczegółowy test przywrócenia z Kosza przed 1.0 nadal wymaga potwierdzenia.

## Poprawka 0.2.1 — 2026-09-10

Usunięto zależność od Image.get_flattened_data; skanowanie korzysta z bajtów obrazu RGB/L. Test regresji symuluje brak tej metody. 25 testów przechodzi.

## Aktualizacja 0.2.0 — 2026-09-10

Przestrzenny nagłówek, wypukłe przyciski, karty podglądów, powiększenie dwuklikiem. Poprawiono podgląd przezroczystości i blokadę odznaczania podczas operacji. 24 testy przechodzą, w tym powiększenie i stany przycisków. Udane przeniesienie do Kosza i przywrócenie nadal wymaga potwierdzenia w zwykłej sesji Windows.

# Status — aktualizowany do 2026-09-19

## Etap

Rozwój po publicznym wydaniu **v0.3.0 prerelease** w kierunku stabilnego 1.0. `main` zawiera nowsze funkcje niż ostatnie publiczne wydanie, dlatego numer publicznego release nie jest używany jako wskaźnik gotowości 1.0.

## Zweryfikowano lokalnie

- Testy silnika: identyczne pliki, podobny obraz po skalowaniu/JPEG, rozróżnianie jednolitych kolorów, uszkodzone i animowane pliki, anulowanie, powtarzające się foldery, hardlinki, eksport CSV, limit pikseli i odmowa dostępu.
- Ochrona zachowywanej kopii i blokowanie nieznanych/zmienionych plików, w tym zmiany treści przy zachowanym rozmiarze i czasie modyfikacji.
- Test GUI: utworzenie okna i dwóch podglądów, zaznaczanie, blokada całej grupy, stany przycisków.
- Poprawne zastosowanie orientacji EXIF przed obliczeniem wymiarów i podobieństwa.
- Test obciążenia 500 wygenerowanych obrazów: 1,36 s w lokalnym środowisku testowym, bez ostrzeżeń; wynik nie jest obietnicą wydajności na innych dyskach i komputerach.
- Sygnatura kolorów zajmuje 192 bajty na zdjęcie zamiast krotek liczb zmiennoprzecinkowych, co ogranicza zużycie pamięci przy większych kolekcjach.
- Próby systemowego kosza na plikach wygenerowanych w katalogu tymczasowym i w Dokumentach: środowisko nie ustawiło flagi potwierdzającej Kosz, więc aplikacja przerwała operacje i pozostawiła pliki na miejscu. Kontrolna biblioteka bez tej blokady usuwała wygenerowane pliki bez utworzenia elementu w Koszu, co potwierdziło zasadność zabezpieczenia.
- Test integracyjny Kosza Windows przy każdej kompilacji sprawdza wygenerowany plik: powodzenie wymaga zniknięcia źródła, a błąd wymaga pozostawienia go bez zmian.
- Program i okno mają własną wielorozmiarową ikonę, dołączaną również do paczki portable.
- Lokalna paczka ZIP przeszła kontrolę integralności, została rozpakowana do czystego katalogu tymczasowego, a uruchomiony z niej EXE zakończył samokontrolę kodem 0.

## Warunki odbioru — do zakończenia przed 1.0

<p align="center">
  <img width="100%" src="assets/readme/progress-mini.svg" alt="SWIR PhotoClean 1.0 acceptance gate — 7 of 8 verified, 87.5 percent" />
</p>

**Postęp bramki 1.0: 7 / 8 = 87,5%.** Wartość wynika wyłącznie z poniższej listy `[x]/[ ]`; generator `tools/readme_progress.py` aktualizuje SVG z tej samej sekcji.

- [x] Udane 24 testy, kompilacja EXE z własną ikoną, samokontrola gotowej paczki i artefakt ZIP w GitHub Actions (uruchomienie 34398518376).
- [x] Test uruchomienia gotowego EXE z własnym Tcl/Tk i dwoma podglądami obrazów. Pierwsza paczka ujawniła błąd wyszukiwania Tcl; poprawiona paczka przeszła samokontrolę.
- [x] Sprawdzenie wyglądu przy skalowaniu 100% i 150%, długich ścieżkach i minimalnym oknie 900 × 700; pełną ścieżkę można skopiować przyciskiem bez rozciągania interfejsu.
- [ ] Udane przeniesienie wygenerowanej kopii do kosza i jej przywrócenie na Windows, przy zachowaniu oryginału.
- [x] Potwierdzenie odmowy trwałego usuwania przy niedostępnym koszu: Windows nie potwierdził operacji kosza, aplikacja ją przerwała, a oba wygenerowane pliki pozostały na miejscu.
- [x] Test pracy na 500 wygenerowanych obrazach oraz anulowania w trakcie porównywania; przed 1.0 warto rozszerzyć próbę na wolniejszy dysk i większe fotografie.
- [x] Testy orientacji EXIF, limitu dużych obrazów i błędów dostępu.
- [x] Paczka portable z instrukcją i potwierdzonym zakresem obsługiwanych formatów; najnowszy artefakt CI ma skrót SHA-256 `2762fc4a3b0e551f67f421694d71e0702e1f660cad3abcefd86b8cd531087240` i wygasa 2026-12-08. Lokalna paczka do testu ma SHA-256 `38ce4542e0dd018d4969df4da0c36c7a1f2ff927b6ad51eb4cbfafa59ebf3b34`.

## Notatki środowiska deweloperskiego

Lokalny runtime dostarczony z aplikacją wymagał względnych TCL_LIBRARY/TK_LIBRARY do skopiowanego katalogu Tcl/Tk; ścieżki absolutne nie działały w jego środowisku wykonawczym. Nie wprowadzono tych lokalnych ścieżek do kodu aplikacji. CI używa oficjalnego Pythona 3.12.

## Następne kroki

Przed 1.0 potwierdzić przywracanie z Kosza, kontynuować hardening nowych funkcji review i rozszerzyć testy większych zbiorów oraz dużych fotografii bez osłabiania dotychczasowych zabezpieczeń.
