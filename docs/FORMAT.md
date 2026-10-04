# Notes de format et niveau de preuve

Ce document sépare les faits confirmés des hypothèses afin d'éviter de transformer un prototype fonctionnel en « spécification » non justifiée.

## Confirmé en jeu — Switch 7.1.2 → PC 7.1.2

- La couche Switch utilise le même générateur XOR/CRC32 LEVEL-5 que la couche PC.
- Les clés Switch observées sont les noms logiques `AUTOSAVE`, `HEADERSAVE` et `SYSTEM`.
- Après XOR, le wrapper Switch commence par `0x85A663B4` et transporte des blocs LZ4 raw.
- Le payload AUTOSAVE Switch peut être normalisé vers le layout PC en rétrécissant exactement 16 champs `u64 -> u32`, soit 64 octets.
- Les 32 bits hauts des 16 champs observés étaient nuls ; le convertisseur refuse une conversion destructive si ce n'est plus vrai.
- Après normalisation, les objets top-level AUTOSAVE s'alignent exactement avec ceux d'une save PC 7.1.2 native.
- Une save PC cible native est nécessaire pour transporter le contexte d'identité du compte.
- Les modes `full`, `object` et `guid` ont chacun été acceptés en jeu pendant les essais ; `full` est retenu par défaut.
- La sortie doit conserver le nom exact `002AB8F4-USERDATALIVE`, puisque ce nom participe au chiffrement.

## Matériel d'identité observé

Deux régions AUTOSAVE ont été isolées par comparaison différentielle entre comptes :

- objet `0x100BFFEE` ;
- field hash `0x18C6F574` (= `CRC32("rand")`), largeur 16 octets.

L'objet `0x100BFFEE` est de forte entropie et varie fortement entre plateformes/comptes. Son contenu n'est pas interprété ici. Le champ 16 octets varie également entre comptes. Son hash correspond à la chaîne `rand`, mais sa sémantique exacte dans cette sauvegarde reste inconnue ; le projet le traite donc comme opaque.

Le projet traite ces données comme **opaque account material**. Il ne prétend pas qu'elles contiennent directement le SteamID64.

## SteamID64

Steamworks définit `ISteamUser::GetSteamID()` comme l'identifiant unique du compte actuellement connecté. Les tests ont montré qu'une sauvegarde fonctionnelle sous un compte cesse d'être reconnue après changement d'identité puis fonctionne à nouveau quand les données d'identité correctes sont transplantées.

Ce dépôt ne possède pas encore la fonction :

```text
SteamID64 -> 0x100BFFEE / 0x18C6F574
```

Par conséquent un template PC natif reste l'autorité pour la liaison au compte.

## PC container

Valeurs confirmées par le save editor public et reproduites localement :

```text
0x00  u32 magic 0x9DCE66C3
0x04  crc32(bytes[0x08:0x800])
0x10  filename NUL-terminated
0x50  blob directory, stride 0x80
0x800 payload region
```

Chaque entrée de directory contient :

```text
u32 blob_crc32
u32 blob_size
u32 relative_offset_from_0x800
char name[]
```

Le template PC est conservé intégralement : cette stratégie préserve également les champs d'en-tête non documentés observés dans les fichiers natifs.

## Switch wrapper

En-tête observé :

```text
0x00  magic 0x85A663B4
0x04  crc32(bytes[0x08:0x10])
0x08  packed region length
0x0C  unpacked total size
0x10  constant observed 0x77E9E1B0
0x14  observed value 1
0x18  packed data length
0x20  chunk stream
```

Chunk :

```text
u32 compressed_size
u32 unpacked_size
bytes raw_lz4_block
```

Un trailer de 32 octets suit les chunks. Une partie de sa sémantique reste inconnue. C'est la raison pour laquelle PC → Switch est encore marqué expérimental : le code préserve le trailer d'un vrai template Switch mais ne prétend pas savoir le recalculer intégralement.

## Critère avant de promouvoir PC → Switch en supporté

Il faut au minimum :

1. convertir une save PC 7.1.2 vers Switch ;
2. la charger réellement dans le jeu Switch ;
3. effectuer une sauvegarde dans le jeu ;
4. réextraire la save et vérifier la persistance de la progression ;
5. comparer le trailer reconstruit au trailer réécrit par le jeu.

Tant que ce test n'est pas fait, le chemin inverse reste expérimental même s'il est structurellement round-trip valide avec notre parseur.
