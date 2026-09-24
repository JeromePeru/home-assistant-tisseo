# Tisséo – Prochains passages pour Home Assistant

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Integration-41BDF5?logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS](https://img.shields.io/badge/HACS-Custom%20Repository-41BDF5)](https://hacs.xyz/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Intégration communautaire Home Assistant permettant d’afficher les prochains passages des bus et tramways du réseau Tisséo de l’agglomération toulousaine.

L’arrêt et les lignes sont choisis directement pendant la configuration. L’intégration utilise les données ouvertes officielles GTFS et GTFS-Realtime de Tisséo, sans compte utilisateur ni clé API.

## Fonctionnalités

- recherche d’un arrêt par son nom, accents facultatifs ;
- choix de plusieurs lignes à suivre ;
- prochains passages avec destination, heure exacte et temps d’attente ;
- distinction entre données en temps réel et horaires théoriques ;
- un capteur global et un capteur par ligne ;
- intervalle d’actualisation configurable de 15 à 300 secondes ;
- fonctionnement sans désactiver la vérification des certificats TLS ;
- interface de configuration et traductions française et anglaise.

## Installation avec HACS

Ce dépôt peut être ajouté comme dépôt personnalisé tant qu’il n’est pas inclus dans le catalogue HACS par défaut.

1. Dans HACS, ouvrir **Intégrations**.
2. Ouvrir le menu ⋮ puis **Dépôts personnalisés**.
3. Ajouter l’URL `https://github.com/JeromePeru/home-assistant-tisseo`.
4. Choisir la catégorie **Intégration**.
5. Rechercher puis télécharger **Tisséo – Prochains passages**.
6. Redémarrer Home Assistant.

## Installation manuelle

1. Télécharger le dépôt.
2. Copier `custom_components/tisseo` dans `/config/custom_components/tisseo`.
3. Redémarrer Home Assistant.

L’arborescence doit être la suivante :

```text
/config
└── custom_components
    └── tisseo
        ├── __init__.py
        ├── config_flow.py
        ├── manifest.json
        └── ...
```

## Configuration

1. Ouvrir **Paramètres → Appareils et services**.
2. Cliquer sur **Ajouter une intégration**.
3. Rechercher **Tisséo – Prochains passages**.
4. Saisir tout ou partie du nom de l’arrêt.
5. Sélectionner l’arrêt, puis les lignes à suivre.
6. Choisir le nombre de passages et la fréquence d’actualisation.

Pour changer ensuite les lignes : **Paramètres → Appareils et services → Tisséo → Configurer**.

## Entités

L’intégration crée :

- `sensor.tisseo_<arret>_next_departures` : liste globale des prochains passages ;
- `sensor.tisseo_<arret>_<ligne>` : minutes avant le prochain passage de la ligne.

L’attribut `passages` contient notamment :

```yaml
- ligne: T1
  destination: Palais de Justice
  heure: "2026-09-23T10:32:00+02:00"
  dans_minutes: 6
  temps_reel: true
  quai: "stop_point:SP_605"
```

## Exemple de carte Lovelace

Adaptez l’identifiant du capteur à celui créé par Home Assistant :

```yaml
type: markdown
title: Prochains passages
content: >-
  {% set p = state_attr('sensor.tisseo_aeroconstellation_next_departures', 'passages') or [] %}
  {% if p %}
  <table width="100%" cellpadding="7" cellspacing="0">
  <thead><tr><th align="left">Ligne</th><th align="left">Direction</th><th align="right">Départ</th><th align="left">Statut</th></tr></thead>
  <tbody>
  {% for x in p %}<tr><td><b>{{ '🚊' if x.ligne.startswith('T') else '🚌' }}&nbsp; {{ x.ligne }}</b></td><td>{{ x.destination }}</td><td align="right"><b>{% if x.dans_minutes == 0 %}Maintenant{% else %}{{ x.dans_minutes }} min{% endif %}</b><br><small>{{ as_timestamp(x.heure) | timestamp_custom('%H:%M') }}</small></td><td>{{ '🟢 Temps réel' if x.temps_reel else '⚪ Horaire prévu' }}</td></tr>{% endfor %}
  </tbody></table>
  {% else %}
  Aucun passage annoncé dans les trois prochaines heures.
  {% endif %}
```

### Dashboard graphique

Un exemple complet inspiré des panneaux d’information voyageurs est fourni dans [`examples/dashboard_tisseo.yaml`](examples/dashboard_tisseo.yaml). Il affiche :

- des tuiles bleues avec le numéro de ligne, la direction et le prochain passage ;
- trois lignes par rangée sur grand écran ;
- un tableau récapitulatif trié par temps d’attente ;
- les données en temps réel et les horaires prévus.

Copiez la vue dans l’éditeur de configuration brute d’un dashboard Home Assistant, puis adaptez les identifiants `sensor.tisseo_aeroconstellation_*` à vos entités.

## Fonctionnement

- Le référentiel GTFS statique fournit les arrêts, lignes, destinations et horaires.
- Le flux GTFS-Realtime complète les courses diffusées en direct.
- Si une course n’est pas publiée dans le flux temps réel, l’horaire théorique reste affiché.
- Les téléchargements passent par le portail officiel Toulouse Métropole avec une vérification TLS stricte.
- Le flux statique est rafraîchi périodiquement et le flux temps réel utilise `ETag`.

## Données et attribution

Les données de transport proviennent du jeu [Tisséo : Réseau transport urbain toulousain](https://data.toulouse-metropole.fr/explore/dataset/tisseo-gtfs/), publié sous licence ODbL.

Ce projet est une intégration communautaire indépendante. Il n’est ni développé, ni approuvé, ni maintenu par Tisséo ou Toulouse Métropole. Les noms Tisséo et Home Assistant appartiennent à leurs propriétaires respectifs.

## Dépannage

- Après l’installation ou une mise à jour, redémarrer Home Assistant.
- Vérifier que Home Assistant peut joindre `data.toulouse-metropole.fr` en HTTPS.
- En cas d’absence de temps réel, l’horaire théorique peut rester disponible.
- Les journaux se trouvent dans **Paramètres → Système → Journaux** en filtrant sur `tisseo`.

## Contribution

Les signalements de bogues et propositions d’amélioration sont bienvenus dans les issues GitHub. Indiquez la version de Home Assistant, le nom de l’arrêt et les lignes concernées, sans publier de données personnelles.

## Licence

Le code de cette intégration est distribué sous licence [MIT](LICENSE). Les données Tisséo restent soumises à leur licence ODbL.
