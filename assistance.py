#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UCD-CYBERFORCE — Journée d’Intégration (Assistant Terminal)
Version remaniée selon le plan d'amélioration

- Langue: Français uniquement (libellés + messages)
- Dépendances: Standard library uniquement
- Fonctionnalités:
  • Saisie guidée avec validations et indices clairs
  • Détection de doublons par CNE/CNI (remplacer / fusionner / annuler)
  • Recherche / modification / suppression intégrées dans un seul flux
  • Statistiques (total, payés, impayés, total MAD)
  • Exports: CSV + TXT, JSON optionnel
  • Autosauvegarde JSON pour reprise après incident
  • Navigation par pages (N = suivante, P = précédente, Q = retour)

Conseil: utilisez un terminal à largeur >= 100 colonnes pour un rendu optimal.
"""

# ==========================
# === Modèles & types
# ==========================

import re
import csv
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

@dataclass
class Participant:
    nom_complet: str      # 3–80, contient espace
    telephone: str        # ^0[5-7]\d{8}$
    age: int              # 17–30
    CNE: str              # 8–12 alnum
    CNI: str              # 6–12 alnum
    statut_frais: str     # "Payé" | "Impayé"
    montant_mad: float    # >= 0
    notes: str = ""       # optionnel

@dataclass
class Config:
    montant_defaut: float = 20.0
    exiger_tout: bool = True
    statut_defaut: str = "Impayé"
    autosave: bool = True
    export_json: bool = False
    dossier_export: str = "./exports"
    autosave_path: str = ".ucd_cyberforce_autosave.json"
    config_path: str = ".ucd_cyberforce_config.json"

@dataclass
class Stats:
    total: int
    payes: int
    impayes: int
    total_mad: float

Participants = List[Participant]
Index = Dict[str, int]  # map CNE/CNI -> index

# ==========================
# === Couleurs & UI helpers
# ==========================

def ansi_supported() -> bool:
    return os.getenv("TERM") not in (None, "", "dumb")

A_BOLD = "\x1b[1m" if ansi_supported() else ""
A_DIM = "\x1b[2m" if ansi_supported() else ""
C_RED = "\x1b[31m" if ansi_supported() else ""
C_GRN = "\x1b[32m" if ansi_supported() else ""
C_YEL = "\x1b[33m" if ansi_supported() else ""
C_CYN = "\x1b[36m" if ansi_supported() else ""
C_RST = "\x1b[0m" if ansi_supported() else ""

APP_TITLE = f"{A_BOLD}UCD-CYBERFORCE — Journée d’Intégration{C_RST}"

def clear_screen() -> None:
    os.system("clear" if os.name != "nt" else "cls")

def hr(char: str = "─", width: int = 96) -> str:
    return char * width

def box(title: str, lines: List[str], footer: Optional[str] = None, width: int = 96) -> None:
    """Boîte avec en-tête coloré et contenu multi-lignes."""
    t = f" {title} "
    top_inner = t.ljust(width - 2, "─")
    top = "┌" + f"{C_CYN}{A_BOLD}{top_inner}{C_RST}" + "┐"
    bot = "└" + ("─" * (width - 2)) + "┘"
    print(top)
    for line in lines:
        print("│ " + line.ljust(width - 3) + "│")
    if footer:
        print("│ " + footer.ljust(width - 3) + "│")
    print(bot)

def section(title: str) -> None:
    """En-tête de section simple, en cyan."""
    print()
    print(f"{C_CYN}{A_BOLD}── {title}{C_RST}")
    print()

def pause(msg: str = "Appuyez sur Entrée pour continuer...") -> None:
    try:
        input(f"\n{A_DIM}{msg}{C_RST}")
    except EOFError:
        pass

def prompt(label: str, default: Optional[str] = None) -> str:
    if default is not None and str(default).strip() != "":
        s = f"{label} [{default}]: "
    else:
        s = f"{label}: "
    try:
        val = input(s)
    except EOFError:
        return str(default) if default is not None else ""
    if not val.strip() and default is not None:
        return str(default)
    return val.strip()

def notify_ok(msg: str) -> None:
    print(f"{C_GRN}✔ {msg}{C_RST}")

def notify_warn(msg: str) -> None:
    print(f"{C_YEL}! {msg}{C_RST}")

def notify_err(msg: str) -> None:
    print(f"{C_RED}✖ {msg}{C_RST}")

# ==========================
# === Chaînes & messages
# ==========================

S = {
    "bienvenue": "Bienvenue dans l’assistant d’inscription de la Journée d’Intégration.",
    "entete": "Assistant de saisie — UCD-CYBERFORCE (Terminal)",
    "help_title": "Aide rapide",
    "help_lines": [
        "Lancer:  python3 script.py",
        "",
        "Raccourcis principaux :",
        "  E = Enregistrer un nouveau participant",
        "  L = Lister les participants (table paginée)",
        "  R = Rechercher / modifier / supprimer",
        "  T = Basculer Payé/Impayé par index",
        "  X = Exporter (CSV + TXT)",
        "  Q = Quitter le programme",
        "",
        "Navigation table :",
        "  N = Page suivante   P = Page précédente   Q = Retour menu",
    ],
    "setup": {
        "montant_defaut": "Montant par défaut (MAD), ex. 20",
        "dossier_export": "Dossier d’export (ex. ./exports)",
        "exiger_tout": "Exiger tous les champs ? (O/n)",
        "autosave": "Activer l’autosauvegarde ? (O/n)",
        "statut_defaut": "Statut par défaut [P=Payé / I=Impayé]",
        "export_json": "Exporter aussi en JSON ? (o/N)",
    },
    "labels": {
        "nom": "Nom et prénom",
        "tel": "Téléphone",
        "age": "Âge",
        "cne": "CNE",
        "cni": "CNI",
        "statut": "Cotisation",
        "montant": "Montant (MAD)",
        "notes": "Notes",
    },
    "hints": {
        "nom": "3–80 caractères, inclure prénom + nom.",
        "tel": "ex. 06XXXXXXXX (commence par 05/06/07 et 10 chiffres).",
        "age": "Âge entre 17 et 30.",
        "cne": "Alphanumérique 8–12 caractères.",
        "cni": "Alphanumérique 6–12 caractères.",
        "montant": "Nombre ≥ 0. Prérempli si Payé.",
    },
    "erreurs": {
        "obligatoire": "Champ obligatoire.",
        "format": "Format invalide.",
        "plage": "Valeur hors plage.",
        "doublon": "Doublon détecté via CNE/CNI.",
        "introuvable": "Aucun enregistrement trouvé.",
    },
    "confirm": {
        "quitter": "Voulez-vous vraiment quitter ? (O/n)",
        "supprimer": "Confirmer la suppression ? (o/n)",
        "export_avant_quitter": "Exporter avant de quitter ? (O/n)",
    },
    "dedup": "CNE/CNI déjà existant. [R]emplacer, [F]usionner notes, [A]nnuler ?",
    "sauve": "Enregistrement ajouté.",
    "maj": "Enregistrement mis à jour.",
    "supprime": "Enregistrement supprimé.",
    "export_ok": "Export terminé.",
    "reprendre": "Autosauvegarde détectée : données chargées.",
}

# ==========================
# === Saisie & Validations
# ==========================

RX_TEL = re.compile(r"^0[5-7]\d{8}$")
RX_CNE = re.compile(r"^[A-Za-z0-9]{8,12}$")
RX_CNI = re.compile(r"^[A-Za-z0-9]{6,12}$")

def ok_nom(n: str) -> bool:
    n = (n or "").strip()
    return 3 <= len(n) <= 80 and " " in n

def ok_tel(t: str) -> bool:
    return bool(RX_TEL.match((t or "").strip()))

def ok_age(a: int) -> bool:
    return 17 <= a <= 30

def ok_cne(c: str) -> bool:
    return bool(RX_CNE.match((c or "").strip()))

def ok_cni(c: str) -> bool:
    return bool(RX_CNI.match((c or "").strip()))

def ok_montant(v: float) -> bool:
    try:
        return float(v) >= 0.0
    except Exception:
        return False

def normaliser_statut(s: str) -> str:
    s = (s or "").strip().lower()
    if s.startswith("p"):
        return "Payé"
    return "Impayé"

def parse_oui_non(defaut_oui: bool = True, reponse: str = "") -> bool:
    r = (reponse or "").strip().lower()
    if not r:
        return defaut_oui
    return r in ("o", "oui", "y", "yes")

def parse_statut_input(raw: str, default_statut: str) -> str:
    if not raw.strip():
        return normaliser_statut(default_statut)
    r = raw.strip().lower()
    if r in ("p", "payé", "payee", "paye", "oui", "o", "y", "yes"):
        return "Payé"
    if r in ("i", "impayé", "impaye", "non", "n", "no"):
        return "Impayé"
    notify_warn("Entrée non reconnue, utilisation du statut par défaut.")
    return normaliser_statut(default_statut)

def saisir_participant(cfg: Config, existant: Optional[Participant] = None) -> Participant:
    """Saisie guidée d’un participant (création ou édition)."""
    if existant is None:
        p = Participant(
            nom_complet="",
            telephone="",
            age=0,
            CNE="",
            CNI="",
            statut_frais=normaliser_statut(cfg.statut_defaut),
            montant_mad=0.0,
            notes="",
        )
    else:
        p = Participant(**asdict(existant))

    section("Saisie du participant")

    # Nom complet
    while True:
        val = prompt(
            f"{S['labels']['nom']} ({S['hints']['nom']})",
            p.nom_complet or None,
        )
        if not val and cfg.exiger_tout:
            notify_err(S["erreurs"]["obligatoire"])
            continue
        if val and not ok_nom(val):
            notify_err(S["hints"]["nom"])
            continue
        p.nom_complet = val
        break

    # Téléphone
    while True:
        val = prompt(
            f"{S['labels']['tel']} ({S['hints']['tel']})",
            p.telephone or None,
        )
        if not val and cfg.exiger_tout:
            notify_err(S["erreurs"]["obligatoire"])
            continue
        if val and not ok_tel(val):
            notify_err(S["hints"]["tel"])
            continue
        p.telephone = val
        break

    # Âge
    while True:
        val = prompt(
            f"{S['labels']['age']} ({S['hints']['age']})",
            str(p.age or "") if p.age else None,
        )
        if not val and cfg.exiger_tout:
            notify_err(S["erreurs"]["obligatoire"])
            continue
        if not val:
            p.age = 0
            break
        try:
            n = int(val)
        except Exception:
            notify_err(S["erreurs"]["format"])
            continue
        if not ok_age(n):
            notify_err(S["hints"]["age"])
            continue
        p.age = n
        break

    # CNE
    while True:
        val = prompt(
            f"{S['labels']['cne']} ({S['hints']['cne']})",
            p.CNE or None,
        )
        if not val and cfg.exiger_tout:
            notify_err(S["erreurs"]["obligatoire"])
            continue
        if val and not ok_cne(val):
            notify_err(S["hints"]["cne"])
            continue
        p.CNE = val.upper()
        break

    # CNI
    while True:
        val = prompt(
            f"{S['labels']['cni']} ({S['hints']['cni']})",
            p.CNI or None,
        )
        if not val and cfg.exiger_tout:
            notify_err(S["erreurs"]["obligatoire"])
            continue
        if val and not ok_cni(val):
            notify_err(S["hints"]["cni"])
            continue
        p.CNI = val.upper()
        break

    # Statut cotisation
    default_statut = p.statut_frais or cfg.statut_defaut
    label_statut = f"{S['labels']['statut']} [P=Payé / I=Impayé] (défaut: {normaliser_statut(default_statut)})"
    val = prompt(label_statut, "")
    p.statut_frais = parse_statut_input(val, default_statut)

    # Montant MAD
    while True:
        if p.statut_frais == "Payé":
            defaut = str(p.montant_mad if p.montant_mad > 0 else cfg.montant_defaut)
        else:
            defaut = str(p.montant_mad if p.montant_mad > 0 else 0)
        val = prompt(
            f"{S['labels']['montant']} ({S['hints']['montant']})",
            defaut,
        )
        if not val:
            # Payé = montant défaut ; Impayé = 0
            p.montant_mad = cfg.montant_defaut if p.statut_frais == "Payé" else 0.0
            break
        try:
            x = float(val)
        except Exception:
            notify_err(S["erreurs"]["format"])
            continue
        if not ok_montant(x):
            notify_err(S["erreurs"]["plage"])
            continue
        p.montant_mad = x
        break

    # Notes (optionnel)
    val = prompt(S["labels"]["notes"], p.notes or "")
    p.notes = val

    return p

# ==========================
# === Sauvegarde & Export
# ==========================

def save_config(cfg: Config) -> None:
    try:
        with open(cfg.config_path, "w", encoding="utf-8") as f:
            json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_config() -> Config:
    cfg = Config()
    if os.path.exists(cfg.config_path):
        try:
            with open(cfg.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        except Exception:
            pass
    # normaliser statut_defaut
    cfg.statut_defaut = normaliser_statut(cfg.statut_defaut)
    return cfg

def autosave(cfg: Config, rows: Participants) -> None:
    if not cfg.autosave:
        return
    try:
        with open(cfg.autosave_path, "w", encoding="utf-8") as f:
            json.dump([asdict(p) for p in rows], f, ensure_ascii=False)
    except Exception:
        pass

def load_autosave(cfg: Config) -> Participants:
    if not os.path.exists(cfg.autosave_path):
        return []
    try:
        with open(cfg.autosave_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rows = [Participant(**d) for d in data]
        if rows:
            notify_ok(S["reprendre"])
        return rows
    except Exception:
        return []

def exporter_tout(cfg: Config, rows: Participants) -> Tuple[str, str, Optional[str]]:
    """Exporte toujours CSV + TXT, JSON seulement si cfg.export_json == True."""
    out_dir = Path(cfg.dossier_export)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "participants_integration.csv"
    txt_path = out_dir / "participants_integration.txt"
    json_path = out_dir / "participants_integration.json"

    # CSV
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["nom_complet", "telephone", "age", "CNE", "CNI", "montant_mad", "statut_frais", "notes"]
        )
        for p in rows:
            w.writerow(
                [
                    p.nom_complet,
                    p.telephone,
                    p.age,
                    p.CNE,
                    p.CNI,
                    f"{p.montant_mad:.0f}",
                    p.statut_frais,
                    p.notes,
                ]
            )

    # TXT (table + stats)
    lines_out: List[str] = []
    lines_out.append(APP_TITLE)
    lines_out.append(hr())
    lines_out += render_table(rows, page=0, page_size=max(1, len(rows)))
    st = stats(rows)
    lines_out.append("")
    lines_out.append(
        f"Résumé — Participants: {st.total}  Payés: {st.payes}  "
        f"Impayés: {st.impayes}  Total MAD: {st.total_mad:.0f}"
    )
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines_out) + "\n")

    json_result: Optional[str] = None
    if cfg.export_json:
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump([asdict(p) for p in rows], f, ensure_ascii=False, indent=2)
            json_result = str(json_path)
        except Exception:
            json_result = None

    return str(csv_path), str(txt_path), json_result

# ==========================
# === Index, stats & table
# ==========================

def indexer(rows: Participants) -> Tuple[Index, Index]:
    by_cne: Index = {}
    by_cni: Index = {}
    for i, p in enumerate(rows):
        if p.CNE:
            by_cne[p.CNE.upper()] = i
        if p.CNI:
            by_cni[p.CNI.upper()] = i
    return by_cne, by_cni

def doublon(p: Participant, idx_cne: Index, idx_cni: Index) -> Optional[int]:
    if p.CNE and p.CNE.upper() in idx_cne:
        return idx_cne[p.CNE.upper()]
    if p.CNI and p.CNI.upper() in idx_cni:
        return idx_cni[p.CNI.upper()]
    return None

def fusionner(old: Participant, new: Participant) -> Participant:
    merged = Participant(**asdict(new))
    if old.notes.strip() and new.notes.strip() and old.notes.strip() != new.notes.strip():
        merged.notes = f"{old.notes} | {new.notes}"
    elif not new.notes.strip():
        merged.notes = old.notes
    return merged

def stats(rows: Participants) -> Stats:
    total = len(rows)
    payes = sum(1 for p in rows if p.statut_frais == "Payé")
    impayes = total - payes
    total_mad = sum(p.montant_mad for p in rows if p.statut_frais == "Payé")
    return Stats(total=total, payes=payes, impayes=impayes, total_mad=total_mad)

HEADERS = {
    "index": "#",
    "nom": "Nom complet",
    "tel": "Téléphone",
    "age": "Âge",
    "cne": "CNE",
    "cni": "CNI",
    "montant": "Montant",
    "statut": "Statut",
    "notes": "Notes",
}

COLS = [
    ("nom", 24),
    ("tel", 12),
    ("age", 3),
    ("cne", 12),
    ("cni", 12),
    ("montant", 8),
    ("statut", 7),
    ("notes", 28),
]

def fmt_cell(v, w: int) -> str:
    s = str(v)
    return s if len(s) <= w else s[: max(0, w - 1)] + "…"

def render_table(rows: Participants, page: int = 0, page_size: int = 12) -> List[str]:
    start = page * page_size
    chunk = rows[start : start + page_size]
    header = " │ ".join(fmt_cell(HEADERS[k], w) for k, w in COLS)
    sep = "─" * len(header)
    body: List[str] = []
    for i, p in enumerate(chunk, start=start):
        data = [
            (p.nom_complet, 24),
            (p.telephone, 12),
            (p.age, 3),
            (p.CNE, 12),
            (p.CNI, 12),
            (f"{p.montant_mad:.0f}", 8),
            (p.statut_frais, 7),
            (p.notes, 28),
        ]
        row = f"{A_DIM}{str(i).rjust(3)}{C_RST} " + " │ ".join(
            fmt_cell(v, w) for v, w in data
        )
        body.append(row)
    total_pages = max(1, (len(rows) - 1) // page_size + 1)
    footer = f"Page {page+1}/{total_pages} — Total: {len(rows)}"
    return [f"{C_CYN}{A_BOLD}{header}{C_RST}", sep, *body, sep, footer]

def print_stats(rows: Participants) -> None:
    st = stats(rows)
    print()
    print(
        f"{A_BOLD}Statistiques — Participants: {st.total}  Payés: {st.payes}  "
        f"Impayés: {st.impayes}  Total MAD: {st.total_mad:.0f}{C_RST}"
    )

def lister_pagine(rows: Participants, titre: str = "Table des participants") -> None:
    if not rows:
        notify_warn("Aucune donnée à afficher.")
        pause()
        return
    page = 0
    page_size = 12
    total_pages = max(1, (len(rows) - 1) // page_size + 1)
    while True:
        clear_screen()
        section(titre)
        table_lines = render_table(rows, page=page, page_size=page_size)
        box(
            titre,
            table_lines,
            footer="N = Page suivante | P = Page précédente | Q = Retour menu",
        )
        print_stats(rows)
        k = input("\nVotre choix (N/P/Q) : ").strip().lower()
        if k == "p":
            page = max(0, page - 1)
        elif k == "n":
            page = min(total_pages - 1, page + 1)
        elif k in ("q", ""):
            break

# ==========================
# === Recherche & actions
# ==========================

def recherche(rows: Participants, q: str) -> List[int]:
    q = (q or "").strip().lower()
    if not q:
        return []
    hits: List[int] = []
    for i, p in enumerate(rows):
        if (q in p.nom_complet.lower()) or (q in p.telephone) or (q == p.CNE.lower()) or (q == p.CNI.lower()):
            hits.append(i)
    return hits

def modifier_dialogue(rows: Participants, idx: int, cfg: Config) -> None:
    if not (0 <= idx < len(rows)):
        notify_err(S["erreurs"]["introuvable"])
        return
    section(f"Modification de l’index {idx}")
    nouveau = saisir_participant(cfg, existant=rows[idx])
    rows[idx] = nouveau
    autosave(cfg, rows)
    notify_ok(S["maj"])

def basculer_paye(rows: Participants, idx: int, cfg: Config) -> None:
    if not (0 <= idx < len(rows)):
        notify_err(S["erreurs"]["introuvable"])
        return
    p = rows[idx]
    if p.statut_frais == "Payé":
        p.statut_frais = "Impayé"
    else:
        p.statut_frais = "Payé"
        if not ok_montant(p.montant_mad) or p.montant_mad <= 0:
            p.montant_mad = cfg.montant_defaut
    autosave(cfg, rows)
    notify_ok(S["maj"])

def ajouter_participant(cfg: Config, rows: Participants) -> None:
    nouveau = saisir_participant(cfg)
    idx_cne, idx_cni = indexer(rows)
    di = doublon(nouveau, idx_cne, idx_cni)
    if di is not None:
        rep = input(f"{C_YEL}{S['dedup']}{C_RST} ").strip().lower()
        if rep.startswith("r"):  # Remplacer
            rows[di] = nouveau
            notify_ok(S["maj"])
        elif rep.startswith("f"):  # Fusionner
            rows[di] = fusionner(rows[di], nouveau)
            notify_ok(S["maj"])
        else:
            notify_warn("Ajout annulé.")
            return
    else:
        rows.append(nouveau)
        notify_ok(S["sauve"])
    autosave(cfg, rows)

def recherche_workflow(cfg: Config, rows: Participants) -> None:
    clear_screen()
    section("Recherche / modification / suppression")
    q = input("Rechercher (nom, téléphone, CNE ou CNI) : ").strip()
    ids = recherche(rows, q)
    if not ids:
        notify_warn(S["erreurs"]["introuvable"])
        pause()
        return

    print(f"\nRésultats (index globaux): {ids}")
    subset = [rows[i] for i in ids]
    lister_pagine(subset, titre="Résultats de la recherche")

    print()
    action = input("[M]odifier / [S]upprimer / [Entrée] retour : ").strip().lower()
    if not action:
        return

    try:
        idx = int(input("Index global de l’enregistrement cible : ").strip())
    except Exception:
        notify_err(S["erreurs"]["format"])
        pause()
        return

    if not (0 <= idx < len(rows)):
        notify_err(S["erreurs"]["introuvable"])
        pause()
        return

    if action.startswith("m"):
        modifier_dialogue(rows, idx, cfg)
    elif action.startswith("s"):
        if input(f"{S['confirm']['supprimer']} ").strip().lower().startswith("o"):
            rows.pop(idx)
            autosave(cfg, rows)
            notify_ok(S["supprime"])
        else:
            notify_warn("Suppression annulée.")
    else:
        notify_warn("Action inconnue.")
    pause()

# ==========================
# === Menu & Logique principale
# ==========================

def afficher_menu() -> None:
    section("Menu principal")
    print("E  Enregistrer un nouveau participant")
    print("L  Lister les participants")
    print()
    print("R  Rechercher / modifier / supprimer")
    print("T  Basculer Payé/Impayé par index")
    print()
    print("X  Exporter (CSV + TXT)")
    print("Q  Quitter")
    print()
    print(f"{A_DIM}Astuce : tapez 'h' pour l’aide rapide.{C_RST}")

def show_help() -> None:
    clear_screen()
    box(S["help_title"], S["help_lines"])
    pause()

def config_simple(cfg: Config) -> Config:
    section("Mode simple — Configuration minimale")
    m = prompt(S["setup"]["montant_defaut"], str(cfg.montant_defaut))
    try:
        cfg.montant_defaut = float(m)
    except Exception:
        pass
    # le reste = valeurs recommandées
    cfg.exiger_tout = True
    cfg.autosave = True
    cfg.statut_defaut = "Impayé"
    cfg.export_json = False
    save_config(cfg)
    return cfg

def config_avancee(cfg: Config) -> Config:
    section("Mode avancé — Configuration détaillée")
    print(f"Montant par défaut actuel : {cfg.montant_defaut} MAD")
    print(f"Dossier d’export actuel  : {cfg.dossier_export}")
    print(f"Exiger tous les champs   : {'Oui' if cfg.exiger_tout else 'Non'}")
    print(f"Autosauvegarde           : {'Oui' if cfg.autosave else 'Non'}")
    print(f"Statut par défaut        : {cfg.statut_defaut}")
    print(f"Export JSON              : {'Oui' if cfg.export_json else 'Non'}")
    print()

    m = prompt(S["setup"]["montant_defaut"], str(cfg.montant_defaut))
    try:
        cfg.montant_defaut = float(m)
    except Exception:
        pass

    d = prompt(S["setup"]["dossier_export"], cfg.dossier_export)
    if d.strip():
        cfg.dossier_export = d.strip()

    e = prompt(S["setup"]["exiger_tout"], "O" if cfg.exiger_tout else "n")
    cfg.exiger_tout = parse_oui_non(defaut_oui=cfg.exiger_tout, reponse=e)

    a = prompt(S["setup"]["autosave"], "O" if cfg.autosave else "n")
    cfg.autosave = parse_oui_non(defaut_oui=cfg.autosave, reponse=a)

    s = prompt(S["setup"]["statut_defaut"], cfg.statut_defaut)
    cfg.statut_defaut = normaliser_statut(s or cfg.statut_defaut)

    j = prompt(S["setup"]["export_json"], "n" if not cfg.export_json else "o")
    cfg.export_json = parse_oui_non(defaut_oui=cfg.export_json, reponse=j)

    save_config(cfg)
    return cfg

def etape_demarrage(cfg: Config) -> Config:
    clear_screen()
    box(
        APP_TITLE,
        [
            S["bienvenue"],
            "",
            "Utiliser la configuration recommandée ?",
        ],
    )
    rep = input("Utiliser la configuration recommandée ? (O/n) ").strip().lower()
    if rep in ("", "o", "oui", "y", "yes"):
        # Configuration recommandée
        cfg.montant_defaut = 20.0
        cfg.exiger_tout = True
        cfg.statut_defaut = "Impayé"
        cfg.autosave = True
        cfg.export_json = False
        save_config(cfg)
        return cfg

    # Sinon : mode simple ou avancé
    while True:
        clear_screen()
        box(
            APP_TITLE,
            [
                "Choisissez votre mode de configuration :",
                "",
                "S  Mode simple (uniquement le montant par défaut)",
                "A  Mode avancé (tous les paramètres)",
            ],
        )
        mode = input("Votre choix (S/A) : ").strip().lower()
        if mode in ("s", ""):
            cfg = config_simple(cfg)
            break
        elif mode in ("a", "avancé", "avance"):
            cfg = config_avancee(cfg)
            break
        else:
            notify_warn("Choix invalide. Utilisez S ou A.")
            pause()
    return cfg

def assistant() -> None:
    clear_screen()
    cfg = load_config()
    rows: Participants = load_autosave(cfg)

    # 1) écran d’accueil + configuration recommandée / simple / avancée
    cfg = etape_demarrage(cfg)

    # 2) boucle principale (menu simplifié)
    while True:
        clear_screen()
        print(APP_TITLE)
        print(S["entete"])
        print()
        afficher_menu()
        print_stats(rows)
        choix = input("\nVotre choix : ").strip().lower()

        if choix == "h":
            show_help()

        elif choix == "e":
            clear_screen()
            ajouter_participant(cfg, rows)
            pause()

        elif choix == "l":
            lister_pagine(rows)

        elif choix == "r":
            recherche_workflow(cfg, rows)

        elif choix == "t":
            try:
                idx = int(input("Index pour basculer Payé/Impayé : ").strip())
            except Exception:
                notify_err(S["erreurs"]["format"])
                pause()
                continue
            basculer_paye(rows, idx, cfg)
            pause()

        elif choix == "x":
            if not rows:
                notify_warn("Aucun participant à exporter.")
                pause()
                continue
            clear_screen()
            section("Export des participants")
            csvp, txtp, jsp = exporter_tout(cfg, rows)
            print()
            print("✔ Export terminé :")
            print(f"  - {os.path.basename(csvp)}")
            print(f"  - {os.path.basename(txtp)}")
            if jsp:
                print(f"  - {os.path.basename(jsp)} (JSON)")
            print(f"\nDossier : {os.path.dirname(csvp) or '.'}")
            pause()

        elif choix == "q":
            # Confirmation de sortie + option d’export
            if not input(f"{S['confirm']['quitter']} ").strip().lower().startswith("o"):
                continue
            if rows:
                if input(f"{S['confirm']['export_avant_quitter']} ").strip().lower().startswith("o"):
                    clear_screen()
                    section("Export final avant sortie")
                    csvp, txtp, jsp = exporter_tout(cfg, rows)
                    print()
                    print("✔ Export terminé :")
                    print(f"  - {os.path.basename(csvp)}")
                    print(f"  - {os.path.basename(txtp)}")
                    if jsp:
                        print(f"  - {os.path.basename(jsp)} (JSON)")
                    print(f"\nDossier : {os.path.dirname(csvp) or '.'}")
                    print_stats(rows)
                    pause("Appuyez sur Entrée pour quitter...")
            print("\nMerci. À bientôt !")
            break

        else:
            notify_warn("Choix inconnu. Utilisez les lettres proposées.")
            pause()

# ==========================
# === Point d’entrée
# ==========================

if __name__ == "__main__":
    try:
        assistant()
    except KeyboardInterrupt:
        print("\nInterruption : au revoir.")
