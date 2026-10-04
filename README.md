# IEVR Save Converter

Outils de conversion de sauvegardes **INAZUMA ELEVEN: Victory Road** entre Nintendo Switch et PC.

> État actuel : **Switch 7.1.2 → PC 7.1.2 confirmé en jeu**. Le chemin inverse est présent à titre **expérimental** seulement.

Le convertisseur a été construit à partir de sauvegardes réelles Switch et PC 7.1.2, puis validé avec plusieurs comptes PC. Il ne modifie jamais la sauvegarde source.

## Ce qui est réellement prouvé

La conversion Switch → PC nécessite deux choses différentes :

1. la progression Switch, que l'outil déchiffre, décompresse et normalise vers le layout PC ;
2. un **`002AB8F4-USERDATALIVE` natif créé sous le compte Steam cible**, utilisé comme gabarit pour conserver les données d'identité locales attendues par le jeu.

Les essais en jeu ont confirmé les trois stratégies de transplantation suivantes :

- `full` — objet d'identité `0x100BFFEE` + champ 16 octets `0x18C6F574` ; **recommandé** ;
- `object` — objet `0x100BFFEE` seulement ;
- `guid` — champ `0x18C6F574` seulement.

`full` est la valeur par défaut.

### Important : SteamID64 seul ne suffit pas encore

Le jeu est lié à l'identité Steam exposée par le runtime. Steamworks fournit cette identité via `SteamUser()->GetSteamID()`. Cependant, le reverse engineering actuel **ne permet pas de calculer de façon fiable les blobs d'identité du jeu à partir du seul nombre SteamID64**.

L'option `--steam-id` existe donc pour :

- indiquer clairement le compte cible dans le manifeste de conversion ;
- éviter de mélanger plusieurs comptes pendant les essais ;
- préparer une future dérivation directe si le format est complètement résolu.

Mais la liaison binaire est actuellement obtenue à partir de `--pc-template`, c'est-à-dire une sauvegarde PC neuve créée sous le compte cible.

## Installation

Python 3.9+ suffit. NumPy est facultatif mais accélère énormément le chiffrement/déchiffrement des fichiers de ~12 Mo.

```bash
python -m pip install .
# option rapide
python -m pip install '.[fast]'
```

Sans installation :

```bash
python -m ievr --help
```

## Conversion Switch → PC

### 1. Préparer la sauvegarde Switch

L'entrée peut être :

- un ZIP contenant `AUTOSAVE/data.bin` et `HEADERSAVE/data.bin` ;
- ou le dossier extrait contenant ces mêmes chemins.

### 2. Créer un gabarit PC sous le compte Steam cible

Connecte **le compte Steam qui utilisera la sauvegarde**, lance le jeu et crée une sauvegarde neuve de quelques secondes. Quitte ensuite le jeu.

Récupère au minimum :

```text
002AB8F4-USERDATALIVE
```

Si ton runtime produit aussi :

```text
002AB8F4-SYSTEMLIVE
```

conserve-le également. Pour OnlineFix, le dossier rencontré pendant les tests était :

```text
C:\Users\Public\Documents\OnlineFix\2799860\Saves
```

Sur Steam officiel, le save editor public documente plutôt :

```text
C:\Program Files (x86)\Steam\userdata\<account-id>\2799860\remote\
```

Le chemin peut dépendre du runtime. Si nécessaire, utilise **Process Monitor** et filtre `nie.exe` + `WriteFile` pour voir le chemin réellement écrit.

### 3. Trouver son SteamID64

Le SteamID64 est un entier décimal de 17 chiffres, par exemple :

```text
76561198xxxxxxxxx
```

Méthodes simples :

1. ouvre ton profil Steam dans un navigateur et copie l'URL ; si elle ressemble à `https://steamcommunity.com/profiles/76561198...`, le nombre est directement le SteamID64 ;
2. si tu utilises une URL personnalisée `/id/nom`, un outil comme **steamid.io** peut résoudre le SteamID64 ;
3. techniquement, c'est l'identifiant retourné au jeu par l'API Steamworks `ISteamUser::GetSteamID()`.

Le SteamID fourni à l'outil doit correspondre au compte qui a créé le `--pc-template`.

### 4. Convertir

```bash
ievr-convert switch-to-pc save_switch.zip \
  --pc-template ./002AB8F4-USERDATALIVE \
  --system-template ./002AB8F4-SYSTEMLIVE \
  --steam-id 76561198XXXXXXXXX \
  --output ./converted
```

Ou sans installation :

```bash
python -m ievr switch-to-pc save_switch.zip \
  --pc-template ./002AB8F4-USERDATALIVE \
  --steam-id 76561198XXXXXXXXX \
  --output ./converted
```

Sortie :

```text
converted/
  002AB8F4-USERDATALIVE
  002AB8F4-SYSTEMLIVE       # si --system-template a été fourni
  ievr-conversion.json
```

**Ne renomme pas `002AB8F4-USERDATALIVE`.** Le nom exact participe à la clé du chiffrement PC.

Ferme toujours le jeu avant de remplacer les fichiers et fais une sauvegarde du dossier original.

### Modes d'identité

```bash
--identity-mode full    # défaut, recommandé
--identity-mode object  # objet 0x100BFFEE uniquement
--identity-mode guid    # champ 0x18C6F574 uniquement
```

Les trois ont été confirmés en jeu pendant le reverse engineering ; `full` garde le plus de cohérence avec le compte cible.

## Inspection / diagnostic

PC :

```bash
ievr-convert inspect-pc 002AB8F4-USERDATALIVE
ievr-convert inspect-pc 002AB8F4-SYSTEMLIVE --name 002AB8F4-SYSTEMLIVE
```

Switch :

```bash
ievr-convert inspect-switch save_switch.zip
```

L'inspection PC valide le chiffrement, le magic, les CRC du header et des blobs, puis affiche l'empreinte du matériel d'identité connu.

## Conversion PC → Switch — expérimental

Le **payload** inverse PC → Switch est compris : les quatre champs qui passent de `u64` sur Switch à `u32` sur PC peuvent être restaurés sans perte.

En revanche, l'enveloppe Switch contient encore un champ de trailer dont la sémantique n'est pas entièrement résolue. Le code peut reconstruire un wrapper qui se redécompresse correctement, mais **l'acceptation par le jeu Switch n'est pas encore confirmée**.

Le chemin est donc volontairement bloqué derrière `--experimental` et exige une vraie sauvegarde Switch comme gabarit :

```bash
ievr-convert pc-to-switch 002AB8F4-USERDATALIVE \
  --switch-template save_switch.zip \
  --output converted-switch \
  --experimental
```

N'utilise pas cette sortie sur ta seule copie de sauvegarde Switch.

## Ce que fait la conversion 7.1.2

La sauvegarde Switch utilise :

```text
AUTOSAVE/data.bin
HEADERSAVE/data.bin
```

Chaque `data.bin` est :

```text
XOR LEVEL-5 (clé CRC32 du nom logique)
    ↓
wrapper 0x85A663B4
    ↓
chunks LZ4 bruts
    ↓
payload sérialisé
```

Le PC utilise un conteneur `002AB8F4-USERDATALIVE` :

```text
XOR LEVEL-5 (clé CRC32 du nom exact du fichier)
    ↓
header 0x800 / magic 0x9DCE66C3
    ↓
AUTOSAVE_data.bin
HEADERSAVE_data.bin
```

La différence de layout observée entre Switch et PC 7.1.2 est exactement de **64 octets** dans AUTOSAVE. Quatre field hashes sont sérialisés en `u64` sur Switch et `u32` sur PC :

| Field hash | Occurrences | Switch | PC |
|---|---:|---:|---:|
| `0x215B03C6` | 1 | 8 bytes | 4 bytes |
| `0xEDC55DC5` | 1 | 8 bytes | 4 bytes |
| `0xF1D2AADB` | 7 | 8 bytes | 4 bytes |
| `0xBE2D4E2D` | 7 | 8 bytes | 4 bytes |

Les 32 bits hauts observés sur Switch sont tous nuls. Deux longueurs d'objets englobants sont ajustées :

```text
0x1002FFEE : -8 bytes
0x1019FFEE : -56 bytes
```

Après cette normalisation, les objets AUTOSAVE Switch et PC 7.1.2 s'alignent en position et taille.

Pour lier la progression au compte PC cible, le mode `full` transplante depuis le template PC :

```text
objet 0x100BFFEE
champ 0x18C6F574 (16 bytes)
```

puis conserve le conteneur et le `HEADERSAVE` natifs du compte cible et recalcule tous les CRC.

## Tests

```bash
python -m unittest discover -s tests -v
```

Les tests synthétiques couvrent :

- chiffrement LEVEL-5 aller-retour ;
- décompression LZ4 ;
- normalisation Switch ↔ PC des 64 octets ;
- transplantation des trois modes d'identité ;
- parsing/reconstruction du conteneur PC et CRC ;
- reconstruction structurelle expérimentale d'une enveloppe Switch.

Aucune sauvegarde utilisateur réelle n'est stockée dans ce dépôt.

## Sources / travaux antérieurs

Ce projet s'appuie sur plusieurs sources publiques et sur du reverse engineering différentiel effectué sur des sauvegardes 7.1.2 réelles :

- Save editor PC 7.1.2 de `adhyayanrathi01`, qui documente le conteneur PC, le chiffrement filename-keyed, les CRC et le format TLV :  
  https://github.com/adhyayanrathi01/inazuma-eleven-victory-road-save-editor
- Save editor PC/PS4 d'`alfizari`, preuve indépendante que les payloads peuvent être transportés entre représentations console/PC :  
  https://github.com/alfizari/Inazuma-Eleven-Victory-Road-Save-Editor
- Guide officiel LEVEL-5 de Cross-Save Switch/Steam :  
  https://www.inazuma.jp/victory-road/en/guide/cross-save/
- Documentation Steamworks `ISteamUser::GetSteamID()` :  
  https://partner.steamgames.com/doc/api/ISteamUser

Voir aussi [`docs/FORMAT.md`](docs/FORMAT.md) pour le niveau de preuve et les zones encore inconnues.

## Limites et sécurité

- Testé avec **Victory Road 7.1.2**. Une mise à jour peut modifier la sérialisation.
- L'identité PC n'est pas dérivée du SteamID64 seul : utilise un template natif du compte cible.
- Fais toujours des backups.
- Utilisation prévue pour les sauvegardes locales/offline que tu possèdes.
- Le chemin PC → Switch reste expérimental tant qu'un round-trip n'a pas été confirmé dans le jeu.

## Licence

MIT. Voir [`LICENSE`](LICENSE).
