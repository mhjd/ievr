# SteamID64 et liaison des sauvegardes

## Pourquoi le compte Steam compte même avec un runtime local

Le jeu peut recevoir une identité Steam via l'API Steamworks ou une couche compatible, indépendamment de l'emplacement physique des fichiers de sauvegarde.

La documentation Steamworks décrit `ISteamUser::GetSteamID()` comme l'identifiant du compte actuellement connecté.

Ainsi, deux comptes peuvent utiliser le même dossier physique tout en étant considérés comme deux utilisateurs différents par le jeu.

## Trouver le SteamID64

Un SteamID64 est un nombre décimal de 17 chiffres.

### URL de profil numérique

Ouvre ton profil Steam dans le navigateur. Si l'URL est :

```text
https://steamcommunity.com/profiles/76561198XXXXXXXXX
```

le nombre final est ton SteamID64.

### URL personnalisée

Si ton URL ressemble à :

```text
https://steamcommunity.com/id/mon-pseudo
```

utilise un résolveur comme https://steamid.io/ pour obtenir la valeur SteamID64.

## Pourquoi `--pc-template` reste nécessaire

Le reverse engineering a identifié des données liées au compte dans AUTOSAVE, mais leur génération à partir du seul SteamID64 n'est pas connue. Il serait donc trompeur de prétendre qu'un `--steam-id` suffit à re-signer une sauvegarde.

Le workflow sûr est :

1. se connecter au compte cible ;
2. lancer le jeu ;
3. créer une sauvegarde PC neuve ;
4. donner son `002AB8F4-USERDATALIVE` à `--pc-template` ;
5. fournir aussi `--steam-id` pour identifier explicitement la cible dans le manifeste.
