# Status — 2026-09-09

## Etap

0.1.0 — działająca wersja rozwojowa, jeszcze nie zatwierdzone wydanie stabilne.

## Zweryfikowano lokalnie

- Testy silnika: identyczne pliki, podobny obraz po skalowaniu/JPEG, rozróżnianie jednolitych kolorów, uszkodzone i animowane pliki, anulowanie, powtarzające się foldery, hardlinki, eksport CSV, limit pikseli i odmowa dostępu.
- Ochrona zachowywanej kopii i blokowanie nieznanych/zmienionych plików, w tym zmiany treści przy zachowanym rozmiarze i czasie modyfikacji.
- Test GUI: utworzenie okna i dwóch podglądów, zaznaczanie, blokada całej grupy, stany przycisków.
- Poprawne zastosowanie orientacji EXIF przed obliczeniem wymiarów i podobieństwa.
- Test obciążenia 500 wygenerowanych obrazów: 1,36 s w lokalnym środowisku testowym, bez ostrzeżeń; wynik nie jest obietnicą wydajności na innych dyskach i komputerach.
- Sygnatura kolorów zajmuje 192 bajty na zdjęcie zamiast krotek liczb zmiennoprzecinkowych, co ogranicza zużycie pamięci przy większych kolekcjach.
- Próba systemowego kosza wyłącznie na wygenerowanych danych: Windows zwrócił przerwanie; oba pliki pozostały na miejscu. Nie uznano tej próby za udane przeniesienie.
- Test integracyjny Kosza Windows przy każdej kompilacji sprawdza wygenerowany plik: powodzenie wymaga zniknięcia źródła, a błąd wymaga pozostawienia go bez zmian.
- Program i okno mają własną wielorozmiarową ikonę, dołączaną również do paczki portable.

## Warunki odbioru — do zakończenia przed 1.0

- [x] Udane 24 testy, kompilacja EXE z własną ikoną, samokontrola gotowej paczki i artefakt ZIP w GitHub Actions (uruchomienie 34396350426).
- [x] Test uruchomienia gotowego EXE z własnym Tcl/Tk i dwoma podglądami obrazów. Pierwsza paczka ujawniła błąd wyszukiwania Tcl; poprawiona paczka przeszła samokontrolę.
- [x] Sprawdzenie wyglądu przy skalowaniu 100% i 150%, długich ścieżkach i minimalnym oknie 900 × 700; pełną ścieżkę można skopiować przyciskiem bez rozciągania interfejsu.
- [ ] Udane przeniesienie wygenerowanej kopii do kosza i jej przywrócenie na Windows, przy zachowaniu oryginału.
- [x] Potwierdzenie odmowy trwałego usuwania przy niedostępnym koszu: Windows nie potwierdził operacji kosza, aplikacja ją przerwała, a oba wygenerowane pliki pozostały na miejscu.
- [x] Test pracy na 500 wygenerowanych obrazach oraz anulowania w trakcie porównywania; przed 1.0 warto rozszerzyć próbę na wolniejszy dysk i większe fotografie.
- [x] Testy orientacji EXIF, limitu dużych obrazów i błędów dostępu.
- [x] Paczka portable z instrukcją i potwierdzonym zakresem obsługiwanych formatów; najnowszy artefakt CI ma skrót SHA-256 `6b7f0375ebca3d1a4f5ac16c0d598e65ae0770307e41a3da7d8f82218bac2297` i wygasa 2026-12-08.

## Notatki środowiska deweloperskiego

Lokalny runtime dostarczony z aplikacją wymagał względnych TCL_LIBRARY/TK_LIBRARY do skopiowanego katalogu Tcl/Tk; ścieżki absolutne nie działały w jego środowisku wykonawczym. Nie wprowadzono tych lokalnych ścieżek do kodu aplikacji. CI używa oficjalnego Pythona 3.12.

## Następne kroki

Najpierw zweryfikować EXE i kosz, następnie testy większych zbiorów oraz ergonomię interfejsu. Automatyzacja godzinowa ma kontynuować uzasadnione poprawki i aktualizować dowody tutaj. Zakończyć cykl po spełnieniu warunków odbioru, nie po samej kompilacji.

