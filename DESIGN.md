# git-vault — design (wariant 2: append-only encrypted bundles)

Prywatny vault: lokalnie plaintext git, na GitHubie tylko zaszyfrowane bundle’e. Push/pull przez CLI `git-vault`; agenci (Cursor / Claude) używają skilli zamiast surowego `git push`/`pull` dla oznaczonych repo.

## Cele

- Inkrementalny upload (tylko nowy bundle + mały manifest)
- Jedno master-password → per-repo key (HKDF)
- Share jednego repo bez ujawniania master-password
- Skill w Cursor i Claude Code wymusza CLI

## Poza zakresem MVP

- Custom git remote helper (`vault::…`)
- Współbieżny push od wielu osób (lock / CRDT)
- Szyfrowanie nazw plików / metadata GitHub (nazwa repo widoczna)

---

## Model kryptograficzny

```
master_password
    │
    ▼
Argon2id(master, salt=global_salt)  →  master_key   # raz na sesję / keychain
    │
    ▼
HKDF-SHA256(master_key, info="git-vault:v1:"+repo_id)  →  repo_key
    │
    ▼
AES-256-GCM (file magic GVAULT1; filenames keep .age suffix)
    szyfruje: bundle N + manifest
```

> MVP uses `cryptography` AES-GCM, not the `age` binary. Wire format is `GVAULT1` + nonce + ciphertext. Swap to real `age` later if desired without changing the CLI UX.

| Element | Wartość |
|---|---|
| `repo_id` | kanoniczna nazwa vaultu, np. `github.com/user/my-notes` (nie lokalna ścieżka) |
| `global_salt` | stały per instalacja, w `~/.config/git-vault/salt` (losowy 16B, nie sekret sam w sobie) |
| KDF | Argon2id, parametry ~0.5–1 s na urządzeniu użytkownika |
| Per-repo key | 32 bajty; eksportowalny do share |

**Share bez master-password:** eksport `repo_key` jako plik `*.vaultkey` albo passphrase-wrap; odbiorca: `git-vault unlock --key-file …`. Alternatywa: `age` recipients (klucz publiczny współpracownika).

---

## Layout na GitHubie (remote vault)

Zwykłe (prywatne) repo GitHub. Zawartość **nie** jest working tree projektu — to magazyn artefaktów:

```
my-notes-vault/                 # repo na GitHubie
├── README.md                   # opcjonalnie: „encrypted vault, use git-vault”
├── vault.json                  # jawny metadany (wersja formatu, repo_id) — BEZ sekretów
├── manifest.age                # zaszyfrowany indeks
└── bundles/
    ├── 000001.bundle.age
    ├── 000002.bundle.age
    └── …
```

### `vault.json` (plaintext)

```json
{
  "format": "git-vault/1",
  "repo_id": "github.com/user/my-notes",
  "bundle_count": 2
}
```

### Manifest (odszyfrowany, JSON)

```json
{
  "repo_id": "github.com/user/my-notes",
  "head": "abc123…",
  "bundles": [
    {
      "seq": 1,
      "file": "bundles/000001.bundle.age",
      "from": null,
      "to": "def456…",
      "sha256": "…"
    },
    {
      "seq": 2,
      "file": "bundles/000002.bundle.age",
      "from": "def456…",
      "to": "abc123…",
      "sha256": "…"
    }
  ]
}
```

### Bundle

Wynik `git bundle create …` zawierający tylko nowe commity od poprzedniego `to` → HEAD, potem zaszyfrowany jako `NNNNNN.bundle.age`.

---

## Layout lokalny

```
~/code/my-notes/                 # normalne repo git (plaintext)
├── .git/
├── .git-vault                   # marker: to vault-managed working copy
│   ├── repo_id
│   ├── remote                   # np. git@github.com:user/my-notes-vault.git
│   └── last_seq                 # ostatni zaaplikowany bundle
└── …pliki projektu…
```

Konfiguracja globalna:

```
~/.config/git-vault/
├── salt
├── config.toml                  # domyślny remote host, age recipients, …
└── (opcjonalnie) keychain hint
```

Hasło: macOS Keychain / `GIT_VAULT_PASSWORD` / interaktywny prompt. **Nigdy** w skillu ani w czacie na stałe.

---

## Kontrakt CLI

Binary / entrypoint: `git-vault` (alias OK: `gv`).

### Komendy

```bash
# Inicjalizacja nowego vaultu (tworzy GitHub repo artefaktów + lokalny marker)
git-vault init [--repo-id ID] [--remote git@github.com:user/name-vault.git]

# Sklonuj vault → lokalny plaintext working tree
git-vault clone <remote-url> [dir]

# Pobierz nowe bundle’e, odszyfruj, unbundle
git-vault pull

# Zrób bundle od last_seq, zaszyfruj, wypchnij do remote vault
git-vault push

# Status: last_seq, head lokalny vs manifest, czy są niepushnięte commity
git-vault status

# Eksport klucza jednego repo (share)
git-vault export-key [--out path.vaultkey]

# Odblokuj lokalną kopię kluczem share (bez master-password)
git-vault unlock --key-file path.vaultkey
```

### Semantyka `push`

1. Wymaga czystego lub commitniętego stanu (MVP: tylko committed).
2. Jeśli brak nowych commitów względem `manifest.head` → no-op.
3. `git bundle create /tmp/….bundle <from>..<HEAD>` (pierwszy push: `--all` lub root..HEAD).
4. Szyfruj bundle → `bundles/NNNNNN.bundle.age`.
5. Zaktualizuj manifest + `vault.json`.
6. W katalogu cache remote: commit + `git push` (jeden mały commit z nowym plikiem).
7. Zapisz `last_seq` lokalnie.

### Semantyka `pull`

1. `git fetch` / pull remote vault (artefakty).
2. Odszyfruj manifest.
3. Dla każdego `seq > last_seq`: odszyfruj bundle → `git unbundle` → `git checkout`/`merge` FF.
4. Ustaw `last_seq`.

### Kody wyjścia

| Kod | Znaczenie |
|---|---|
| 0 | OK / no-op |
| 2 | brak hasła / zły klucz |
| 3 | konflikt (lokalny HEAD ≠ oczekiwany `from`) |
| 4 | remote / sieć |
| 5 | uszkodzony bundle / hash mismatch |

### Wykrywanie vault-repo

Repo jest vaultem, gdy istnieje `.git-vault/repo_id` **lub** remote URL jest na liście w `~/.config/git-vault/config.toml`.

Agent **nigdy** nie robi `git push origin` / `git pull origin` na takim repo — tylko `git-vault push` / `git-vault pull`.

Lokalne `git commit`, `git status`, `git diff` — dozwolone i pożądane.

---

## Integracja z agentami

```
┌─────────────┐     ┌─────────────┐
│ Cursor skill│     │ Claude skill│
└──────┬──────┘     └──────┬──────┘
       │                   │
       └─────────┬─────────┘
                 ▼
           git-vault CLI
                 ▼
         GitHub (ciphertext)
```

Skill = reguły zachowania. CLI = egzekucja crypto.

Instalacja skilli (docelowa):

| Środowisko | Ścieżka |
|---|---|
| Cursor (personal) | `~/.cursor/skills/git-vault/SKILL.md` |
| Claude Code (personal) | `~/.claude/skills/git-vault/SKILL.md` |

Szkielety w tym katalogu: `skills/cursor/`, `skills/claude/`.

---

## MVP — kolejność implementacji

1. CLI: `init`, `push`, `pull`, `clone`, `status` + Argon2/HKDF + age
2. Marker `.git-vault` + detekcja
3. Skill Cursor + skill Claude
4. `export-key` / `unlock`
5. (później) remote helper `vault::` dla twardego „zawsze”

---

## Ryzyka

| Ryzyko | Mitygacja |
|---|---|
| Agent zrobi zwykły `git push` | Skill + opcjonalnie usuń `origin` push URL / remote helper |
| Utrata master-password | Backup keychain / wydrukowane recovery / export-key offline |
| Konflikt przy dwóch maszynach | `pull` przed `push`; exit 3 przy divergencji |
| Wyciek hasła w logach agenta | Tylko keychain / TTY prompt; zabraniać `echo $PASS` w skillu |
