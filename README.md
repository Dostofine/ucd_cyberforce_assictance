# 🛡️ Assistant d'Inscription UCD-CYBERFORCE

Assistant terminal en Python pour la gestion des inscriptions de la Journée d'Intégration. Ce projet utilise uniquement la bibliothèque standard pour une portabilité maximale.

## ✨ Points Forts
* **Saisie Guidée** : Validation stricte des numéros de téléphone, CNE (8-12 car.) et CNI (6-12 car.).
* **Gestion des Doublons** : Détection automatique par CNE/CNI avec options de fusion des notes.
* **Statistiques** : Calcul automatique des totaux et des montants en MAD.
* **Exports** : Génération de rapports aux formats CSV et TXT.

## 🚀 Installation
1. Clonez le dépôt :
   ```bash
   git clone [https://github.com/Dostofine/ucd_cyberforce_assictance.git]
2.Lancez l'application :
    python assistance.py

## 🛠️ Configuration
Le script propose trois modes au démarrage :

Recommandé : Paramètres par défaut optimisés.

Simple : Configuration rapide du montant de base.

Avancé : Personnalisation complète (dossier d'export, format JSON, etc.).

