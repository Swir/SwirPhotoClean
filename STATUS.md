# Status — 2026-09-09

## Etap

0.1.0 — działająca wersja rozwojowa, jeszcze nie zatwierdzone wydanie stabilne.

## Zweryfikowano lokalnie

- 16 testów silnika: identyczne pliki, podobny obraz po skalowaniu/JPEG, rozróżnianie jednolitych kolorów, uszkodzone i animowane pliki, anulowanie, powtarzające się foldery, hardlinki, eksport CSV.
- Ochrona zachowywanej kopii i blokowanie nieznanych/zmienionych plików, w tym zmiany treści przy zachowanym rozmiarze i czasie modyfikacji.
- Test GUI: utworzenie okna i dwóch podglądów, zaznaczanie, blokada całej grupy, stany przycisków.
- Próba systemowego kosza wyłącznie na wygenerowanych danych: Windows zwrócił przerwanie; oba pliki pozostały na miejscu. Nie uznano tej próby za udane przeniesienie.

## Warunki odbioru — do zakończenia przed 1.0

- [ ] Udane testy i kompilacja EXE w GitHub Actions.
- [x] Test uruchomienia gotowego EXE z własnym Tcl/Tk i dwoma podglądami obrazów. Pierwsza paczka ujawniła błąd wyszukiwania Tcl; poprawiona paczka przeszła samokontrolę.
- [ ] Sprawdzenie wyglądu przy skalowaniu 100% i 150%, długich ścieżkach i małym oknie.
- [ ] Udane przeniesienie wygenerowanej kopii do kosza i jej przywrócenie na Windows, przy zachowaniu oryginału.
- [ ] Potwierdzenie odmowy trwałego usuwania przy niedostępnym koszu.
- [ ] Test pracy na większym zbiorze danych, responsywności i anulowania w trakcie porównywania.
- [ ] Testy formatu EXIF, limitu dużych obrazów i błędów dostępu.
- [ ] Paczka portable z instrukcją i potwierdzonym zakresem obsługiwanych formatów.

## Notatki środowiska deweloperskiego

Lokalny runtime dostarczony z aplikacją wymagał względnych TCL_LIBRARY/TK_LIBRARY do skopiowanego katalogu Tcl/Tk; ścieżki absolutne nie działały w jego środowisku wykonawczym. Nie wprowadzono tych lokalnych ścieżek do kodu aplikacji. CI używa oficjalnego Pythona 3.12.

## Następne kroki

Najpierw zweryfikować EXE i kosz, następnie testy większych zbiorów oraz ergonomię interfejsu. Automatyzacja godzinowa ma kontynuować uzasadnione poprawki i aktualizować dowody tutaj. Zakończyć cykl po spełnieniu warunków odbioru, nie po samej kompilacji.
